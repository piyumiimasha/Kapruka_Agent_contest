from memory.short_term import add_to_cart, remove_from_cart, get_cart, clear_cart
from utils.logger import get_logger

log = get_logger("CartManager")


def add_item(session_id: str, product: dict):
    item = {
        "product_id": product["id"],
        "name":       product["name"],
        "price":      product["price"],
        "variant_id": product.get("selected_variant_id"),
        "quantity":   1,
    }
    add_to_cart(session_id, item)
    log.info(f"Item added: {item['product_id']} session={session_id}")


def remove_item(session_id: str, product_id: str, variant_id: str = None):
    remove_from_cart(session_id, product_id, variant_id)


def view_cart(session_id: str) -> list[dict]:
    return get_cart(session_id)


def empty_cart(session_id: str):
    clear_cart(session_id)
    log.info(f"Cart cleared session={session_id}")


def build_order_cart(session_id: str) -> list[dict]:
    cart = get_cart(session_id)
    if not cart:
        raise ValueError("Cannot place order: cart is empty")
    return [
        {"product_id": i["product_id"], "quantity": i["quantity"],
         **( {"variant_id": i["variant_id"]} if i.get("variant_id") else {})}
        for i in cart
    ]


def get_cart_total(session_id: str) -> float:
    return sum(float(i.get("price", 0)) * i["quantity"] for i in get_cart(session_id))
