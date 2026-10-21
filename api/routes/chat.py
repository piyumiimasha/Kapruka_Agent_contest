from fastapi import APIRouter, Request, Response
from pydantic import BaseModel
from agents.orchestrator import run_orchestrator
from kapruka_mcp.rate_limiter import get_rate_limit_status
from kapruka_mcp.tools.get_product import get_product
from utils.product_parser import extract_single_product
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

    session_id  = get_or_create_session(request, response)
    auth_header = request.headers.get("Authorization", "")
    log.info(f"CHAT AUTH | has_authorization={bool(auth_header)} | is_bearer={auth_header.startswith('Bearer ')} | session={session_id}")

    message = body.message.strip()

    # ── Product detail fetch for modal (bypasses orchestrator) ───────────
    if message.startswith("__get_product_detail__:"):
        parts      = message.split(":", 2)
        product_id = parts[1].strip() if len(parts) > 1 else ""
        if product_id:
            try:
                result = await get_product(product_id=product_id, currency="LKR")
                parsed = extract_single_product(result)
                return {
                    "reply":      "",
                    "agent":      "discovery",
                    "products":   [parsed] if parsed else [],
                    "session_id": session_id,
                    "rate_limits": get_rate_limit_status(),
                }
            except Exception as e:
                log.error(f"Product detail fetch failed: {e}")
                return {"reply": "", "agent": "discovery", "products": [],
                        "session_id": session_id, "rate_limits": get_rate_limit_status()}

    log.info(f"Chat | session={session_id} | msg={message[:80]}")
    result = await run_orchestrator(session_id, message)
    return {**result, "session_id": session_id, "rate_limits": get_rate_limit_status()}


@router.get("/status")
async def status(request: Request, response: Response):
    session_id = get_or_create_session(request, response)
    return {"status": "ok", "session_id": session_id, "rate_limits": get_rate_limit_status()}