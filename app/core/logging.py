"""Logs com dados pessoais minimizados: só IDs mascarados, nunca texto de mensagens."""

import logging
import re

_SECRET_QUERY_RE = re.compile(r"((?:hub[._]verify_token|access_token)=)[^&\s\"]+", re.IGNORECASE)


class RedactSecretsFilter(logging.Filter):
    """Mascara segredos que aparecem em URLs (ex.: hub.verify_token na verificação da Meta).

    O log de acesso do uvicorn grava a URL completa; sem este filtro, o token de verificação
    do webhook ficaria no log (ocorrido na sessão de teste de 06/11/2026).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(
                _SECRET_QUERY_RE.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args
            )
        if isinstance(record.msg, str):
            record.msg = _SECRET_QUERY_RE.sub(r"\1***", record.msg)
        return True


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    for name in ("uvicorn.access", "uvicorn.error", "httpx"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactSecretsFilter) for f in logger.filters):
            logger.addFilter(RedactSecretsFilter())


def mask_id(value: str | None) -> str:
    """Mascara identificadores (ex.: wa_id/telefone), mantendo só os 4 últimos caracteres."""
    if not value:
        return "-"
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"
