"""Política de retenção (decisão do proprietário: 14 dias para dados de clientes).

- Conversa inativa há mais que o prazo e fora de atendimento humano: apagada por completo
  (mensagens, rascunhos, respostas). A auditoria fica, sem o identificador da conversa.
- Conversa ainda ativa: registros antigos têm texto e dados pessoais removidos.
- Conversas em HUMAN_PENDING/HUMAN_ACTIVE nunca são limpas automaticamente.
- Auditoria (sem dados pessoais) é mantida por mais tempo; sessões expiradas são apagadas.
"""

from dataclasses import asdict, dataclass
from datetime import timedelta

from app.core.clock import Clock
from app.domain.enums import HUMAN_STATES
from app.domain.models import AuditEvent, OrderDraft
from app.repositories.base import Database, Tx


@dataclass
class PurgeReport:
    dry_run: bool
    conversations_deleted: int = 0
    messages_redacted: int = 0
    replies_redacted: int = 0
    drafts_redacted: int = 0
    audit_deleted: int = 0
    sessions_deleted: int = 0


class _DryRunRollbackError(Exception):
    pass


def redact_draft(draft: OrderDraft) -> None:
    """Remove dados pessoais; mantém itens, modalidade e pagamento para estatística."""
    draft.name = None
    draft.phone_raw = None
    draft.address = None
    draft.reference = None
    draft.change_raw = None
    draft.raw_fields = {}
    draft.unknown_fields = []
    draft.unparsed_lines = []
    for item in draft.items:
        item.unknown_fields = []


class RetentionService:
    def __init__(
        self, db: Database, clock: Clock, *, retention_days: int, audit_retention_days: int
    ) -> None:
        self._db = db
        self._clock = clock
        self._retention = timedelta(days=retention_days)
        self._audit_retention = timedelta(days=audit_retention_days)

    async def purge(self, *, dry_run: bool = False) -> PurgeReport:
        report = PurgeReport(dry_run=dry_run)
        try:
            async with self._db.transaction() as tx:
                await self._purge(tx, report)
                if dry_run:
                    raise _DryRunRollbackError  # desfaz tudo, mantendo apenas a contagem
        except _DryRunRollbackError:
            pass
        return report

    async def _purge(self, tx: Tx, report: PurgeReport) -> None:
        now = self._clock.now()
        cutoff = now - self._retention

        for conv in await tx.list_conversations():
            if conv.state in HUMAN_STATES:
                continue
            last_activity = max(conv.updated_at, conv.last_customer_message_at or conv.updated_at)
            if last_activity < cutoff:
                await tx.delete_conversation(conv.id)
                report.conversations_deleted += 1
                continue
            report.messages_redacted += await tx.redact_inbound_before(conv.id, cutoff, now)
            report.replies_redacted += await tx.redact_outbound_before(conv.id, cutoff, now)
            for draft in await tx.list_drafts(conv.id):
                if (
                    draft.created_at < cutoff
                    and draft.redacted_at is None
                    and draft.id != conv.active_draft_id
                ):
                    redact_draft(draft)
                    draft.redacted_at = now
                    await tx.save_draft(draft)
                    report.drafts_redacted += 1

        report.audit_deleted = await tx.purge_audit_before(now - self._audit_retention)
        report.sessions_deleted = await tx.purge_expired_sessions(now)
        await tx.add_audit(
            AuditEvent(
                conversation_id=None,
                kind="retencao_executada",
                actor="sistema",
                detail={k: v for k, v in asdict(report).items() if k != "dry_run"},
                created_at=now,
            )
        )
