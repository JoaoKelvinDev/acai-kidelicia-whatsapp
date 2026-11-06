"""Textos do painel em português para estados, motivos e avisos."""

from app.domain.enums import (
    ConversationState,
    DeliveryStatus,
    Modality,
    OutboundStatus,
    PaymentMethod,
    StoreStatus,
)
from app.domain.models import Issue

STATE_LABELS = {
    ConversationState.AUTO_ACTIVE: "Automático",
    ConversationState.COLLECTING_DATA: "Coletando dados",
    ConversationState.HUMAN_PENDING: "Aguardando equipe",
    ConversationState.HUMAN_ACTIVE: "Em atendimento",
    ConversationState.CLOSED: "Encerrada",
}

STORE_STATUS_LABELS = {
    StoreStatus.OPEN: "Loja aberta",
    StoreStatus.CLOSED: "Loja fechada",
    StoreStatus.PAUSED: "Atendimento pausado",
    StoreStatus.UNKNOWN: "Status da loja não configurado",
}

REASON_LABELS = {
    "pedido_recebido": "Pedido recebido — montar e pesar",
    "pedido_requer_revisao": "Pedido precisa de conferência",
    "alteracao_requer_revisao": "Cliente pediu alteração no pedido",
    "limite_de_tentativas": "Cliente não completou os dados",
    "loja_fechado": "Pedido chegou com a loja fechada",
    "loja_pausado": "Pedido chegou com o atendimento pausado",
    "loja_desconhecido": "Pedido completo — status da loja não configurado",
    "intencao_human_request": "Pediu para falar com a equipe",
    "intencao_cancel_or_change": "Cancelamento ou alteração",
    "intencao_complaint": "Reclamação",
    "intencao_status_question": "Pergunta sobre o andamento",
    "intencao_question": "Dúvida",
    "intencao_other": "Mensagem não entendida",
    "intencao_buy": "Quer comprar (sem link do site configurado)",
    "midia_recebida": "Enviou áudio, imagem ou arquivo",
    "mensagem_apos_encerramento": "Nova mensagem após encerramento",
    "rascunho_nao_encontrado": "Pedido anterior não encontrado",
    "assumida": "Assumida pela equipe",
    "pausada": "Pausada pela equipe",
    "resposta_pelo_aplicativo": "Equipe respondeu pelo aplicativo",
}

ISSUE_LABELS = {
    ("taxa_entrega", "nao_verificada"): "Taxa de entrega veio do texto do cliente — conferir",
    ("taxa_entrega", "nao_informada"): "Taxa de entrega não informada",
    ("taxa_entrega", "nao_reconhecida"): "Taxa de entrega em formato não reconhecido",
    ("taxa_entrega", "negativa"): "Taxa de entrega negativa",
    ("taxa_entrega", "taxa_em_retirada"): "Taxa de entrega informada em pedido de retirada",
    ("telefone", "diferente_do_remetente"): "Telefone do pedido diferente deste WhatsApp",
    ("referencia", "sem_referencia_declarada"): "Cliente disse que não há ponto de referência",
    ("pedido", "campos_desconhecidos"): "Pedido tem campos que o sistema não conhece",
    ("pedido", "linhas_nao_reconhecidas"): "Pedido tem linhas que o sistema não entendeu",
    ("pedido", "campos_repetidos_divergentes"): "Campo repetido com valores diferentes",
    ("pedido", "possivel_duplicidade"): "Possível pedido duplicado",
    ("itens", "ausente"): "Nenhum item identificado",
}

ISSUE_CODE_LABELS = {
    "ausente": "não informado",
    "placeholder": "parece um teste",
    "ficticio": "número fictício",
    "formato": "formato inválido",
    "ddd": "DDD inválido",
    "nao_reconhecida": "não reconhecida",
    "nao_reconhecido": "não reconhecido",
    "nao_inteira_positiva": "quantidade inválida",
    "fora_do_catalogo": "fora do catálogo",
    "campos_desconhecidos": "campos desconhecidos",
}

MODALITY_LABELS = {Modality.DELIVERY: "Delivery", Modality.PICKUP: "Retirada"}
PAYMENT_LABELS = {
    PaymentMethod.PIX: "Pix",
    PaymentMethod.CARD: "Cartão",
    PaymentMethod.CASH: "Dinheiro",
}
OUTBOUND_STATUS_LABELS = {
    OutboundStatus.PENDING: "na fila",
    OutboundStatus.SENDING: "enviando",
    OutboundStatus.SENT: "enviada",
    OutboundStatus.FAILED: "falhou",
    OutboundStatus.UNKNOWN: "resultado incerto",
    OutboundStatus.CANCELLED: "cancelada",
    OutboundStatus.BLOCKED: "bloqueada",
}
DELIVERY_LABELS = {
    DeliveryStatus.SENT: "enviada",
    DeliveryStatus.DELIVERED: "entregue",
    DeliveryStatus.READ: "lida",
    DeliveryStatus.FAILED: "não entregue",
}
WEEKDAYS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def reason_label(reason: str | None) -> str:
    if not reason:
        return ""
    return REASON_LABELS.get(reason, reason.replace("_", " "))


def issue_label(issue: Issue) -> str:
    known = ISSUE_LABELS.get((issue.field, issue.code))
    if known:
        return known
    field = issue.field.replace("_", " ").replace("itens[", "item ").replace("].", ": ")
    return f"{field.capitalize()} — {ISSUE_CODE_LABELS.get(issue.code, issue.code)}"


def format_phone(wa_id: str) -> str:
    digits = "".join(ch for ch in wa_id if ch.isdigit())
    if digits.startswith("55") and len(digits) == 13:
        return f"({digits[2:4]}) {digits[4:9]}-{digits[9:]}"
    if digits.startswith("55") and len(digits) == 12:
        return f"({digits[2:4]}) {digits[4:8]}-{digits[8:]}"
    return wa_id
