"""Orquestração do atendimento: uma mensagem recebida → estado + intenções de resposta.

Este serviço não envia nada: grava intenções (OutboundIntent) que o Dispatcher envia depois,
revalidando estado, pausa e janela de atendimento no momento do envio.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from pydantic import BaseModel

from app.core.clock import Clock
from app.core.logging import mask_id
from app.domain.enums import (
    HUMAN_STATES,
    ConversationState,
    DraftState,
    Intent,
    MediaPolicy,
    ReplyKind,
    StoreStatus,
)
from app.domain.models import AuditEvent, Conversation, InboundMessage, OrderDraft, OutboundIntent
from app.domain.store import StoreSettings
from app.domain.validation import ValidationResult, validate_draft
from app.parsers.pending_reply import parse_pending_reply
from app.parsers.site_order import parse_site_order, set_order_field
from app.repositories.base import Database, Tx
from app.services.intents import classify
from app.services.replies import ask_data_text, confirmation_text, render
from app.services.transitions import transition

logger = logging.getLogger(__name__)

BOT_ACTOR = "bot"
_HANDOFF_INTENTS = frozenset(
    {
        Intent.HUMAN_REQUEST,
        Intent.CANCEL_OR_CHANGE,
        Intent.COMPLAINT,
        Intent.STATUS_QUESTION,
        Intent.QUESTION,
    }
)
_STORE_REPLIES = {
    StoreStatus.CLOSED: ReplyKind.STORE_CLOSED,
    StoreStatus.PAUSED: ReplyKind.STORE_PAUSED,
    StoreStatus.UNKNOWN: ReplyKind.STORE_UNKNOWN,
}


class HandleResult(BaseModel):
    duplicate: bool = False
    skipped_reason: str | None = None
    intent: Intent | None = None
    conversation_state: ConversationState | None = None
    draft_id: str | None = None
    outbound_ids: list[str] = []


@dataclass
class _Ctx:
    tx: Tx
    conv: Conversation
    store: StoreSettings
    msg: InboundMessage
    now: datetime
    result: HandleResult = field(default_factory=HandleResult)


class ConversationService:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def handle_inbound(self, msg: InboundMessage) -> HandleResult:
        # Uma transação: mensagem, estado, rascunho, respostas e auditoria são gravados juntos.
        # Se algo falhar, nada fica gravado e o reenvio do mesmo evento é processado de novo.
        async with self._db.transaction() as tx:
            if not await tx.add_inbound(msg):
                logger.info("mensagem duplicada ignorada id=%s", msg.provider_message_id)
                return HandleResult(duplicate=True)

            now = self._clock.now()
            store = await tx.get_store_settings()
            conv = await tx.get_conversation(msg.conversation_id) or Conversation(
                id=msg.conversation_id, created_at=now, updated_at=now
            )
            last = conv.last_customer_message_at
            conv.last_customer_message_at = (
                msg.timestamp if last is None else max(last, msg.timestamp)
            )
            conv.last_inbound_message_id = msg.provider_message_id
            if msg.provider_user_id:
                conv.provider_user_id = msg.provider_user_id
            conv.updated_at = now
            ctx = _Ctx(tx=tx, conv=conv, store=store, msg=msg, now=now)

            if store.automation_paused:
                ctx.result.skipped_reason = "pausa_global"
            elif conv.state in HUMAN_STATES:
                ctx.result.skipped_reason = "atendimento_humano"
            elif conv.state is ConversationState.CLOSED:
                # Encerramento não autoriza reabertura automática: a equipe decide.
                await self._transition(
                    ctx, ConversationState.HUMAN_PENDING, "mensagem_apos_encerramento"
                )
                ctx.result.skipped_reason = "conversa_encerrada"
            else:
                await self._route(ctx)

            saved = await tx.save_conversation(conv)
            ctx.result.conversation_state = saved.state
            logger.info(
                "mensagem processada conversa=%s intencao=%s estado=%s respostas=%d motivo=%s",
                mask_id(saved.id),
                ctx.result.intent,
                saved.state,
                len(ctx.result.outbound_ids),
                ctx.result.skipped_reason,
            )
            return ctx.result

    # ── roteamento ──────────────────────────────────────────────────────────

    async def _route(self, ctx: _Ctx) -> None:
        intent = classify(ctx.msg.type, ctx.msg.text)
        ctx.result.intent = intent

        if intent is Intent.MEDIA:
            await self._media(ctx)
        elif intent is Intent.SITE_ORDER:
            await self._new_order(ctx)
        elif intent in _HANDOFF_INTENTS:
            await self._handoff(
                ctx, f"intencao_{intent.value}", ReplyKind.HANDOFF, ctx.store.texts.handoff
            )
        elif ctx.conv.state is ConversationState.COLLECTING_DATA:
            await self._pending_reply(ctx)
        elif intent is Intent.GREETING:
            await self._greeting(ctx)
        elif intent is Intent.BUY and ctx.store.website_url:
            await self._reply(
                ctx, ReplyKind.SITE_REDIRECT, render(ctx.store.texts.site_redirect, ctx.store)
            )
        else:
            # Dúvida sem base cadastrada, ou sem link do site para direcionar.
            await self._handoff(
                ctx, f"intencao_{intent.value}", ReplyKind.HANDOFF, ctx.store.texts.handoff
            )

    async def _greeting(self, ctx: _Ctx) -> None:
        texts = ctx.store.texts
        template = texts.greeting if ctx.store.website_url else texts.greeting_no_link
        await self._reply(ctx, ReplyKind.GREETING, render(template, ctx.store))

    async def _media(self, ctx: _Ctx) -> None:
        texts = ctx.store.texts
        if ctx.store.media_policy is MediaPolicy.ASK_TEXT:
            await self._reply(ctx, ReplyKind.MEDIA, render(texts.media_ask_text, ctx.store))
        else:
            await self._handoff(ctx, "midia_recebida", ReplyKind.MEDIA, texts.media_handoff)

    # ── fluxo A: pedido do site ─────────────────────────────────────────────

    async def _new_order(self, ctx: _Ctx) -> None:
        draft = parse_site_order(
            ctx.msg.text or "",
            conversation_id=ctx.conv.id,
            source_message_id=ctx.msg.provider_message_id,
            now=ctx.now,
        )
        draft.possible_duplicate_of = await self._find_duplicate(ctx, draft)
        if ctx.conv.active_draft_id:
            await self._audit(
                ctx, "rascunho_substituido", anterior=ctx.conv.active_draft_id, novo=draft.id
            )
        ctx.conv.active_draft_id = draft.id
        await self._evaluate(ctx, draft, previous_pending=None)

    async def _pending_reply(self, ctx: _Ctx) -> None:
        draft = await ctx.tx.get_draft(ctx.conv.active_draft_id or "")
        if draft is None:
            await self._handoff(
                ctx, "rascunho_nao_encontrado", ReplyKind.HANDOFF, ctx.store.texts.handoff
            )
            return
        before = validate_draft(draft, ctx.store, ctx.conv.id).pending_fields
        reply = parse_pending_reply(ctx.msg.text or "", before)
        if reply.needs_review:
            draft.state = DraftState.NEEDS_REVIEW
            await self._save_draft(ctx, draft)
            await self._handoff(
                ctx,
                "alteracao_requer_revisao",
                ReplyKind.REVIEW_HANDOFF,
                ctx.store.texts.review_handoff,
            )
            return
        for field_name, raw in reply.updates.items():
            set_order_field(draft, field_name, raw)
        if reply.updates:
            await self._audit(
                ctx,
                "rascunho_atualizado",
                rascunho=draft.id,
                campos=list(reply.updates),
                mensagem=ctx.msg.provider_message_id,
            )
        await self._evaluate(ctx, draft, previous_pending=before)

    async def _evaluate(
        self, ctx: _Ctx, draft: OrderDraft, *, previous_pending: list[str] | None
    ) -> None:
        result = validate_draft(draft, ctx.store, ctx.conv.id)
        draft.issues = result.issues
        ctx.result.draft_id = draft.id

        if result.requires_human:
            draft.state = DraftState.NEEDS_REVIEW
            await self._save_draft(ctx, draft)
            await self._handoff(
                ctx,
                "pedido_requer_revisao",
                ReplyKind.REVIEW_HANDOFF,
                ctx.store.texts.review_handoff,
            )
            return

        pending = result.pending_fields
        if not pending:
            await self._complete(ctx, draft, result)
            return

        draft.state = DraftState.INCOMPLETE
        retry = previous_pending is not None
        if retry:
            resolved_any = bool(set(previous_pending or []) - set(pending))
            if not resolved_any:
                draft.correction_attempts += 1
            if draft.correction_attempts >= ctx.store.max_correction_attempts:
                draft.state = DraftState.NEEDS_REVIEW
                await self._save_draft(ctx, draft)
                await self._handoff(
                    ctx,
                    "limite_de_tentativas",
                    ReplyKind.HANDOFF,
                    ctx.store.texts.attempts_exceeded,
                )
                return

        await self._save_draft(ctx, draft)
        if ctx.conv.state is not ConversationState.COLLECTING_DATA:
            await self._transition(ctx, ConversationState.COLLECTING_DATA, "dados_pendentes")
        await self._reply(
            ctx,
            ReplyKind.ASK_DATA,
            ask_data_text(ctx.store, result.customer_issues, retry=retry),
        )

    async def _complete(self, ctx: _Ctx, draft: OrderDraft, result: ValidationResult) -> None:
        status = ctx.store.effective_status(ctx.now)
        if status is StoreStatus.OPEN:
            draft.state = DraftState.RECEIVED
            await self._save_draft(ctx, draft)
            await self._handoff(
                ctx,
                "pedido_recebido",
                ReplyKind.CONFIRMATION,
                confirmation_text(ctx.store, draft, result),
            )
            return
        # Fechado, pausado ou sem configuração: não confirmar; a equipe confere.
        draft.state = DraftState.NEEDS_REVIEW
        await self._save_draft(ctx, draft)
        texts = ctx.store.texts
        template = {
            StoreStatus.CLOSED: texts.store_closed,
            StoreStatus.PAUSED: texts.store_paused,
            StoreStatus.UNKNOWN: texts.store_unknown,
        }[status]
        await self._handoff(ctx, f"loja_{status.value}", _STORE_REPLIES[status], template)

    async def _find_duplicate(self, ctx: _Ctx, draft: OrderDraft) -> str | None:
        window = timedelta(minutes=ctx.store.duplicate_window_minutes)
        for other in await ctx.tx.list_drafts(ctx.conv.id):
            if (
                other.fingerprint == draft.fingerprint
                and other.source_message_id != draft.source_message_id
                and ctx.now - other.created_at <= window
            ):
                return other.id
        return None

    # ── utilitários ─────────────────────────────────────────────────────────

    async def _handoff(self, ctx: _Ctx, reason: str, kind: ReplyKind, template: str) -> None:
        await self._transition(ctx, ConversationState.HUMAN_PENDING, reason)
        await self._reply(ctx, kind, render(template, ctx.store))

    async def _transition(self, ctx: _Ctx, state: ConversationState, reason: str) -> None:
        await transition(ctx.tx, ctx.conv, state, reason=reason, actor=BOT_ACTOR, now=ctx.now)

    async def _reply(self, ctx: _Ctx, kind: ReplyKind, text: str) -> None:
        intent = OutboundIntent(
            conversation_id=ctx.conv.id,
            idempotency_key=f"{ctx.msg.provider_message_id}:{kind.value}",
            kind=kind,
            text=text,
            reply_epoch=ctx.conv.reply_epoch,
            source_message_id=ctx.msg.provider_message_id,
            created_at=ctx.now,
            updated_at=ctx.now,
        )
        if await ctx.tx.add_outbound(intent):
            ctx.result.outbound_ids.append(intent.id)

    async def _save_draft(self, ctx: _Ctx, draft: OrderDraft) -> None:
        draft.updated_at = ctx.now
        await ctx.tx.save_draft(draft)

    async def _audit(self, ctx: _Ctx, kind: str, **detail: str | list[str]) -> None:
        await ctx.tx.add_audit(
            AuditEvent(
                conversation_id=ctx.conv.id,
                kind=kind,
                actor=BOT_ACTOR,
                detail=dict(detail),
                created_at=ctx.now,
            )
        )
