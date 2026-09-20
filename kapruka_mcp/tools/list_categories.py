from kapruka_mcp.mcp_client import mcp_fetch

async def list_categories(depth: int = None) -> dict:
    params = {"depth": depth} if depth is not None else {}
    return await mcp_fetch("kapruka_list_categories", params)
