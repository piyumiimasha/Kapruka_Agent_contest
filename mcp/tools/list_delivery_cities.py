from mcp.mcp_client import mcp_fetch

async def list_delivery_cities(query: str = None, limit: int = None) -> dict:
    params = {k: v for k, v in {"query": query, "limit": limit}.items() if v is not None}
    return await mcp_fetch("kapruka_list_delivery_cities", params)
