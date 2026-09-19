import httpx
from config.settings import settings
from mcp.rate_limiter import consume_request
from utils.logger import get_logger

log = get_logger("McpClient")

BASE = settings.kapruka_mcp_base_url


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after_ms: int):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class McpError(Exception):
    def __init__(self, message: str, status: int):
        super().__init__(message)
        self.status = status


async def mcp_fetch(tool_name: str, params: dict) -> dict:
    allowed, retry_after_ms = consume_request()
    if not allowed:
        raise RateLimitError(
            f"Rate limit exceeded. Retry after {retry_after_ms // 1000}s",
            retry_after_ms,
        )

    url = f"{BASE}/tools/{tool_name}"
    log.debug(f"→ {tool_name} | params={params}")

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=params)

    remaining = response.headers.get("RateLimit-Remaining")
    if remaining is not None:
        log.debug(f"Kapruka RateLimit-Remaining: {remaining}")

    if response.status_code != 200:
        log.error(f"{tool_name} failed", extra={"status": response.status_code, "body": response.text})
        raise McpError(
            f"Kapruka MCP error ({response.status_code}): {response.text}",
            response.status_code,
        )

    log.debug(f"← {tool_name} OK")
    return response.json()
