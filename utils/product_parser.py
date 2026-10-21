import re
from utils.logger import get_logger

log = get_logger("ProductParser")


def extract_products_from_search(result: dict) -> list[dict]:
    """
    Parse kapruka_search_products MCP response.
    Format: **1. Name**\n   ID: `id` · LKR X · stock · shipping\n   [View product](url)
    """
    text = result.get("text", "")
    if not text:
        return []

    products = []
    pattern = re.compile(
        r"\*\*\d+\.\s+(.+?)\*\*\s*\n"
        r"\s+ID:\s+`([^`]+)`\s*·\s*"
        r"(LKR[\s\d,]+)\s*·\s*"
        r"([^·\n]+?)(?:\s*·\s*([^\n]+))?\s*\n"
        r"\s+\[View product\]\(([^)]+)\)",
        re.MULTILINE,
    )
    for m in pattern.finditer(text):
        products.append({
            "id":          m.group(2).strip(),
            "name":        m.group(1).strip(),
            "price":       m.group(3).strip(),
            "stock":       m.group(4).strip(),
            "shipping":    (m.group(5) or "").strip(),
            "product_url": m.group(6).strip(),
            "image_url":   None,
        })

    log.debug(f"Parsed {len(products)} products from search text")
    return products


def extract_single_product(result: dict) -> dict | None:
    """
    Parse kapruka_get_product MCP response.

    Raw format example:
    ## Pink Serenity Pink Red Roses Heart Shaped Flower Arrangement
    **ID**: `flowers00T2203`
    **Price**: LKR 2,500
    **Stock**: In stock (low)
    **Category**: flowers
    **Vendor**: Flowers
    **Weight**: 0 lbs
    **International shipping**: No
    **Delivery**: Island-wide

    The Pink Serenity... [description paragraph]

    **Image**: https://...
    [View on Kapruka](url)
    """
    text = result.get("text", "")
    if not text:
        return None

    product = {}

    # Name — first ## heading
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

    # Category
    m = re.search(r"\*\*Category\*\*:\s*(.+)", text)
    if m:
        product["category"] = m.group(1).strip()

    # Vendor
    m = re.search(r"\*\*Vendor\*\*:\s*(.+)", text)
    if m:
        product["vendor"] = m.group(1).strip()

    # International shipping
    m = re.search(r"\*\*International shipping\*\*:\s*(.+)", text)
    if m:
        product["international_shipping"] = m.group(1).strip()

    # Delivery scope
    m = re.search(r"\*\*Delivery\*\*:\s*(.+)", text)
    if m:
        product["delivery"] = m.group(1).strip()

    # Image URL
    m = re.search(r"\*\*Image\*\*:\s*(https?://\S+)", text)
    if m:
        product["image_url"] = m.group(1).strip()

    # Product URL
    m = re.search(r"\[View on Kapruka\]\((https?://[^)]+)\)", text)
    if m:
        product["product_url"] = m.group(1).strip()

    # Description — paragraph between the metadata block and **Image**
    # Everything after a blank line following **Delivery** and before **Image**
    m = re.search(
        r"\*\*Delivery\*\*:[^\n]*\n+(.+?)\n+\*\*Image\*\*",
        text, re.DOTALL
    )
    if m:
        desc = m.group(1).strip()
        # Remove trailing ellipsis note — MCP truncates descriptions
        product["description"] = desc
        product["description_truncated"] = desc.endswith("...")

    if not product.get("name") and not product.get("id"):
        return None

    return product