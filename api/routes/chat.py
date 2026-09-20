from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from agents.orchestrator import run_orchestrator
from kapruka_mcp.rate_limiter import get_rate_limit_status
from api.middleware.auth import get_or_create_session
from utils.logger import get_logger

log = get_logger("ChatRoute")
router = APIRouter()


class ChatRequest(BaseModel):
    message: str


@router.post("/")
async def chat(body: ChatRequest, request: Request, response: Response):
    if not body.message.strip():
        return {"error": "message is required"}, 400

    session_id = get_or_create_session(request, response)
    log.info(f"Chat | session={session_id} | msg={body.message[:80]}")

    result = await run_orchestrator(session_id, body.message.strip())
    return {
        **result,
        "session_id":  session_id,
        "rate_limits": get_rate_limit_status(),
    }


@router.get("/status")
async def status(request: Request, response: Response):
    session_id = get_or_create_session(request, response)
    return {"status": "ok", "session_id": session_id, "rate_limits": get_rate_limit_status()}
