"""
Reading and editing a thread through the checkpointer.

- Checkpoints are immutable snapshots forming a TREE (each has a parent).
- Every turn starts with an "input" checkpoint (metadata source == "input") whose
  messages are everything BEFORE that turn. That is the fork point for an edit.
- "Editing" never changes old checkpoints: we fork from the checkpoint just before
  the message (update_state(parent, None)), which becomes the new head. The old
  branch stays stored.
"""
from langchain_core.messages import AIMessage, HumanMessage

from utils.logger import get_logger

log = get_logger("History")


class NothingToEdit(Exception):
    pass


class StaleEdit(Exception):
    pass


class EditBlocked(Exception):
    pass


def thread_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _cid(snap):
    return ((snap.config or {}).get("configurable") or {}).get("checkpoint_id")


def _pid(snap):
    return ((snap.parent_config or {}).get("configurable") or {}).get("checkpoint_id")


def _may_have_placed_order(m) -> bool:
    """
    Your order agent creates the order inside its own tool loop and the graph only
    sees its text reply, so this is a heuristic: an order-agent reply that carries a
    payment link or says the order was placed. Edits that would drop such a reply
    are refused, because editing cannot cancel a real order.
    """
    if not isinstance(m, AIMessage) or (m.additional_kwargs or {}).get("agent") != "order":
        return False
    text = (m.content or "").lower()
    return "http" in text or "order placed" in text or "✅" in text


async def thread_state(graph, session_id: str):
    return await graph.aget_state(thread_config(session_id))


def serialize_messages(msgs: list) -> list[dict]:
    """Messages -> JSON for the UI. agent + product cards ride on the AIMessage."""
    out, h = [], 0
    for m in msgs:
        if isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content, "human_index": h})
            h += 1
        elif isinstance(m, AIMessage):
            kw = m.additional_kwargs or {}
            out.append({"role": "assistant", "content": m.content,
                        "agent": kw.get("agent"), "products": kw.get("products") or []})
    return out


async def _find_input_checkpoint(graph, session_id: str, head, wanted):
    """
    Walk the CURRENT branch from the head back via parent links (one query for all
    checkpoints, then in memory - the raw history also holds abandoned branches) and
    return the first 'input' checkpoint for which wanted(snap) is true.
    """
    snaps = [s async for s in graph.aget_state_history(thread_config(session_id))]
    by_id = {_cid(s): s for s in snaps if _cid(s)}
    snap, seen = head, set()
    while snap is not None and _cid(snap) and _cid(snap) not in seen:
        seen.add(_cid(snap))
        if (snap.metadata or {}).get("source") == "input" and wanted(snap):
            return snap
        snap = by_id.get(_pid(snap))
    return None


async def _fork_before(graph, session_id: str, start, removed) -> dict:
    """`start` is the 'input' checkpoint of a turn: make the state before it the new head."""
    if start.parent_config is None:
        # first turn of the thread: nothing earlier to fork from -> start over
        deleter = getattr(graph.checkpointer, "adelete_thread", None)
        if deleter is not None:
            await deleter(session_id)
        else:
            await graph.aupdate_state(start.config, None)   # fork the (empty) input checkpoint
        return {"removed_message": removed, "empty": True}

    await graph.aupdate_state(start.parent_config, None)    # fork: new head = state before the turn
    return {"removed_message": removed, "empty": False}


async def rewind_to_message(graph, session_id: str, human_index: int,
                            expected: str | None = None) -> dict:
    """
    Time travel to just before the human_index-th user message (0-based): that message
    and everything after it are dropped. The caller then sends the edited text as a
    normal turn. `expected` is what the UI believes it is editing; if the server's copy
    differs the UI is out of date and we refuse rather than edit the wrong message.
    """
    head = await thread_state(graph, session_id)
    msgs = list((head.values or {}).get("messages", []))
    humans = [i for i, m in enumerate(msgs) if isinstance(m, HumanMessage)]
    if not 0 <= human_index < len(humans):
        raise NothingToEdit("That message no longer exists in this chat.")
    target = humans[human_index]
    original = msgs[target].content or ""

    if expected is not None and original.strip() != expected.strip():
        raise StaleEdit("This chat changed since it was loaded.")
    if any(_may_have_placed_order(m) for m in msgs[target:]):
        raise EditBlocked("An order was placed after that message, and editing can't cancel it.")

    start = await _find_input_checkpoint(
        graph, session_id, head,
        lambda s: len((s.values or {}).get("messages", [])) == target)
    if start is None:
        raise NothingToEdit("Could not find where that message started.")
    return await _fork_before(graph, session_id, start, original)


async def discard_unfinished_turn(graph, session_id: str) -> dict | None:
    """
    After Stop: the cancelled turn left the user's message in the thread and unfinished
    nodes in `next`. Fork back to before that turn so the thread is clean. Returns None
    if nothing was unfinished (the turn had already completed).
    """
    head = await thread_state(graph, session_id)
    if not head.next:
        return None
    start = await _find_input_checkpoint(graph, session_id, head, lambda s: True)
    if start is None:
        return None
    n_before = len((start.values or {}).get("messages", []))
    msgs = list((head.values or {}).get("messages", []))
    removed = (msgs[n_before].content if len(msgs) > n_before
               and isinstance(msgs[n_before], HumanMessage) else None)
    return await _fork_before(graph, session_id, start, removed)
