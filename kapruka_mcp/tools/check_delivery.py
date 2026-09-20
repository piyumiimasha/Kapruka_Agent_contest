from kapruka_mcp.mcp_client import mcp_fetch

async def check_delivery(city: str, delivery_date: str, product_id: str = None) -> dict:
    params = {"city": city, "delivery_date": delivery_date}
    if product_id:
        params["product_id"] = product_id
    return await mcp_fetch("kapruka_check_delivery", {"params": params})