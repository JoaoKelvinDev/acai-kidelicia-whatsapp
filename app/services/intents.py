"""Classificador determinístico de intenção. A IA (Etapa 4) poderá refinar, nunca substituir
as regras críticas: pedido estruturado, pedido de humano, cancelamento/alteração e reclamação."""

import re

from app.domain.enums import Intent, MessageType
from app.parsers.normalize import fold
from app.parsers.site_order import is_site_order

_HUMAN_RE = re.compile(
    r"\b(atendente|humano|falar com|quero falar|preciso falar|pessoa real|pessoa de verdade"
    r"|uma pessoa|alguem da loja|responsavel|gerente)\b"
)
_CANCEL_OR_CHANGE_RE = re.compile(
    r"\b(cancel\w*|desist\w*|alter\w*|mudar|muda|mude|trocar|troca|troque|tirar|tira"
    r"|acrescent\w*)\b"
)
_COMPLAINT_RE = re.compile(
    r"\b(reclam\w*|pessim\w*|horrivel|absurdo|errad\w*|nao chegou|nunca chega|derretid\w*"
    r"|estragad\w*|demorando|atrasad\w*|atraso)\b"
)
_STATUS_RE = re.compile(
    r"\b(cade|kd|ja saiu|saiu para entrega|saiu pra entrega|vai demorar|quanto tempo"
    r"|previsao|andamento|ta pronto|esta pronto|ficou pronto|ja ta vindo|ja esta vindo"
    r"|chega quando|vai chegar|status)\b"
)
_BUY_RE = re.compile(
    r"\b(quero|queria|gostaria|pedir|encomend\w*|comprar|cardapio|menu|acai|acais)\b"
)
_GREETING_RE = re.compile(
    r"\b(oi+e?|ola|opa|eai|e ai|bom dia|boa tarde|boa noite|hello|hi|salve|alo"
    r"|tudo bem|tudo bom|td bem|td bom|como vai|blz|beleza)\b"
)


def classify(message_type: MessageType, text: str | None) -> Intent:
    if message_type is not MessageType.TEXT:
        return Intent.MEDIA
    if not text or not text.strip():
        return Intent.OTHER
    if is_site_order(text):
        return Intent.SITE_ORDER
    f = fold(text)
    if _HUMAN_RE.search(f):
        return Intent.HUMAN_REQUEST
    if _CANCEL_OR_CHANGE_RE.search(f):
        return Intent.CANCEL_OR_CHANGE
    if _COMPLAINT_RE.search(f):
        return Intent.COMPLAINT
    if _STATUS_RE.search(f):
        return Intent.STATUS_QUESTION
    if _BUY_RE.search(f):
        return Intent.BUY
    if _GREETING_RE.search(f) and not _GREETING_RE.sub(" ", f).strip():
        return Intent.GREETING
    if "?" in text:
        return Intent.QUESTION
    return Intent.OTHER
