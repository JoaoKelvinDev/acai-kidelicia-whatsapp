"""Normalização tolerante do texto vindo do WhatsApp.

Remove decoração (emojis, asteriscos de negrito, bullets, separadores, "�" soltos) sem
alterar o conteúdo dos valores. Um "�" no meio de uma palavra provavelmente substituiu uma
letra acentuada; ele é preservado no valor para não destruir nomes.
"""

import re
import unicodedata

REPLACEMENT_CHAR = "�"
_INVISIBLE = frozenset("️︎‍​‌⁠﻿⃣")
_LEADING_BULLET_RE = re.compile(r"^(?:[•·‣◦●○■□▪▫➤➢►▶>]|[-–—](?=\s))\s*")
_SEPARATOR_RE = re.compile(r"^[-_=—–─━.·•\s]{3,}$")
_SPACES_RE = re.compile(r"[ \t   ]+")


def _is_decoration(ch: str) -> bool:
    if ch in _INVISIBLE:
        return True
    if 0x1F3FB <= ord(ch) <= 0x1F3FF:  # modificadores de tom de pele
        return True
    return unicodedata.category(ch) in {"So", "Cs", "Co"}


def strip_decorations(line: str) -> str:
    out: list[str] = []
    for i, ch in enumerate(line):
        if ch == REPLACEMENT_CHAR:
            prev_ch = line[i - 1] if i > 0 else ""
            next_ch = line[i + 1] if i + 1 < len(line) else ""
            if prev_ch.isalpha() and next_ch.isalpha():
                out.append(ch)
            continue
        if ch == "*" or _is_decoration(ch):
            continue
        out.append(ch)
    return "".join(out)


def clean_lines(text: str) -> list[str]:
    """Quebra em linhas limpas e não vazias; separadores visuais são descartados."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for raw in text.split("\n"):
        line = _SPACES_RE.sub(" ", strip_decorations(raw)).strip()
        if not line or _SEPARATOR_RE.match(line):
            continue
        line = _LEADING_BULLET_RE.sub("", line).strip()
        if line:
            lines.append(line)
    return lines


def fold(text: str) -> str:
    """Forma canônica para comparação: sem acentos, minúscula, só letras/dígitos e espaços."""
    text = text.replace(REPLACEMENT_CHAR, "")
    decomposed = unicodedata.normalize("NFKD", text)
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", no_marks.lower()).strip()
