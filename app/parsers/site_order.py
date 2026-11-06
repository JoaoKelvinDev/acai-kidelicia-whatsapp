"""Reconhecimento e extração do pedido no formato atual do site.

O reconhecimento é estrutural (rótulos conhecidos), não por palavra-chave ou emoji. Nada
que não seja reconhecido é descartado em silêncio: rótulos desconhecidos e linhas soltas
ficam registrados no rascunho para conferência humana.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from app.domain.models import OrderDraft, OrderItem, RawField
from app.parsers.money import parse_brl
from app.parsers.normalize import clean_lines, fold
from app.parsers.values import (
    parse_change,
    parse_list,
    parse_modality,
    parse_payment,
    parse_quantity,
)

ORDER_FIELDS = (
    "nome", "telefone", "modalidade", "endereco", "referencia",
    "taxa_entrega", "pagamento", "troco",
)  # fmt: skip
ITEM_FIELDS = ("quantidade", "tamanho", "base", "cremes", "sorvetes", "adicionais")

_ORDER_ALIASES: dict[str, tuple[str, ...]] = {
    "nome": ("Nome", "Nome completo", "Cliente", "Nome do cliente"),
    "telefone": ("Telefone", "Tel", "Fone", "Celular", "WhatsApp", "Telefone de contato"),
    "modalidade": ("Modalidade", "Tipo de entrega", "Tipo de pedido", "Forma de entrega"),
    "endereco": ("Endereço", "Endereço de entrega", "Endereço completo"),
    "referencia": ("Ponto de referência", "Referência", "Ponto de ref"),
    "taxa_entrega": ("Taxa de entrega", "Taxa", "Frete", "Taxa de delivery"),
    "pagamento": ("Pagamento", "Forma de pagamento", "Método de pagamento", "Pagar com"),
    "troco": ("Troco", "Troco para", "Troco pra", "Precisa de troco"),
}
_ITEM_ALIASES: dict[str, tuple[str, ...]] = {
    "quantidade": ("Quantidade", "Qtd", "Qtde", "Quant"),
    "tamanho": ("Tamanho", "Recipiente"),
    "base": ("Base",),
    "cremes": ("Cremes", "Creme"),
    "sorvetes": ("Sorvetes", "Sorvete"),
    "adicionais": ("Adicionais", "Adicional", "Complementos", "Complemento"),
}


def _variants(alias: str) -> set[str]:
    # Inclui a forma sem letras não-ASCII: "Endere�o" vira "endereo" após remover o "�".
    ascii_only = "".join(c for c in alias if ord(c) < 128)
    return {fold(alias), fold(ascii_only)}


def _label_table(aliases: dict[str, tuple[str, ...]]) -> dict[str, str]:
    return {v: field for field, names in aliases.items() for a in names for v in _variants(a)}


_ORDER_LABELS = _label_table(_ORDER_ALIASES)
_ITEM_LABELS = _label_table(_ITEM_ALIASES)
_HEADER_RE = re.compile(r"^novo pedido\b")
_ITEM_BREAK_RE = re.compile(r"^(item|acai|copo|pedido)\s*\d+$")
_SECTION_HEADERS = frozenset(
    {"pedido", "itens", "itens do pedido", "seu pedido", "resumo", "resumo do pedido"}
)
_FOOTERS = frozenset(
    {"obrigado", "obrigada", "muito obrigado", "muito obrigada", "obrigado pela preferencia"}
)


class LineKind(StrEnum):
    HEADER = "header"
    SECTION = "section"
    ITEM_BREAK = "item_break"
    FOOTER = "footer"
    ORDER_FIELD = "order_field"
    ITEM_FIELD = "item_field"
    UNKNOWN_FIELD = "unknown_field"
    TEXT = "text"


@dataclass(frozen=True)
class ScannedLine:
    kind: LineKind
    text: str
    field: str | None = None
    label: str = ""
    value: str = ""


def scan_line(line: str) -> ScannedLine:
    folded = fold(line)
    if _HEADER_RE.match(folded):
        return ScannedLine(LineKind.HEADER, line)
    if folded in _SECTION_HEADERS:
        return ScannedLine(LineKind.SECTION, line)
    if _ITEM_BREAK_RE.match(folded):
        return ScannedLine(LineKind.ITEM_BREAK, line)
    if folded in _FOOTERS:
        return ScannedLine(LineKind.FOOTER, line)
    label, sep, value = line.partition(":")
    if sep:
        key, value = fold(label), value.strip()
        label = label.strip()
        if key in _ORDER_LABELS:
            return ScannedLine(LineKind.ORDER_FIELD, line, _ORDER_LABELS[key], label, value)
        if key in _ITEM_LABELS:
            return ScannedLine(LineKind.ITEM_FIELD, line, _ITEM_LABELS[key], label, value)
        if key:
            return ScannedLine(LineKind.UNKNOWN_FIELD, line, None, label, value)
    return ScannedLine(LineKind.TEXT, line)


def scan(text: str) -> list[ScannedLine]:
    return [scan_line(line) for line in clean_lines(text)]


def is_site_order(text: str) -> bool:
    lines = scan(text)
    order = {ln.field for ln in lines if ln.kind is LineKind.ORDER_FIELD}
    items = {ln.field for ln in lines if ln.kind is LineKind.ITEM_FIELD}
    has_header = any(ln.kind is LineKind.HEADER for ln in lines)
    if has_header and len(order) + len(items) >= 2:
        return True
    return len(order) >= 2 and len(items) >= 1


def fingerprint(text: str) -> str:
    canonical = "\n".join(fold(line) for line in clean_lines(text))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _none_if_empty(value: str) -> str | None:
    return value or None


def set_order_field(draft: OrderDraft, field: str, raw: str) -> None:
    """Aplica um valor bruto a um campo do pedido, mantendo o texto original."""
    raw = raw.strip()
    draft.raw_fields[field] = raw
    match field:
        case "nome":
            draft.name = _none_if_empty(raw)
        case "telefone":
            draft.phone_raw = _none_if_empty(raw)
        case "modalidade":
            draft.modality_raw = _none_if_empty(raw)
            draft.modality = parse_modality(raw)
        case "endereco":
            draft.address = _none_if_empty(raw)
        case "referencia":
            draft.reference = _none_if_empty(raw)
        case "taxa_entrega":
            draft.delivery_fee_raw = _none_if_empty(raw)
            draft.delivery_fee = parse_brl(raw) if raw else None
            draft.delivery_fee_verified = False
        case "pagamento":
            draft.payment_raw = _none_if_empty(raw)
            draft.payment = parse_payment(raw)
            if "troco" in fold(raw):
                _apply_change(draft, raw)
        case "troco":
            _apply_change(draft, raw)
        case _:
            raise ValueError(f"campo de pedido desconhecido: {field}")


def _apply_change(draft: OrderDraft, raw: str) -> None:
    draft.change_raw = _none_if_empty(raw)
    needed, amount = parse_change(raw)
    if needed is None:
        return
    draft.change_needed = needed
    draft.change_for = amount if needed else None


def _set_item_field(item: OrderItem, field: str, raw: str) -> None:
    match field:
        case "quantidade":
            item.quantity_raw = _none_if_empty(raw)
            item.quantity = parse_quantity(raw)
        case "tamanho":
            item.size = _none_if_empty(raw)
        case "base":
            item.base = _none_if_empty(raw)
        case "cremes":
            item.creams = parse_list(raw)
        case "sorvetes":
            item.ice_creams = parse_list(raw)
        case "adicionais":
            item.extras = parse_list(raw)


def parse_site_order(
    text: str, *, conversation_id: str, source_message_id: str, now: datetime
) -> OrderDraft:
    draft = OrderDraft(
        conversation_id=conversation_id,
        source_message_id=source_message_id,
        fingerprint=fingerprint(text),
        created_at=now,
        updated_at=now,
    )
    current: OrderItem | None = None
    seen_in_item: set[str] = set()

    for line in scan(text):
        match line.kind:
            case LineKind.ORDER_FIELD:
                assert line.field is not None
                previous = draft.raw_fields.get(line.field)
                if previous is not None and fold(previous) != fold(line.value):
                    if line.field not in draft.repeated_fields:
                        draft.repeated_fields.append(line.field)
                    continue
                set_order_field(draft, line.field, line.value)
            case LineKind.ITEM_FIELD:
                assert line.field is not None
                if current is None or line.field == "quantidade" or line.field in seen_in_item:
                    current = OrderItem(position=len(draft.items) + 1)
                    draft.items.append(current)
                    seen_in_item = set()
                seen_in_item.add(line.field)
                _set_item_field(current, line.field, line.value)
            case LineKind.ITEM_BREAK:
                current = None
            case LineKind.UNKNOWN_FIELD:
                raw_field = RawField(label=line.label, value=line.value)
                target = current.unknown_fields if current else draft.unknown_fields
                target.append(raw_field)
            case LineKind.TEXT:
                draft.unparsed_lines.append(line.text)
            case LineKind.HEADER | LineKind.SECTION | LineKind.FOOTER:
                pass
    return draft
