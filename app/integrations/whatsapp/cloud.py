"""Gateway real: envio de texto pela WhatsApp Cloud API.

Classificação de falhas (códigos conferidos na documentação de erros da Cloud API):
- retentável: limite de envio (130429, 131056, 4, 80007), erro temporário (1, 2, 131000),
  HTTP 429/5xx e falha de conexão antes de a requisição sair;
- resultado incerto: timeout ou queda depois de a requisição sair — pode ter sido entregue;
- definitiva: o resto (ex.: 131047 fora da janela de 24 h, 190 token inválido).
O token nunca é registrado em log.
"""

import logging

import httpx

from app.domain.phone import same_phone
from app.integrations.whatsapp.gateway import GatewayError, SendResult

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.facebook.com"
_RETRYABLE_CODES = frozenset({1, 2, 4, 80007, 130429, 131000, 131056})
_NAMED_CODES = {
    190: "token_invalido",
    100: "parametro_invalido",
    131026: "nao_entregavel",
    131030: "destinatario_nao_permitido_pela_meta",
    131031: "conta_restrita",
    131047: "fora_da_janela_24h",
    131048: "restrito_por_spam",
    130429: "limite_de_envio",
    131056: "limite_por_destinatario",
}


class CloudApiGateway:
    def __init__(
        self,
        *,
        access_token: str,
        phone_number_id: str,
        api_version: str,
        allowed_recipients: frozenset[str],
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
        base_url: str = GRAPH_BASE_URL,
    ) -> None:
        self._url = f"{base_url}/{api_version}/{phone_number_id}/messages"
        self._headers = {"Authorization": f"Bearer {access_token}"}
        self._allowed = allowed_recipients
        self._client = client or httpx.AsyncClient(timeout=timeout_seconds)

    async def aclose(self) -> None:
        await self._client.aclose()

    def _resolve_recipient(self, to: str) -> str | None:
        """Destino efetivo, ou None se bloqueado pela lista de teste.

        Com lista, envia no formato cadastrado nela (o mesmo da lista de destinatários de teste
        da Meta): o wa_id de números BR pode chegar sem o nono dígito, e a Meta recusa (131030)
        se o formato não for idêntico ao cadastrado.
        """
        if not self._allowed:
            return to
        return next((allowed for allowed in sorted(self._allowed) if same_phone(to, allowed)), None)

    async def send_text(self, to: str, text: str) -> SendResult:
        recipient = self._resolve_recipient(to)
        if recipient is None:
            # Trava de segurança do ambiente de teste: nunca chega à Meta.
            raise GatewayError("destinatario_fora_da_lista_autorizada")
        to = recipient
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        try:
            response = await self._client.post(self._url, json=payload, headers=self._headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
            raise GatewayError("falha_de_conexao", retryable=True) from exc
        except httpx.TimeoutException as exc:
            raise GatewayError("timeout_apos_envio", outcome_unknown=True) from exc
        except httpx.HTTPError as exc:
            raise GatewayError("erro_de_transporte", outcome_unknown=True) from exc

        if response.status_code == 200:
            try:
                return SendResult(provider_message_id=str(response.json()["messages"][0]["id"]))
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise GatewayError("resposta_sem_id", outcome_unknown=True) from exc
        raise self._classify(response)

    @staticmethod
    def _classify(response: httpx.Response) -> GatewayError:
        try:
            body = response.json()
        except ValueError:
            body = None
        error = body.get("error") if isinstance(body, dict) else None
        if not isinstance(error, dict):
            error = {}
        code = error.get("code") if isinstance(error.get("code"), int) else None
        name = _NAMED_CODES.get(
            code or -1, f"meta_{code}" if code else f"http_{response.status_code}"
        )
        retryable = (
            code in _RETRYABLE_CODES or response.status_code == 429 or response.status_code >= 500
        )
        if code == 190:
            logger.error("token da Cloud API inválido ou expirado: gere um novo e atualize o .env")
        return GatewayError(name, retryable=retryable)
