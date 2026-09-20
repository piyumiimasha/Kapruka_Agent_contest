from langfuse import Langfuse
from config.settings import settings
from utils.logger import get_logger

log = get_logger("Tracer")

# Singleton Langfuse client
_langfuse: Langfuse | None = None


def get_langfuse() -> Langfuse:
    global _langfuse
    if _langfuse is None:
        _langfuse = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        log.info("Langfuse client initialized")
    return _langfuse


def trace(name: str, session_id: str, user_id: str = None, metadata: dict = None):
    """Start a new Langfuse trace — one per user message."""
    return get_langfuse().trace(
        name=name,
        session_id=session_id,
        user_id=user_id,
        metadata=metadata or {},
    )