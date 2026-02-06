"""Helpers for running async code from sync contexts."""

from __future__ import annotations

import asyncio
import threading
from typing import Coroutine, TypeVar

R = TypeVar("R")

_loop_lock = threading.Lock()
_loop_ready = threading.Event()
_loop: asyncio.AbstractEventLoop | None = None
_thread: threading.Thread | None = None
_thread_ident: int | None = None


def _loop_runner(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    _loop_ready.set()
    loop.run_forever()


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    global _loop, _thread
    if _loop is not None and _loop.is_running():
        return _loop
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop_ready.clear()
        _loop = asyncio.new_event_loop()
        _thread = threading.Thread(
            target=_loop_runner,
            name="sudoagent-async-loop",
            args=(_loop,),
            daemon=True,
        )
        _thread.start()
        global _thread_ident
        _thread_ident = _thread.ident
        _loop_ready.wait()
        return _loop


def run_sync(coro: Coroutine[object, object, R]) -> R:
    """Run an async coroutine from sync code without creating a new event loop each call."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError("run_sync cannot be called from within an async event loop")
    if _thread_ident is not None and threading.get_ident() == _thread_ident:
        raise RuntimeError("run_sync cannot be called from the background loop thread")
    loop = _ensure_background_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()
