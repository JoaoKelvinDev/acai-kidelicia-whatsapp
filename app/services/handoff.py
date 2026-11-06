"""Controle humano: assumir, pausar, retomar, encerrar e pausa global.

Na Etapa 1 só é exposto pelas rotas /dev (sem produção). A Etapa 2 adiciona autenticação e
autorização antes de expor estes controles.
"""

from app.core.clock import Clock
from app.domain.enums import ConversationState
from app.domain.models import AuditEvent, Conversation
from app.repositories.base import Repository
from app.services.transitions import transition


class ConversationNotFoundError(Exception):
    pass


def _check_actor(actor: str) -> str:
    actor = actor.strip()
    if not actor:
        raise ValueError("ação humana exige identificação do responsável")
    return actor


class HandoffService:
    def __init__(self, repo: Repository, clock: Clock) -> None:
        self._repo = repo
        self._clock = clock

    async def take_over(self, conversation_id: str, actor: str) -> Conversation:
        return await self._apply(
            conversation_id, actor, ConversationState.HUMAN_ACTIVE, "assumida", assign=True
        )

    async def pause(self, conversation_id: str, actor: str) -> Conversation:
        return await self._apply(conversation_id, actor, ConversationState.HUMAN_PENDING, "pausada")

    async def resume(self, conversation_id: str, actor: str) -> Conversation:
        # Retomada explícita: volta ao automático sem reaproveitar pendências antigas.
        return await self._apply(
            conversation_id, actor, ConversationState.AUTO_ACTIVE, "retomada", clear=True
        )

    async def close(self, conversation_id: str, actor: str) -> Conversation:
        # Encerrar não apaga histórico.
        return await self._apply(
            conversation_id, actor, ConversationState.CLOSED, "encerrada", clear=True
        )

    async def set_global_pause(self, paused: bool, actor: str) -> None:
        actor = _check_actor(actor)
        store = await self._repo.get_store_settings()
        store.automation_paused = paused
        await self._repo.save_store_settings(store)
        await self._repo.add_audit(
            AuditEvent(
                conversation_id=None,
                kind="pausa_global",
                actor=actor,
                detail={"pausada": paused},
                created_at=self._clock.now(),
            )
        )

    async def _apply(
        self,
        conversation_id: str,
        actor: str,
        state: ConversationState,
        reason: str,
        *,
        assign: bool = False,
        clear: bool = False,
    ) -> Conversation:
        actor = _check_actor(actor)
        async with self._repo.lock(conversation_id):
            conv = await self._repo.get_conversation(conversation_id)
            if conv is None:
                raise ConversationNotFoundError(conversation_id)
            now = self._clock.now()
            await transition(self._repo, conv, state, reason=reason, actor=actor, now=now)
            conv.assignee = actor if assign else None
            if clear:
                conv.active_draft_id = None
            return await self._repo.save_conversation(conv)
