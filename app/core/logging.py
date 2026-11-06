"""Logs com dados pessoais minimizados: só IDs mascarados, nunca texto de mensagens."""

import logging


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def mask_id(value: str | None) -> str:
    """Mascara identificadores (ex.: wa_id/telefone), mantendo só os 4 últimos caracteres."""
    if not value:
        return "-"
    if len(value) <= 4:
        return "***"
    return f"***{value[-4:]}"
