"""
Past chats: list them and re-open one.

The conversation is read back from the LangGraph checkpoint (the same thread_id the
chat route uses); chat_threads only supplies the list and the titles.
"""
from fastapi import APIRouter, HTTPException, Request, Response

from api.middleware.auth import get_or_create_session
from api.routes.chat import _ids, _valid_chat_id
from db.thread_repository import list_threads, thread_exists
from graph.history import serialize_messages, thread_state

router = APIRouter()


@router.get("")
async def my_threads(request: Request, response: Response):
    user_id = get_or_create_session(request, response)
    return {"threads": await list_threads(user_id)}


@router.get("/{chat_id}/messages")
async def thread_messages(chat_id: str, request: Request, response: Response):
    chat_id = _valid_chat_id(chat_id)
    user_id, session_id = _ids(request, response, chat_id)
    # Ownership: the row is keyed by the JWT's user_id, and the checkpoint thread_id
    # starts with it too, so another user's chat can never be read.
    if not await thread_exists(user_id, chat_id):
        raise HTTPException(status_code=404, detail="Chat not found")
    snap = await thread_state(request.app.state.graph, session_id)
    return {"chat_id": chat_id,
            "messages": serialize_messages(list((snap.values or {}).get("messages", [])))}
