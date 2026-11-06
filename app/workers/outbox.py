"""Processamento da outbox em segundo plano, dentro do próprio processo da aplicação.

Sem Redis/Celery: a fila é a própria tabela outbound_messages, suficiente para o volume
inicial. Pode rodar em mais de um processo porque a reivindicação é atômica no banco.
"""

import asyncio
import logging

from app.services.dispatcher import Dispatcher

logger = logging.getLogger(__name__)


class OutboxWorker:
    def __init__(self, dispatcher: Dispatcher, poll_seconds: float) -> None:
        self._dispatcher = dispatcher
        self._poll_seconds = poll_seconds

    async def run_once(self) -> int:
        await self._dispatcher.recover_stale_sending()
        return len(await self._dispatcher.dispatch_due())

    async def run_forever(self) -> None:
        logger.info("outbox iniciada (intervalo=%ss)", self._poll_seconds)
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("erro no processamento da outbox")
            await asyncio.sleep(self._poll_seconds)
