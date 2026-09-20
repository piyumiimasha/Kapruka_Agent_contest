from kapruka_mcp.mcp_client import mcp_fetch

async def track_order(order_number: str) -> dict:
    return await mcp_fetch("kapruka_track_order", {"params": {"order_number": order_number}})