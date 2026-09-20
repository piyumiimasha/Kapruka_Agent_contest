import json
import uuid
import httpx
from config.settings import settings
from kapruka_mcp.rate_limiter import consume_request
from utils.logger import get_logger

log = get_logger("McpClient")

BASE = settings.kapruka_mcp_base_url.rstrip("/")
MCP_URL = f"{BASE}/mcp"

_session_id: str | None = None


class RateLimitError(Exception):
    def __init__(self, message: str, retry_after_ms: int):
        super().__init__(message)
        self.retry_after_ms = retry_after_ms


class McpError(Exception):
    def __init__(self, message: str, status: int = 0):
        super().__init__(message)
        self.status = status


async def initialize() -> str:
    global _session_id

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.post(
            MCP_URL,
            json={
                "jsonrpc": "2.0",
                "id":      str(uuid.uuid4()),
                "method":  "initialize",
                "params":  {
                    "protocolVersion": "2024-11-05",
                    "capabilities":    {},
                    "clientInfo":      {"name": "kapruka-agent", "version": "1.0.0"},
                },
            },
            headers={
                "Content-Type": "application/json",
                "Accept":       "application/json, text/event-stream",
            },
        )

    if response.status_code != 200:
        raise McpError(f"Initialize failed: HTTP {response.status_code}: {response.text[:300]}")

    session_id = (
        response.headers.get("mcp-session-id") or
        response.headers.get("x-session-id")
    )
    if not session_id:
        raise McpError(f"No session ID in headers: {dict(response.headers)}")

    _session_id = session_id
    log.info(f"MCP session initialized: {_session_id}")
    return _session_id


async def get_session_id() -> str:
    if _session_id is None:
        await initialize()
    return _session_id


async def mcp_fetch(tool_name: str, params: dict) -> dict:
    allowed, retry_after_ms = consume_request()
    if not allowed:
        raise RateLimitError(
            f"Rate limit exceeded. Retry after {retry_after_ms // 1000}s",
            retry_after_ms,
        )

    session_id = await get_session_id()

    payload = {
        "jsonrpc": "2.0",
        "id":      str(uuid.uuid4()),
        "method":  "tools/call",
        "params":  {
            "name":      tool_name,
            "arguments": params,
        },
    }

    log.debug(f"→ {tool_name} | params={params}")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.post(
            MCP_URL,
            json=payload,
            headers={
                "Content-Type":   "application/json",
                "Accept":         "application/json, text/event-stream",
                "mcp-session-id": session_id,
            },
        )

    log.debug(f"← {tool_name} | status={response.status_code}")

    # Session expired — reinitialize and retry once
    if response.status_code in (401, 403) or "Missing session ID" in response.text:
        log.warning("Session expired, reinitializing...")
        global _session_id
        _session_id = None
        return await mcp_fetch(tool_name, params)

    if response.status_code != 200:
        raise McpError(f"HTTP {response.status_code}: {response.text[:300]}", response.status_code)

    content_type = response.headers.get("content-type", "")
    body = _parse_sse(response.text) if "text/event-stream" in content_type else response.json()

    if "error" in body:
        err = body["error"]
        raise McpError(f"MCP error [{err.get('code')}]: {err.get('message')}")

    result = body.get("result", body)

    # Tool returned an error (isError: True) — raise with the message text
    if isinstance(result, dict) and result.get("isError"):
        content = result.get("content", [])
        msg = content[0].get("text", "Unknown tool error") if content else "Unknown tool error"
        raise McpError(f"Tool error — {tool_name}: {msg}")

    # Unwrap content[0].text → JSON
    content = result.get("content", []) if isinstance(result, dict) else []
    if content and content[0].get("type") == "text":
        text = content[0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Text is not JSON — return as-is in a dict
            return {"text": text}

    return result


def _parse_sse(text: str) -> dict:
    for line in text.splitlines():
        if line.startswith("data:"):
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    return json.loads(data)
                except json.JSONDecodeError:
                    continue
    raise McpError(f"No parseable data in SSE: {text[:300]}")