import json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from config.settings import settings
from mcp.rate_limiter import consume_request
from utils.logger import get_logger

log = get_logger("McpClient")

BASE = settings.kapruka_mcp_base_url  # https://mcp.kapruka.com


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after_ms: int):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class McpError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


async def mcp_fetch(tool_name: str, params: dict) -> dict:
    # Check global rate limit before every call
    allowed, retry_after_ms = consume_request()
    if not allowed:
        raise RateLimitError(
            f"Rate limit exceeded. Retry after {retry_after_ms // 1000}s",
            retry_after_ms,
        )

    log.debug(f"→ {tool_name} | params={params}")

    try:
        async with streamablehttp_client(BASE) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments=params)

        log.debug(f"← {tool_name} OK")

        # Result content is a list of TextContent blocks
        if result.content and result.content[0].type == "text":
            return json.loads(result.content[0].text)

        # Fallback: return raw result
        return {"content": [c.model_dump() for c in result.content]}

    except RateLimitError:
        raise
    except Exception as e:
        log.error(f"{tool_name} failed: {e}")
        raise McpError(str(e))