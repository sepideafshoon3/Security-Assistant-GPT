"""The refresh bug: a dropped HTTP connection must NOT stop a generation."""

from __future__ import annotations

import time
from collections.abc import Iterator

import pytest

from src.api.generation import GenerationAlreadyRunningError, GenerationManager


def _slow_stream(n: int = 6, delay: float = 0.03) -> Iterator[str]:
    for i in range(n):
        time.sleep(delay)
        yield f"w{i} "


async def _collect(mgr: GenerationManager, gen, start: int = 0) -> list[str]:
    return [p async for p in mgr.subscribe(gen, start)]


@pytest.mark.asyncio
async def test_subscriber_disconnect_does_not_stop_generation() -> None:
    mgr, saved = GenerationManager(), []
    gen = mgr.start("c1", _slow_stream(), persist=saved.append)

    # first "page": reads a bit, then is torn down (= refresh)
    sub = mgr.subscribe(gen)
    first = await sub.__anext__()
    await sub.aclose()
    assert first == "w0 "

    # second "page" re-attaches mid-flight and gets everything via replay
    assert mgr.is_active("c1")
    replay = await _collect(mgr, gen, 0)
    assert "".join(replay) == "w0 w1 w2 w3 w4 w5 "
    assert saved == ["w0 w1 w2 w3 w4 w5"]  # full reply, not a truncated one
    assert not mgr.is_active("c1")


@pytest.mark.asyncio
async def test_explicit_stop_keeps_partial_and_closes_upstream() -> None:
    mgr, saved, closed = GenerationManager(), [], []

    def stream() -> Iterator[str]:
        try:
            yield from _slow_stream(50)
        finally:
            closed.append(True)

    gen = mgr.start("c2", stream(), persist=saved.append)
    sub = mgr.subscribe(gen)
    await sub.__anext__()
    assert mgr.stop("c2") is True
    rest = [p async for p in sub]

    assert gen.stopped and gen.error is None
    assert 0 < len(saved[0]) < len("w00 " * 50)
    assert closed == [True]  # upstream generator really closed
    assert len(rest) < 49


@pytest.mark.asyncio
async def test_second_start_for_same_conversation_rejected() -> None:
    mgr = GenerationManager()
    gen = mgr.start("c3", _slow_stream(), persist=lambda _t: None)
    with pytest.raises(GenerationAlreadyRunningError):
        mgr.start("c3", _slow_stream(), persist=lambda _t: None)
    await _collect(mgr, gen)


@pytest.mark.asyncio
async def test_error_is_reported_and_after_hook_skipped() -> None:
    mgr, saved, after_calls = GenerationManager(), [], []

    def boom() -> Iterator[str]:
        yield "partial"
        raise RuntimeError("provider down")

    async def after() -> None:
        after_calls.append(1)

    gen = mgr.start("c4", boom(), persist=saved.append, after=after)
    await _collect(mgr, gen)
    assert gen.error == "provider down"
    assert saved == ["partial"] and after_calls == []


@pytest.mark.asyncio
async def test_after_hook_runs_before_finished() -> None:
    mgr, order = GenerationManager(), []

    async def after() -> None:
        order.append("after")

    gen = mgr.start("c5", _slow_stream(2), persist=lambda _t: None, after=after)
    await _collect(mgr, gen)
    order.append("subscriber-done")
    assert order == ["after", "subscriber-done"]
