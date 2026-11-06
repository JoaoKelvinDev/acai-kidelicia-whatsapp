"""Configuração lida do ambiente (.env). Sem valores reais no repositório."""

from typing import Literal, Self

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["local", "test", "staging", "production"]
DEV_ENVS: frozenset[str] = frozenset({"local", "test"})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Padrão seguro: sem APP_ENV explícito, as rotas de simulação ficam desligadas.
    app_env: AppEnv = "production"
    log_level: str = "INFO"

    store_name: str = "Açaí Ki-Delícia PL"
    store_timezone: str = "America/Sao_Paulo"
    store_website_url: str | None = None

    # Banco: SQLite local; PostgreSQL proposto para produção (mesmo esquema/migrações).
    database_url: str = "sqlite+aiosqlite:///./data/acai.db"
    # Recusa iniciar se o banco não estiver na última migração.
    require_migrated_db: bool = True

    # Painel da equipe
    session_ttl_hours: int = Field(default=12, ge=1)
    session_cookie_secure: bool = True
    login_max_failures: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=5, ge=1)
    # Se preenchido (ex.: "localhost,127.0.0.1"), o painel só responde nesses hosts.
    # Útil com túnel: a internet alcança o webhook, mas não o painel.
    admin_allowed_hosts: str = ""

    # Fila de envio (outbox)
    outbox_worker_enabled: bool = True
    outbox_poll_seconds: float = Field(default=1.0, gt=0)
    outbox_max_attempts: int = Field(default=5, ge=1)
    outbox_backoff_base_seconds: float = Field(default=5.0, gt=0)
    outbox_backoff_max_seconds: float = Field(default=300.0, gt=0)
    outbox_sending_lease_seconds: int = Field(default=120, ge=10)

    # Retenção (decisão do proprietário: 14 dias para dados de clientes)
    retention_days: int = Field(default=14, ge=1)
    audit_retention_days: int = Field(default=365, ge=1)

    # WhatsApp Cloud API (Etapa 3). Segredos só no .env.
    whatsapp_gateway: Literal["fake", "cloud"] = "fake"
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_verify_token: SecretStr | None = None
    meta_graph_api_version: str = Field(default="v25.0", pattern=r"^v\d+\.\d+$")
    # Números (separados por vírgula) que podem receber mensagens fora de produção.
    whatsapp_allowed_recipients: str = ""
    whatsapp_api_timeout_seconds: float = Field(default=15.0, gt=0)
    webhook_max_body_bytes: int = Field(default=1_000_000, ge=1024)
    # Mensagem enviada pelo app do celular (coexistência) pausa a automação da conversa.
    pause_on_owner_echo: bool = True

    @field_validator(
        "whatsapp_access_token",
        "whatsapp_phone_number_id",
        "whatsapp_app_secret",
        "whatsapp_verify_token",
        "store_website_url",
        mode="before",
    )
    @classmethod
    def _blank_is_missing(cls, value: object) -> object:
        # "WHATSAPP_APP_SECRET=" vazio no .env NÃO pode virar um segredo vazio (inseguro).
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def dev_tools_enabled(self) -> bool:
        return self.app_env in DEV_ENVS

    @property
    def admin_hosts(self) -> frozenset[str]:
        return frozenset(
            h.strip().lower() for h in self.admin_allowed_hosts.split(",") if h.strip()
        )

    @property
    def webhook_enabled(self) -> bool:
        return self.whatsapp_app_secret is not None and self.whatsapp_verify_token is not None

    @property
    def allowed_recipients(self) -> frozenset[str]:
        return frozenset(
            "".join(ch for ch in part if ch.isdigit())
            for part in self.whatsapp_allowed_recipients.split(",")
            if part.strip()
        )

    @model_validator(mode="after")
    def _check_whatsapp(self) -> Self:
        if self.whatsapp_gateway != "cloud":
            return self
        missing = [
            name
            for name in (
                "whatsapp_access_token",
                "whatsapp_phone_number_id",
                "whatsapp_app_secret",
                "whatsapp_verify_token",
            )
            if not getattr(self, name)
        ]
        if missing:
            raise ValueError(
                f"WHATSAPP_GATEWAY=cloud exige: {', '.join(m.upper() for m in missing)}"
            )
        if self.app_env == "local":
            # Rotas /dev não têm login: com envio real e túnel, seriam um risco.
            raise ValueError("WHATSAPP_GATEWAY=cloud não pode rodar com APP_ENV=local; use staging")
        if self.app_env != "production" and not self.allowed_recipients:
            raise ValueError(
                "Fora de produção, WHATSAPP_ALLOWED_RECIPIENTS é obrigatório com o gateway cloud"
            )
        return self
