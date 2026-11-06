"""Interpretação determinística de valores de campos (aliases controlados)."""

import re
from decimal import Decimal

from app.domain.enums import Modality, PaymentMethod
from app.parsers.money import find_amount
from app.parsers.normalize import fold

_DELIVERY_RE = re.compile(r"\b(deliv\w*|entreg\w*|tele ?entrega|motoboy)\b")
_PICKUP_RE = re.compile(r"\b(retir\w*|busc\w*|balcao|no local|na loja)\b")
_PIX_RE = re.compile(r"\bpix\b")
_CARD_RE = re.compile(r"\b(cartao|credito|debito|maquin\w*)\b")
_CASH_RE = re.compile(r"\b(dinheiro|especie)\b")
_QUANTITY_RE = re.compile(r"x?\s*(\d{1,3})\s*(?:x|un|und|unid\w*)?")
_EMPTY_LIST = frozenset({"", "nenhum", "nenhuma", "sem", "nao", "nada", "n a", "na"})
_CHANGE_NO_RE = re.compile(r"\b(nao|sem|dispenso|nenhum)\b")
_CHANGE_YES_RE = re.compile(r"\b(sim|preciso|precisa|quero|vou precisar)\b")


def parse_modality(raw: str | None) -> Modality | None:
    f = fold(raw or "")
    delivery, pickup = bool(_DELIVERY_RE.search(f)), bool(_PICKUP_RE.search(f))
    if delivery == pickup:  # nenhum ou ambos: ambíguo
        return None
    return Modality.DELIVERY if delivery else Modality.PICKUP


def parse_payment(raw: str | None) -> PaymentMethod | None:
    f = fold(raw or "").split("troco")[0]
    found = [
        method
        for method, pattern in (
            (PaymentMethod.PIX, _PIX_RE),
            (PaymentMethod.CARD, _CARD_RE),
            (PaymentMethod.CASH, _CASH_RE),
        )
        if pattern.search(f)
    ]
    return found[0] if len(found) == 1 else None


def parse_quantity(raw: str | None) -> int | None:
    match = _QUANTITY_RE.fullmatch(fold(raw or ""))
    return int(match.group(1)) if match else None


def parse_list(raw: str | None) -> list[str]:
    if raw is None or fold(raw) in _EMPTY_LIST:
        return []
    return [part.strip() for part in re.split(r"[,;]", raw) if part.strip()]


def parse_change(raw: str | None) -> tuple[bool | None, Decimal | None]:
    """Necessidade de troco e valor. (None, None) quando não dá para afirmar nada."""
    text = raw or ""
    f = fold(text)
    amount = find_amount(text)
    negative = bool(_CHANGE_NO_RE.search(f))
    if negative:
        return (False, None) if amount is None else (None, None)
    if amount is not None:
        return True, amount
    if _CHANGE_YES_RE.search(f):
        return True, None
    return None, None
