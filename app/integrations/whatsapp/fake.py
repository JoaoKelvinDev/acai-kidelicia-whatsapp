"""Gateway falso para desenvolvimento e testes: registra envios, não usa rede."""

from dataclasses import dataclass

from app.domain.models import new_id
from app.integrations.whatsapp.gateway import GatewayError, SendResult


@dataclass(frozen=True)
class SentMessage:
    to: str
    text: str
    provider_message_id: str


class FakeGateway:
    def __init__(self) -> None:
        self.sent: list[SentMessage] = []
        self._fail_next: list[GatewayError] = []

    def fail_next(self, error: GatewayError) -> None:
        self._fail_next.append(error)

    async def send_text(self, to: str, text: str) -> SendResult:
        if self._fail_next:
            raise self._fail_next.pop(0)
        provider_id = f"fake.{new_id()}"
        self.sent.append(SentMessage(to=to, text=text, provider_message_id=provider_id))
        return SendResult(provider_message_id=provider_id)
