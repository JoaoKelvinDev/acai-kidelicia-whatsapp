"""Aplicação FastAPI. Executar com: uv run uvicorn app.main:create_app --factory --reload"""

from fastapi import FastAPI

from app.api import health, simulation
from app.core.config import Settings
from app.core.container import Container, build_container
from app.core.logging import configure_logging


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    container = container or build_container(settings)
    dev = settings.dev_tools_enabled

    app = FastAPI(
        title="Açaí Ki-Delícia PL — atendimento WhatsApp",
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
    )
    app.state.settings = settings
    app.state.container = container
    app.include_router(health.router)
    if dev:
        app.include_router(simulation.router)
    return app
