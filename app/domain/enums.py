from enum import StrEnum


class ConversationState(StrEnum):
    AUTO_ACTIVE = "AUTO_ACTIVE"
    COLLECTING_DATA = "COLLECTING_DATA"
    HUMAN_PENDING = "HUMAN_PENDING"
    HUMAN_ACTIVE = "HUMAN_ACTIVE"
    CLOSED = "CLOSED"


HUMAN_STATES: frozenset[ConversationState] = frozenset(
    {ConversationState.HUMAN_PENDING, ConversationState.HUMAN_ACTIVE}
)
AUTOMATED_STATES: frozenset[ConversationState] = frozenset(
    {ConversationState.AUTO_ACTIVE, ConversationState.COLLECTING_DATA}
)


class DraftState(StrEnum):
    """Estado do rascunho. Não indica preparo nem pagamento."""

    INCOMPLETE = "INCOMPLETE"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    RECEIVED = "RECEIVED"


class Modality(StrEnum):
    PICKUP = "retirada"
    DELIVERY = "delivery"


class PaymentMethod(StrEnum):
    PIX = "pix"
    CARD = "cartao"
    CASH = "dinheiro"


class StoreStatus(StrEnum):
    OPEN = "aberto"
    CLOSED = "fechado"
    PAUSED = "pausado"
    UNKNOWN = "desconhecido"


class IssueKind(StrEnum):
    MISSING = "ausente"
    INVALID = "invalido"
    UNVERIFIABLE = "nao_verificavel"


class MessageType(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    LOCATION = "location"
    STICKER = "sticker"
    CONTACTS = "contacts"
    OTHER = "other"


class Intent(StrEnum):
    SITE_ORDER = "site_order"
    GREETING = "greeting"
    BUY = "buy"
    HUMAN_REQUEST = "human_request"
    CANCEL_OR_CHANGE = "cancel_or_change"
    COMPLAINT = "complaint"
    STATUS_QUESTION = "status_question"
    QUESTION = "question"
    MEDIA = "media"
    OTHER = "other"


class ReplyKind(StrEnum):
    CONFIRMATION = "confirmation"
    ASK_DATA = "ask_data"
    HANDOFF = "handoff"
    REVIEW_HANDOFF = "review_handoff"
    STORE_CLOSED = "store_closed"
    STORE_PAUSED = "store_paused"
    STORE_UNKNOWN = "store_unknown"
    GREETING = "greeting"
    SITE_REDIRECT = "site_redirect"
    MEDIA = "media"


class OutboundStatus(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    # Timeout/erro sem confirmação: pode ter sido entregue. Não reenviar cegamente.
    UNKNOWN = "unknown"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class MediaPolicy(StrEnum):
    HANDOFF = "handoff"
    ASK_TEXT = "ask_text"
