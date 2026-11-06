"""Telefone brasileiro: normalização e plausibilidade. Não afirma titularidade."""

import re
from dataclasses import dataclass
from itertools import pairwise

VALID_DDDS: frozenset[int] = frozenset(
    {
        11, 12, 13, 14, 15, 16, 17, 18, 19,
        21, 22, 24, 27, 28,
        31, 32, 33, 34, 35, 37, 38,
        41, 42, 43, 44, 45, 46, 47, 48, 49,
        51, 53, 54, 55,
        61, 62, 63, 64, 65, 66, 67, 68, 69,
        71, 73, 74, 75, 77, 79,
        81, 82, 83, 84, 85, 86, 87, 88, 89,
        91, 92, 93, 94, 95, 96, 97, 98, 99,
    }
)  # fmt: skip


@dataclass(frozen=True)
class PhoneCheck:
    normalized: str | None  # E.164, ex.: +5511974123058
    error: str | None


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _national(digits: str) -> str:
    if len(digits) in (12, 13) and digits.startswith("55"):
        return digits[2:]
    if len(digits) in (11, 12) and digits.startswith("0"):
        return digits[1:]  # prefixo de discagem interurbana
    return digits


def _is_sequence(value: str) -> bool:
    if len(value) < 6:
        return False
    steps = {int(b) - int(a) for a, b in pairwise(value)}
    return steps in ({1}, {-1})


def _looks_fictitious(subscriber: str) -> bool:
    candidates = [subscriber, subscriber[1:]]
    return any(len(set(c)) == 1 or _is_sequence(c) for c in candidates)


def check_br_phone(raw: str, *, accept_landline: bool = True) -> PhoneCheck:
    digits = _digits(raw)
    if not digits:
        return PhoneCheck(None, "vazio")
    if len(set(digits)) == 1:
        return PhoneCheck(None, "ficticio")
    national = _national(digits)
    if len(national) not in (10, 11):
        return PhoneCheck(None, "formato")
    if int(national[:2]) not in VALID_DDDS:
        return PhoneCheck(None, "ddd")
    subscriber = national[2:]
    if len(subscriber) == 9:
        if subscriber[0] != "9":
            return PhoneCheck(None, "formato")
    else:
        if not accept_landline:
            return PhoneCheck(None, "fixo_nao_aceito")
        if subscriber[0] not in "2345":
            return PhoneCheck(None, "formato")
    if _looks_fictitious(subscriber):
        return PhoneCheck(None, "ficticio")
    return PhoneCheck(f"+55{national}", None)


def same_phone(a: str, b: str) -> bool:
    """Compara números BR tolerando o nono dígito ausente em alguns wa_id antigos."""
    na, nb = _national(_digits(a)), _national(_digits(b))
    if na == nb:
        return True
    short, long_ = sorted((na, nb), key=len)
    return (
        len(short) == 10 and len(long_) == 11 and long_[2] == "9" and long_[:2] + long_[3:] == short
    )


def last_digits(value: str, count: int = 4) -> str:
    return _digits(value)[-count:]
