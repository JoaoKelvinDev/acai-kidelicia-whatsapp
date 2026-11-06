"""Aplicação FastAPI. Executar com: uv run uvicorn app.main:create_app --factory --reload"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api import health, simulation, webhook
from app.core.config import Settings
from app.core.container import Container, build_container
from app.core.logging import configure_logging
from app.db.engine import ensure_migrated
from app.web import routes as web

_ADMIN_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; style-src 'self'; script-src 'none'; img-src 'self'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None, *, container: Container | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings.log_level)
    container = container or build_container(settings)
    dev = settings.dev_tools_enabled
    if dev and settings.webhook_enabled:
        logging.getLogger(__name__).warning(
            "Webhook configurado com APP_ENV=%s: as rotas /dev (sem login) estão ativas. "
            "Nunca exponha este servidor por túnel assim; use APP_ENV=staging.",
            settings.app_env,
        )

    @contextlib.asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if settings.require_migrated_db:
            await ensure_migrated(container.engine)
        worker_task = (
            asyncio.create_task(container.worker.run_forever())
            if settings.outbox_worker_enabled
            else None
        )
        try:
            yield
        finally:
            if worker_task:
                worker_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await worker_task
            await container.aclose()

    app = FastAPI(
        title="Açaí Ki-Delícia PL — atendimento WhatsApp",
        docs_url="/docs" if dev else None,
        redoc_url=None,
        openapi_url="/openapi.json" if dev else None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.container = container

    @app.middleware("http")
    async def admin_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        is_admin = request.url.path.startswith("/admin")
        hosts = settings.admin_hosts
        if is_admin and hosts and (request.url.hostname or "").lower() not in hosts:
            response: Response = PlainTextResponse("Not Found", status_code=404)
        else:
            response = await call_next(request)
        if is_admin:
            for name, value in _ADMIN_HEADERS.items():
                response.headers.setdefault(name, value)
        return response

    @app.exception_handler(web.LoginRequiredError)
    async def login_required(_request: Request, _exc: web.LoginRequiredError) -> Response:
        return RedirectResponse("/admin/login", status_code=303)

    app.include_router(health.router)
    app.include_router(webhook.router)
    app.include_router(web.router)
    app.mount(
        "/admin/static",
        StaticFiles(directory=str(Path(web.__file__).parent / "static")),
        name="admin-static",
    )
    if dev:
        app.include_router(simulation.router)
    return app
