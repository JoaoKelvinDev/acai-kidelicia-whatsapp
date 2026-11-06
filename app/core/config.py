"""Configuração lida do ambiente (.env). Sem valores reais no repositório."""

from typing import Literal

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

    @property
    def dev_tools_enabled(self) -> bool:
        return self.app_env in DEV_ENVS
