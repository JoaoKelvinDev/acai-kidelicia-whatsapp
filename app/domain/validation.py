"""Validação do rascunho: separa ausentes, inválidos e condições não verificáveis.

- Problemas em campos de cadastro (nome, telefone, endereço…) são perguntados ao cliente.
- Problemas em itens, estrutura ou taxa vão para conferência humana (requires_human).
- Notas não verificáveis (taxa editável, telefone diferente do remetente) não bloqueiam.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from app.domain.enums import IssueKind, Modality, PaymentMethod
from app.domain.models import Issue, OrderDraft
from app.domain.phone import check_br_phone, same_phone
from app.domain.store import StoreSettings
from app.parsers.normalize import fold

CUSTOMER_FIELDS: frozenset[str] = frozenset(
    {"nome", "telefone", "modalidade", "endereco", "referencia", "pagamento", "troco",
     "troco_valor"}
)  # fmt: skip

_PLACEHOLDER_WORDS = frozenset(
    {
        "teste", "test", "testando", "nome", "fulano", "ciclano", "beltrano", "cliente",
        "x", "xx", "xxx", "aaa", "asd", "asdf", "abc", "qwe", "qwerty", "exemplo",
        "endereco", "rua", "referencia", "ponto", "de", "n", "a", "na", "null", "none",
        "undefined", "ok",
    }
)  # fmt: skip
_NO_REFERENCE = frozenset(
    {"nao tem", "nao possui", "nao ha", "nenhum", "nenhuma", "sem referencia", "sem", "nao"}
)


def _filled(value: str | None) -> bool:
    return bool(value and value.strip())


def is_placeholder(value: str) -> bool:
    f = fold(value)
    if not re.search(r"[a-z]", f):
        return True
    compact = f.replace(" ", "")
    if len(set(compact)) == 1:
        return True
    return all(word in _PLACEHOLDER_WORDS for word in f.split())


@dataclass(frozen=True)
class ValidationResult:
    issues: list[Issue]

    @property
    def customer_issues(self) -> list[Issue]:
        return [
            i
            for i in self.issues
            if i.kind in (IssueKind.MISSING, IssueKind.INVALID) and not i.requires_human
        ]

    @property
    def review_issues(self) -> list[Issue]:
        return [i for i in self.issues if i.requires_human]

    @property
    def notes(self) -> list[Issue]:
        return [i for i in self.issues if i.kind is IssueKind.UNVERIFIABLE and not i.requires_human]

    @property
    def requires_human(self) -> bool:
        return bool(self.review_issues)

    @property
    def pending_fields(self) -> list[str]:
        return list(dict.fromkeys(i.field for i in self.customer_issues))

    def has_note(self, code: str) -> bool:
        return any(i.code == code for i in self.notes)


def validate_draft(
    draft: OrderDraft, store: StoreSettings, sender_id: str | None = None
) -> ValidationResult:
    issues: list[Issue] = []

    def add(kind: IssueKind, field: str, code: str, *, human: bool = False) -> None:
        # Só campos de cadastro podem ser corrigidos pelo cliente; o resto vai para a equipe.
        if kind is not IssueKind.UNVERIFIABLE and field not in CUSTOMER_FIELDS:
            human = True
        issues.append(Issue(kind=kind, field=field, code=code, requires_human=human))

    # Nome
    if not _filled(draft.name):
        add(IssueKind.MISSING, "nome", "ausente")
    elif is_placeholder(draft.name or ""):
        add(IssueKind.INVALID, "nome", "placeholder")

    # Telefone (dado do pedido; a identidade da conversa é o remetente do WhatsApp)
    if not _filled(draft.phone_raw):
        add(IssueKind.MISSING, "telefone", "ausente")
    else:
        check = check_br_phone(draft.phone_raw or "", accept_landline=store.accept_landline)
        if check.error:
            add(IssueKind.INVALID, "telefone", check.error)
        elif sender_id and check.normalized and not same_phone(check.normalized, sender_id):
            add(IssueKind.UNVERIFIABLE, "telefone", "diferente_do_remetente")

    # Modalidade e dados de entrega
    if not _filled(draft.modality_raw):
        add(IssueKind.MISSING, "modalidade", "ausente")
    elif draft.modality is None:
        add(IssueKind.INVALID, "modalidade", "nao_reconhecida")

    if draft.modality is Modality.DELIVERY:
        _validate_delivery(draft, store, add)
    elif draft.modality is Modality.PICKUP and draft.delivery_fee and draft.delivery_fee > 0:
        add(IssueKind.UNVERIFIABLE, "taxa_entrega", "taxa_em_retirada")

    # Itens: qualquer problema vai para a equipe (mudança de itens exige humano)
    if not draft.items:
        add(IssueKind.MISSING, "itens", "ausente", human=True)
    for item in draft.items:
        prefix = f"itens[{item.position}]"
        if not _filled(item.quantity_raw):
            add(IssueKind.MISSING, f"{prefix}.quantidade", "ausente", human=True)
        elif item.quantity is None or item.quantity <= 0:
            add(IssueKind.INVALID, f"{prefix}.quantidade", "nao_inteira_positiva", human=True)
        if "tamanho" in store.required_item_fields and not _filled(item.size):
            add(IssueKind.MISSING, f"{prefix}.tamanho", "ausente", human=True)
        if "base" in store.required_item_fields and not _filled(item.base):
            add(IssueKind.MISSING, f"{prefix}.base", "ausente", human=True)
        if store.allowed_sizes is not None and _filled(item.size):
            allowed = {fold(s) for s in store.allowed_sizes}
            if fold(item.size or "") not in allowed:
                add(IssueKind.INVALID, f"{prefix}.tamanho", "fora_do_catalogo", human=True)
        if item.unknown_fields:
            add(IssueKind.UNVERIFIABLE, prefix, "campos_desconhecidos", human=True)

    # Pagamento e troco
    if not _filled(draft.payment_raw):
        add(IssueKind.MISSING, "pagamento", "ausente")
    elif draft.payment is None:
        add(IssueKind.INVALID, "pagamento", "nao_reconhecido")
    if draft.modality is Modality.DELIVERY and draft.payment is PaymentMethod.CASH:
        if draft.change_needed is None:
            add(IssueKind.MISSING, "troco", "ausente")
        elif draft.change_needed and draft.change_for is None:
            add(IssueKind.MISSING, "troco_valor", "ausente")
        elif draft.change_needed and draft.change_for is not None and draft.change_for <= 0:
            add(IssueKind.INVALID, "troco_valor", "nao_positivo")

    # Estrutura do texto
    if draft.unknown_fields:
        add(IssueKind.UNVERIFIABLE, "pedido", "campos_desconhecidos", human=True)
    if draft.unparsed_lines:
        add(IssueKind.UNVERIFIABLE, "pedido", "linhas_nao_reconhecidas", human=True)
    if draft.repeated_fields:
        add(IssueKind.UNVERIFIABLE, "pedido", "campos_repetidos_divergentes", human=True)
    if draft.possible_duplicate_of:
        add(IssueKind.UNVERIFIABLE, "pedido", "possivel_duplicidade", human=True)

    return ValidationResult(issues)


class _AddIssue(Protocol):
    def __call__(self, kind: IssueKind, field: str, code: str, *, human: bool = False) -> None: ...


def _validate_delivery(draft: OrderDraft, store: StoreSettings, add: _AddIssue) -> None:
    if not _filled(draft.address):
        add(IssueKind.MISSING, "endereco", "ausente")
    elif is_placeholder(draft.address or ""):
        add(IssueKind.INVALID, "endereco", "placeholder")

    if store.require_reference_for_delivery:
        if not _filled(draft.reference):
            add(IssueKind.MISSING, "referencia", "ausente")
        elif fold(draft.reference or "") in _NO_REFERENCE:
            add(IssueKind.UNVERIFIABLE, "referencia", "sem_referencia_declarada")
        elif is_placeholder(draft.reference or ""):
            add(IssueKind.INVALID, "referencia", "placeholder")

    if _filled(draft.delivery_fee_raw):
        if draft.delivery_fee is None:
            add(IssueKind.INVALID, "taxa_entrega", "nao_reconhecida", human=True)
        elif draft.delivery_fee < 0:
            add(IssueKind.INVALID, "taxa_entrega", "negativa", human=True)
        else:
            add(IssueKind.UNVERIFIABLE, "taxa_entrega", "nao_verificada")
    else:
        add(IssueKind.UNVERIFIABLE, "taxa_entrega", "nao_informada")
