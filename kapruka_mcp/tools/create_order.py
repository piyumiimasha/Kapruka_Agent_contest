from kapruka_mcp.mcp_client import mcp_fetch, RateLimitError
from kapruka_mcp.rate_limiter import consume_create_order

async def create_order(
    cart: list, recipient: dict, delivery: dict,
    sender: dict, gift_message: str = None, currency: str = None,
) -> dict:
    allowed, retry_after_ms = consume_create_order()
    if not allowed:
        raise RateLimitError(
            f"Order creation rate limit reached. Retry after {retry_after_ms // 1000}s",
            retry_after_ms,
        )
    params = {"cart": cart, "recipient": recipient, "delivery": delivery, "sender": sender}
    if gift_message:
        params["gift_message"] = gift_message
    if currency:
        params["currency"] = currency
    return await mcp_fetch("kapruka_create_order", {"params": params})