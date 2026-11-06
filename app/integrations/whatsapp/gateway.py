"""Contrato de envio. O adapter oficial (Cloud API) entra na Etapa 3."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str


class GatewayError(Exception):
    def __init__(
        self, code: str, *, retryable: bool = False, outcome_unknown: bool = False
    ) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable
        # Ex.: timeout após enviar a requisição — a mensagem pode ter sido entregue.
        self.outcome_unknown = outcome_unknown


class MessagingGateway(Protocol):
    async def send_text(self, to: str, text: str) -> SendResult: ...
