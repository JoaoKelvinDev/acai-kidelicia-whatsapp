"""Configuração lida do ambiente (.env). Sem valores reais no repositório."""

from typing import Literal

from pydantic import Field
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

    @property
    def dev_tools_enabled(self) -> bool:
        return self.app_env in DEV_ENVS
