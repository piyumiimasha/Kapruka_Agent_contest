from mcp.mcp_client import mcp_fetch

async def search_products(
    q: str = None, category: str = None, min_price: float = None,
    max_price: float = None, in_stock_only: bool = None, sort: str = None,
    limit: int = None, cursor: str = None, currency: str = None,
) -> dict:
    params = {k: v for k, v in {
        "q": q, "category": category, "min_price": min_price,
        "max_price": max_price, "in_stock_only": in_stock_only,
        "sort": sort, "limit": limit, "cursor": cursor, "currency": currency,
    }.items() if v is not None}
    return await mcp_fetch("kapruka_search_products", params)
