from kapruka_mcp.mcp_client import mcp_fetch

async def get_product(product_id: str, currency: str = None) -> dict:
    params = {"product_id": product_id}
    if currency:
        params["currency"] = currency
    return await mcp_fetch("kapruka_get_product", {"params": params})