"""Valores monetários em formato brasileiro ou com ponto decimal."""

import re
import unicodedata
from decimal import Decimal

_FREE_WORDS = frozenset({"gratis", "gratuita", "gratuito", "isento", "isenta", "free"})
_AMOUNT_RE = re.compile(r"\d[\d.,]*\d|\d")
_CENTS = Decimal("0.01")


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _to_decimal(s: str) -> Decimal | None:
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thousands = "." if dec == "," else ","
        int_part, _, frac = s.rpartition(dec)
        thousands_re = rf"\d{{1,3}}(?:{re.escape(thousands)}\d{{3}})*"
        if not re.fullmatch(thousands_re, int_part) or not re.fullmatch(r"\d{1,2}", frac):
            return None
        return Decimal(int_part.replace(thousands, "") + "." + frac)
    sep = "," if "," in s else "." if "." in s else None
    if sep is None:
        return Decimal(s)
    parts = s.split(sep)
    if len(parts) == 2 and parts[0] and 1 <= len(parts[1]) <= 2:
        return Decimal(f"{parts[0]}.{parts[1]}")
    if 1 <= len(parts[0]) <= 3 and all(len(p) == 3 for p in parts[1:]):
        return Decimal("".join(parts))
    return None


def parse_brl(raw: str | None) -> Decimal | None:
    """'R$ 3.00', '3,00', '1.234,56', 'Grátis' → Decimal. Retorna None se não reconhecer."""
    if raw is None:
        return None
    s = _strip_accents(raw.strip().lower())
    if s in _FREE_WORDS:
        return Decimal("0.00")
    s = re.sub(r"r\$|reais|real|\s", "", s)
    negative = s.startswith("-")
    s = s.lstrip("-")
    if not re.fullmatch(r"\d(?:[\d.,]*\d)?", s):
        return None
    value = _to_decimal(s)
    if value is None:
        return None
    value = value.quantize(_CENTS)
    return -value if negative else value


def find_amount(text: str) -> Decimal | None:
    """Extrai um único valor de um texto livre; se houver mais de um, é ambíguo (None)."""
    found = _AMOUNT_RE.findall(text)
    if len(found) != 1:
        return None
    return parse_brl(found[0])
