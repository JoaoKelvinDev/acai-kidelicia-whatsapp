import logging

from app.core.logging import RedactSecretsFilter, configure_logging


def _record(msg: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, args, None)


def test_verify_token_is_masked_in_access_log():
    # Formato real do log de acesso do uvicorn na verificação da Meta.
    path = (
        "/webhook/whatsapp?hub.mode=subscribe&hub.challenge=123&hub.verify_token=SEGREDO1"
        "&hub_mode=subscribe&hub_challenge=123&hub_verify_token=SEGREDO2"
    )
    record = _record('%s - "%s %s HTTP/%s" %d', "2a03:2880::0", "GET", path, "1.1", 200)
    RedactSecretsFilter().filter(record)
    text = record.getMessage()
    assert "SEGREDO1" not in text and "SEGREDO2" not in text
    assert "hub.verify_token=***" in text and "hub.challenge=123" in text


def test_access_token_in_message_is_masked():
    record = _record("GET https://graph.facebook.com/x?access_token=123|abc&fields=y")
    RedactSecretsFilter().filter(record)
    assert "123|abc" not in record.getMessage()


def test_filter_installed_once_on_uvicorn_access():
    configure_logging()
    configure_logging()
    filters = [
        f for f in logging.getLogger("uvicorn.access").filters if isinstance(f, RedactSecretsFilter)
    ]
    assert len(filters) == 1
