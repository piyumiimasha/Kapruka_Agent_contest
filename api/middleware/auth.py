from datetime import datetime, timedelta
from uuid import uuid4
from fastapi import Request, Response
from jose import jwt, JWTError
from config.settings import settings
from utils.logger import get_logger

log = get_logger("Auth")


def create_token(session_id: str) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.jwt_expires_in_days)
    return jwt.encode(
        {"session_id": session_id, "exp": expire},
        settings.jwt_secret,
        algorithm="HS256",
    )


def get_or_create_session(request: Request, response: Response) -> str:
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]

    if token:
        try:
            payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
            session_id = payload["session_id"]
            log.debug(f"Authenticated: {session_id}")
            return session_id
        except JWTError:
            log.warning("Invalid token — issuing anonymous session")

    # Anonymous fallback
    session_id = str(uuid4())
    new_token = create_token(session_id)
    response.headers["X-Session-Token"] = new_token
    log.info(f"Anonymous session: {session_id}")
    return session_id
