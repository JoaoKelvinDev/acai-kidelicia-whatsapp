"""Painel mínimo da equipe (HTML renderizado no servidor, sem JavaScript).

Segurança:
- Sessão em cookie HttpOnly/SameSite=Lax; token guardado só como hash no banco.
- Todo POST autenticado exige token CSRF da sessão.
- Atendente: ações nas conversas. Admin: também configuração da loja e pausa global.
- Conteúdo do cliente é sempre escapado pelo Jinja2 (autoescape).
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.core.container import Container
from app.domain.enums import ConversationState, ReplyKind, StoreStatus
from app.domain.models import AuditEvent, Conversation, OrderDraft
from app.domain.store import OpeningWindow
from app.domain.validation import validate_draft
from app.services.auth import AuthContext, LoginError
from app.services.handoff import ConversationNotFoundError
from app.web import labels

SESSION_COOKIE = "acai_session"
TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter(prefix="/admin", include_in_schema=False)

VIEWS: dict[str, tuple[str, set[ConversationState]]] = {
    "pendentes": ("Aguardando equipe", {ConversationState.HUMAN_PENDING}),
    "atendimento": ("Em atendimento", {ConversationState.HUMAN_ACTIVE}),
    "automatico": (
        "Automático",
        {ConversationState.AUTO_ACTIVE, ConversationState.COLLECTING_DATA},
    ),
    "encerradas": ("Encerradas", {ConversationState.CLOSED}),
}
ACTIONS: dict[str, str] = {
    "take_over": "Assumir",
    "pause": "Pausar automação",
    "resume": "Devolver ao automático",
    "close": "Encerrar",
}


class LoginRequiredError(Exception):
    pass


def _container(request: Request) -> Container:
    return request.app.state.container


async def current_auth(request: Request) -> AuthContext:
    auth = await _container(request).auth.resolve(request.cookies.get(SESSION_COOKIE))
    if auth is None:
        raise LoginRequiredError
    return auth


AuthDep = Annotated[AuthContext, Depends(current_auth)]


async def admin_auth(auth: AuthDep) -> AuthContext:
    if not auth.operator.is_admin:
        raise HTTPException(status_code=403, detail="Somente administradores")
    return auth


AdminDep = Annotated[AuthContext, Depends(admin_auth)]


def _check_csrf(auth: AuthContext, token: str) -> None:
    if not secrets.compare_digest(token.encode(), auth.session.csrf_token.encode()):
        raise HTTPException(status_code=403, detail="Token de segurança inválido")


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


async def _render(
    request: Request, name: str, auth: AuthContext | None, status_code: int = 200, **ctx: Any
) -> HTMLResponse:
    container = _container(request)
    async with container.db.transaction() as tx:
        store = await tx.get_store_settings()
    tz = ZoneInfo(store.timezone)
    now = container.clock.now()

    def local(dt: datetime | None, fmt: str = "%d/%m %H:%M") -> str:
        return dt.astimezone(tz).strftime(fmt) if dt else "—"

    def ago(dt: datetime | None) -> str:
        if dt is None:
            return ""
        minutes = int((now - dt).total_seconds() // 60)
        if minutes < 1:
            return "agora"
        if minutes < 60:
            return f"há {minutes} min"
        hours = minutes // 60
        return f"há {hours} h" if hours < 48 else f"há {hours // 24} dias"

    context = {
        "auth": auth,
        "store": store,
        "store_status": store.effective_status(now),
        "labels": labels,
        "local": local,
        "ago": ago,
        **ctx,
    }
    return TEMPLATES.TemplateResponse(request, name, context, status_code=status_code)


# ── login ───────────────────────────────────────────────────────────────────


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> Response:
    if await _container(request).auth.resolve(request.cookies.get(SESSION_COOKIE)):
        return _redirect("/admin")
    return await _render(request, "login.html", None)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: Annotated[str, Form(max_length=80)],
    password: Annotated[str, Form(max_length=200)],
) -> Response:
    container = _container(request)
    try:
        token, _ = await container.auth.login(username, password)
    except LoginError:
        return await _render(
            request,
            "login.html",
            None,
            status_code=401,
            error="Usuário ou senha inválidos, ou acesso bloqueado temporariamente.",
        )
    response = _redirect("/admin")
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=container.settings.session_ttl_hours * 3600,
        httponly=True,
        secure=container.settings.session_cookie_secure,
        samesite="lax",
        path="/admin",
    )
    return response


@router.post("/logout")
async def logout(request: Request, auth: AuthDep, csrf_token: Annotated[str, Form()]) -> Response:
    _check_csrf(auth, csrf_token)
    await _container(request).auth.logout(request.cookies.get(SESSION_COOKIE))
    response = _redirect("/admin/login")
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return response


# ── conversas ───────────────────────────────────────────────────────────────


@dataclass
class _Row:
    conv: Conversation
    name: str | None


@router.get("", response_class=HTMLResponse)
async def conversations(request: Request, auth: AuthDep, view: str = "pendentes") -> Response:
    if view not in VIEWS:
        view = "pendentes"
    _, states = VIEWS[view]
    async with _container(request).db.transaction() as tx:
        counts = {
            key: len(await tx.list_conversations(view_states))
            for key, (_, view_states) in VIEWS.items()
        }
        convs = await tx.list_conversations(states, limit=200)
        rows = []
        for conv in convs:
            drafts = await tx.list_drafts(conv.id)
            rows.append(_Row(conv=conv, name=drafts[-1].name if drafts else None))
    if view == "pendentes":
        rows.sort(key=lambda r: r.conv.last_customer_message_at or r.conv.updated_at)
    return await _render(
        request, "conversations.html", auth, rows=rows, view=view, views=VIEWS, counts=counts
    )


@router.get("/conversas/{conversation_id}", response_class=HTMLResponse)
async def conversation_detail(request: Request, auth: AuthDep, conversation_id: str) -> Response:
    async with _container(request).db.transaction() as tx:
        conv = await tx.get_conversation(conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="Conversa não encontrada")
        messages = await tx.list_inbound(conversation_id)
        outbound = await tx.list_outbound(conversation_id)
        drafts = await tx.list_drafts(conversation_id)
        store = await tx.get_store_settings()

    draft: OrderDraft | None = drafts[-1] if drafts else None
    issues = validate_draft(draft, store, conv.id).issues if draft else []
    timeline: list[dict[str, Any]] = [
        {
            "at": m.timestamp,
            "inbound": True,
            "text": m.text,
            "type": m.type,
            "redacted": m.redacted_at,
        }
        for m in messages
    ] + [
        {
            "at": o.created_at,
            "inbound": False,
            "text": o.text,
            "status": o.status,
            "kind": o.kind,
            "redacted": o.redacted_at,
        }
        for o in outbound
    ]
    timeline.sort(key=lambda item: item["at"])
    return await _render(
        request,
        "conversation.html",
        auth,
        conv=conv,
        draft=draft,
        issues=issues,
        timeline=timeline,
        actions=_available_actions(conv.state),
        ReplyKind=ReplyKind,
    )


def _available_actions(state: ConversationState) -> list[tuple[str, str]]:
    allowed = {
        ConversationState.HUMAN_PENDING: ["take_over", "resume", "close"],
        ConversationState.HUMAN_ACTIVE: ["resume", "close"],
        ConversationState.AUTO_ACTIVE: ["take_over", "pause", "close"],
        ConversationState.COLLECTING_DATA: ["take_over", "pause", "close"],
        ConversationState.CLOSED: ["take_over", "resume"],
    }[state]
    return [(key, ACTIONS[key]) for key in allowed]


@router.post("/conversas/{conversation_id}/acao")
async def conversation_action(
    request: Request,
    auth: AuthDep,
    conversation_id: str,
    action: Annotated[Literal["take_over", "pause", "resume", "close"], Form()],
    csrf_token: Annotated[str, Form()],
) -> Response:
    _check_csrf(auth, csrf_token)
    handler = getattr(_container(request).handoff, action)
    try:
        await handler(conversation_id, auth.operator.username)
    except ConversationNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Conversa não encontrada") from exc
    return _redirect(f"/admin/conversas/{conversation_id}")


# ── configurações (admin) ───────────────────────────────────────────────────


@router.get("/configuracoes", response_class=HTMLResponse)
async def settings_page(request: Request, auth: AdminDep, saved: bool = False) -> Response:
    return await _render(
        request, "settings.html", auth, saved=saved, hours=await _hours_by_day(request)
    )


async def _hours_by_day(request: Request) -> list[OpeningWindow | None]:
    async with _container(request).db.transaction() as tx:
        store = await tx.get_store_settings()
    by_day: list[OpeningWindow | None] = [None] * 7
    for window in store.opening_hours or []:
        if by_day[window.weekday] is None:
            by_day[window.weekday] = window
    return by_day


def _parse_time(value: str) -> time | None:
    try:
        return time.fromisoformat(value) if value else None
    except ValueError:
        return None


@router.post("/configuracoes", response_class=HTMLResponse)
async def settings_submit(request: Request, auth: AdminDep) -> Response:
    form = await request.form()
    _check_csrf(auth, str(form.get("csrf_token", "")))
    container = _container(request)

    status_value = str(form.get("status", "auto"))
    website = str(form.get("website_url", "")).strip() or None
    errors: list[str] = []
    windows: list[OpeningWindow] = []
    for day in range(7):
        if form.get(f"open_{day}") != "on":
            continue
        start, end = (
            _parse_time(str(form.get(f"start_{day}", ""))),
            _parse_time(str(form.get(f"end_{day}", ""))),
        )
        if start is None or end is None or start >= end:
            errors.append(f"{labels.WEEKDAYS[day]}: horário inválido (início antes do fim).")
            continue
        windows.append(OpeningWindow(weekday=day, start=start, end=end))
    if website and not website.startswith(("https://", "http://")):
        errors.append("O link do site deve começar com https://")

    if not errors:
        async with container.db.transaction() as tx:
            store = await tx.get_store_settings()
            update = {
                "status_override": None if status_value == "auto" else status_value,
                "opening_hours": windows or None,
                "website_url": website,
            }
            try:
                new_store = store.model_validate({**store.model_dump(), **update})
            except ValidationError:
                errors.append("Configuração inválida.")
            else:
                await tx.save_store_settings(new_store, container.clock.now())
                await tx.add_audit(
                    _settings_audit(auth, container.clock.now(), status_value, len(windows))
                )
    if errors:
        return await _render(
            request,
            "settings.html",
            auth,
            status_code=400,
            errors=errors,
            hours=await _hours_by_day(request),
        )
    return _redirect("/admin/configuracoes?saved=1")


def _settings_audit(auth: AuthContext, now: datetime, status: str, windows: int) -> AuditEvent:
    return AuditEvent(
        conversation_id=None,
        kind="configuracao_loja",
        actor=auth.operator.username,
        detail={"status": status, "janelas_de_horario": windows},
        created_at=now,
    )


@router.post("/pausa-global")
async def global_pause(
    request: Request,
    auth: AdminDep,
    paused: Annotated[Literal["1", "0"], Form()],
    csrf_token: Annotated[str, Form()],
) -> Response:
    _check_csrf(auth, csrf_token)
    await _container(request).handoff.set_global_pause(paused == "1", auth.operator.username)
    return _redirect("/admin/configuracoes?saved=1")


STORE_STATUS_CHOICES = [
    ("auto", "Seguir horários cadastrados"),
    (StoreStatus.OPEN.value, "Aberta (manual)"),
    (StoreStatus.CLOSED.value, "Fechada (manual)"),
    (StoreStatus.PAUSED.value, "Atendimento pausado (manual)"),
]
TEMPLATES.env.globals["STORE_STATUS_CHOICES"] = STORE_STATUS_CHOICES
