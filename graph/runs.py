"""
Tracks in-flight message runs so the user can press "Stop".

Stopping = cancelling the asyncio task that runs graph.ainvoke(). This is NOT
LangGraph's interrupt(): interrupt() is a pause a node asks for on purpose;
cancellation is an external abort of the whole run.

Your order agent creates the order itself inside its tool loop, so cancelling it
could leave a real order created but never shown. While the order node runs the
thread is marked "protected" and Stop is refused.

In-memory and single-process. With several uvicorn workers a shared channel
(e.g. Redis pub/sub) would be needed to reach the worker that owns the run.
"""
import asyncio
from contextlib import contextmanager

_RUNNING: dict[str, asyncio.Task] = {}
_PROTECTED: set[str] = set()


def is_running(thread_id: str) -> bool:
    t = _RUNNING.get(thread_id)
    return bool(t and not t.done())


def register(thread_id: str, task: asyncio.Task) -> None:
    _RUNNING[thread_id] = task


def unregister(thread_id: str, task: asyncio.Task) -> None:
    if _RUNNING.get(thread_id) is task:
        del _RUNNING[thread_id]


@contextmanager
def protected(thread_id: str):
    """Mark a thread as un-stoppable (used while the order agent may place an order)."""
    _PROTECTED.add(thread_id)
    try:
        yield
    finally:
        _PROTECTED.discard(thread_id)


def request_stop(thread_id: str) -> str:
    """'stopped' | 'protected' | 'not_running'."""
    if not is_running(thread_id):
        return "not_running"
    if thread_id in _PROTECTED:
        return "protected"
    _RUNNING[thread_id].cancel()
    return "stopped"
