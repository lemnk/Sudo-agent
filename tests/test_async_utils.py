import asyncio

import pytest

from sudoagent.async_utils import run_sync


async def _async_value() -> int:
    await asyncio.sleep(0)
    return 42


def test_run_sync_executes_coroutine() -> None:
    assert run_sync(_async_value()) == 42


def test_run_sync_raises_inside_event_loop() -> None:
    async def _inner() -> None:
        coro = _async_value()
        try:
            with pytest.raises(RuntimeError):
                run_sync(coro)
        finally:
            coro.close()

    asyncio.run(_inner())
