"""Configuração da loja. Nada aqui é presumido: o que não foi cadastrado fica desconhecido."""

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import MediaPolicy, StoreStatus

DEFAULT_FIELD_QUESTIONS: dict[str, str] = {
    "nome": "Qual é o seu nome?",
    "telefone": "Qual é o telefone para contato, com DDD?",
    "modalidade": "O pedido é para retirada ou delivery?",
    "endereco": ("Qual é o endereço completo para entrega (rua, número ou “sem número” e bairro)?"),
    "referencia": "Qual é um ponto de referência perto do endereço?",
    "pagamento": "Qual será a forma de pagamento: Pix, cartão ou dinheiro?",
    "troco": "Vai precisar de troco? Se sim, para qual valor?",
    "troco_valor": "Troco para qual valor?",
}


class ReplyTexts(BaseModel):
    """Templates internos. Placeholders aceitos: {store_name}, {website_url}, {last4}."""

    confirmation: str = (
        "Recebemos seu pedido! A equipe dará sequência ao atendimento. "
        "O valor final será informado por aqui após a montagem e a pesagem. "
        "Se houver alguma indisponibilidade, entraremos em contato."
    )
    phone_divergence_note: str = (
        "Observação: o telefone informado no pedido (final {last4}) é diferente deste "
        "WhatsApp. A equipe vai confirmar o contato com você por aqui."
    )
    ask_data_intro: str = "Para darmos sequência ao seu pedido, precisamos de alguns dados:"
    ask_data_retry_intro: str = "Ainda precisamos destes dados para continuar:"
    ask_data_format_hint: str = (
        "Se puder, responda no formato “Campo: valor” (por exemplo, “Nome: Maria”)."
    )
    ask_data_outro: str = "Pode responder aqui mesmo."
    field_questions: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_FIELD_QUESTIONS))
    invalid_suffix: str = " (o dado informado não parece válido)"
    handoff: str = (
        "Vou encaminhar sua mensagem para a nossa equipe, que vai continuar o atendimento por aqui."
    )
    review_handoff: str = (
        "Recebemos sua mensagem. Alguns detalhes do pedido precisam ser conferidos pela "
        "nossa equipe, que vai continuar o atendimento por aqui."
    )
    attempts_exceeded: str = (
        "Não consegui completar os dados do pedido por aqui. Encaminhei para a nossa equipe, "
        "que vai continuar o atendimento."
    )
    store_closed: str = (
        "No momento estamos fechados, então seu pedido ainda não foi encaminhado para "
        "montagem. Sua mensagem ficou registrada e a equipe vai responder por aqui."
    )
    store_paused: str = (
        "No momento o atendimento está pausado, então seu pedido ainda não foi encaminhado "
        "para montagem. Sua mensagem ficou registrada e a equipe vai responder por aqui."
    )
    store_unknown: str = (
        "Recebemos sua mensagem. A equipe vai conferir o pedido e continuar o atendimento por aqui."
    )
    greeting: str = (
        "Olá! Sou o assistente virtual do {store_name}. Para fazer seu pedido, acesse "
        "{website_url} — ao finalizar, a mensagem do pedido vem para este WhatsApp e é só "
        "enviá-la. Se precisar de outra coisa, é só escrever."
    )
    greeting_no_link: str = (
        "Olá! Sou o assistente virtual do {store_name}. Se precisar de algo, é só escrever "
        "que eu encaminho para a equipe."
    )
    site_redirect: str = (
        "Os pedidos são feitos pelo nosso site: {website_url}. Lá você monta seu açaí e, ao "
        "finalizar, a mensagem do pedido vem para este WhatsApp — é só enviá-la."
    )
    media_handoff: str = (
        "Ainda não consigo abrir áudios, imagens, localizações ou arquivos por aqui. "
        "Encaminhei para a nossa equipe; se preferir, escreva sua mensagem em texto."
    )
    media_ask_text: str = (
        "Ainda não consigo abrir áudios, imagens, localizações ou arquivos por aqui. "
        "Pode escrever sua mensagem em texto?"
    )


class OpeningWindow(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = segunda-feira")
    start: time
    end: time

    @model_validator(mode="after")
    def _check_order(self) -> "OpeningWindow":
        if self.start >= self.end:
            raise ValueError("início deve ser anterior ao fim (janelas no mesmo dia)")
        return self


class StoreSettings(BaseModel):
    store_name: str
    website_url: str | None = None
    timezone: str = "America/Sao_Paulo"

    # Status manual tem prioridade; sem ele, usa horários; sem horários, é desconhecido.
    status_override: StoreStatus | None = None
    opening_hours: list[OpeningWindow] | None = None

    # Pausa global da automação (falha/manutenção). Mensagens continuam registradas.
    automation_paused: bool = False

    max_correction_attempts: int = Field(default=2, ge=1)
    require_reference_for_delivery: bool = True
    accept_landline: bool = True
    required_item_fields: list[Literal["tamanho", "base"]] = Field(
        default_factory=lambda: ["tamanho"]
    )
    # Catálogo de tamanhos, quando cadastrado. None = não validar contra catálogo.
    allowed_sizes: list[str] | None = None
    media_policy: MediaPolicy = MediaPolicy.HANDOFF
    duplicate_window_minutes: int = Field(default=120, ge=0)
    service_window_hours: int = Field(default=24, ge=1)

    texts: ReplyTexts = Field(default_factory=ReplyTexts)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"fuso horário desconhecido: {value}") from exc
        return value

    def effective_status(self, now: datetime) -> StoreStatus:
        if self.status_override is not None:
            return self.status_override
        if self.opening_hours is None:
            return StoreStatus.UNKNOWN
        local = now.astimezone(ZoneInfo(self.timezone))
        current = local.time()
        for window in self.opening_hours:
            if window.weekday == local.weekday() and window.start <= current < window.end:
                return StoreStatus.OPEN
        return StoreStatus.CLOSED
