import re
from utils.logger import get_logger

log = get_logger("ProductParser")


def extract_products_from_search(result: dict) -> list[dict]:
    """
    Parse kapruka_search_products MCP response.

    Format per product:
    **1. Product Name**
       ID: `CAKE00KA002222` · LKR 2,610 · In stock (low) · ships internationally
       [View product](https://www.kapruka.com/...)
    """
    text = result.get("text", "")
    if not text:
        return []

    products = []

    # Match each numbered product block
    # **1. Name**\n   ID: `...` · LKR ... · stock · ...\n   [View product](url)
    pattern = re.compile(
        r"\*\*\d+\.\s+(.+?)\*\*\s*\n"          # **1. Product Name**
        r"\s+ID:\s+`([^`]+)`\s*·\s*"            # ID: `CAKE00KA002222` ·
        r"(LKR[\s\d,]+)\s*·\s*"                 # LKR 2,610 ·
        r"([^·\n]+?)(?:\s*·\s*([^\n]+))?\s*\n"  # In stock (low) · ships internationally
        r"\s+\[View product\]\(([^)]+)\)",       # [View product](url)
        re.MULTILINE,
    )

    for m in pattern.finditer(text):
        name       = m.group(1).strip()
        product_id = m.group(2).strip()
        price      = m.group(3).strip()
        stock      = m.group(4).strip()
        shipping   = (m.group(5) or "").strip()
        url        = m.group(6).strip()

        products.append({
            "id":          product_id,
            "name":        name,
            "price":       price,
            "stock":       stock,
            "shipping":    shipping,
            "product_url": url,
            "image_url":   None,  # not in search — populated by get_product
        })

    log.debug(f"Parsed {len(products)} products from search text")
    return products


def extract_single_product(result: dict) -> dict | None:
    """
    Parse kapruka_get_product MCP response.

    Format:
    ## Product Name
    **ID**: `ID`
    **Price**: LKR X,XXX
    **Stock**: In stock (high)
    **Image**: https://...
    [View on Kapruka](url)
    """
    text = result.get("text", "")
    if not text:
        return None

    product = {}

    # Name
    m = re.search(r"^##\s+(.+)$", text, re.MULTILINE)
    if m:
        product["name"] = m.group(1).strip()

    # ID
    m = re.search(r"\*\*ID\*\*:\s*`([^`]+)`", text)
    if m:
        product["id"] = m.group(1).strip()

    # Price
    m = re.search(r"\*\*Price\*\*:\s*(LKR[\s\d,]+)", text)
    if m:
        product["price"] = m.group(1).strip()

    # Stock
    m = re.search(r"\*\*Stock\*\*:\s*(.+)", text)
    if m:
        product["stock"] = m.group(1).strip()

    # Image
    m = re.search(r"\*\*Image\*\*:\s*(https?://\S+)", text)
    if m:
        product["image_url"] = m.group(1).strip()

    # Product URL
    m = re.search(r"\[View on Kapruka\]\((https?://[^)]+)\)", text)
    if m:
        product["product_url"] = m.group(1).strip()

    # Description snippet
    m = re.search(r"\*\*Delivery\*\*:.+?\n+(.+?)\n+\*\*Image\*\*", text, re.DOTALL)
    if m:
        product["description"] = m.group(1).strip()[:200]

    if not product.get("name") and not product.get("id"):
        return None

    return product