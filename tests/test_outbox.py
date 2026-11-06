"""Fila de envio: novas tentativas, espera, recuperação e concorrência."""

import asyncio
import contextlib
from datetime import timedelta

from app.domain.enums import OutboundStatus
from app.integrations.whatsapp.gateway import GatewayError
from tests.conftest import SENDER, load_order


def transient() -> GatewayError:
    return GatewayError("rate_limit", retryable=True)


async def test_transient_failure_is_retried_after_backoff(h, clock):
    h.gateway.fail_next(transient())
    await h.receive("Oi")
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.PENDING
    assert intent.attempts == 1
    assert intent.status_reason == "rate_limit"
    assert intent.next_attempt_at == clock.now() + timedelta(seconds=5)

    assert await h.c.worker.run_once() == 0  # ainda não venceu
    assert h.gateway.sent == []

    clock.advance(seconds=6)
    assert await h.c.worker.run_once() == 1
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.SENT
    assert intent.attempts == 2
    assert len(h.gateway.sent) == 1


async def test_backoff_grows_and_attempts_are_limited(h, clock):
    for _ in range(5):
        h.gateway.fail_next(transient())
    await h.receive("Oi")
    delays = []
    for _ in range(4):
        [intent] = await h.outbound()
        delays.append((intent.next_attempt_at - clock.now()).total_seconds())
        clock.advance(seconds=400)
        await h.c.worker.run_once()
    assert delays == [5, 10, 20, 40]
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.FAILED
    assert intent.status_reason == "rate_limit:tentativas_esgotadas"
    assert intent.attempts == 5
    assert h.gateway.sent == []


async def test_handoff_between_attempts_cancels_retry(h, clock):
    h.gateway.fail_next(transient())
    await h.receive("Oi")
    await h.c.handoff.take_over(SENDER, "joao")
    clock.advance(seconds=60)
    await h.c.worker.run_once()
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.CANCELLED
    assert h.gateway.sent == []


async def test_retry_outside_24h_window_is_blocked(h, clock):
    h.gateway.fail_next(transient())
    await h.receive("Oi")
    clock.advance(hours=25)
    await h.c.worker.run_once()
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.BLOCKED
    assert h.gateway.sent == []


async def test_interrupted_send_becomes_unknown_and_is_not_resent(h, clock):
    await h.receive("Oi", dispatch=False)
    [intent] = await h.outbound()
    intent.status = OutboundStatus.SENDING
    intent.sending_started_at = clock.now()
    await h.q("save_outbound", intent)

    clock.advance(seconds=60)
    await h.c.worker.run_once()
    assert (await h.outbound())[0].status is OutboundStatus.SENDING  # lease ainda válido

    clock.advance(seconds=61)
    await h.c.worker.run_once()
    [intent] = await h.outbound()
    assert intent.status is OutboundStatus.UNKNOWN
    assert intent.status_reason == "interrompido_durante_envio"
    await h.c.worker.run_once()
    assert h.gateway.sent == []


async def test_concurrent_dispatchers_send_once(h):
    await h.receive(load_order("delivery_pix_valido"), dispatch=False)
    [intent] = await h.outbound()
    results = await asyncio.gather(*(h.c.dispatcher.dispatch_intent(intent.id) for _ in range(5)))
    assert len(h.gateway.sent) == 1
    assert {r.status for r in results} == {OutboundStatus.SENT}


async def test_worker_picks_up_replies_from_any_conversation(h):
    await h.receive("Oi", dispatch=False)
    await h.receive("Bom dia", sender="5511963217045", dispatch=False)
    assert await h.c.worker.run_once() == 2
    assert len(h.gateway.sent) == 2


async def test_worker_survives_errors(h, monkeypatch):
    calls = 0

    async def boom():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("falha temporária")
        raise asyncio.CancelledError

    monkeypatch.setattr(h.c.worker, "run_once", boom)
    monkeypatch.setattr(h.c.worker, "_poll_seconds", 0)
    with contextlib.suppress(asyncio.CancelledError):
        await h.c.worker.run_forever()
    assert calls == 2
