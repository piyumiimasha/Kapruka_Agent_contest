from collections import defaultdict
from config.settings import settings
from utils.logger import get_logger

log = get_logger("ShortTerm")

_sessions: dict[str, dict] = defaultdict(lambda: {"history": [], "cart": []})


# ── History ─────────────────────────────────────────────────────────────────

def add_turn(session_id: str, role: str, content: str, agent: str = None):
    session = _sessions[session_id]
    session["history"].append({"role": role, "content": content, "agent": agent})
    while len(session["history"]) > settings.max_short_term_turns:
        session["history"].pop(0)
    log.debug(f"Turn added [{role}] session={session_id} agent={agent}")


def get_history(session_id: str) -> list[dict]:
    return [
        {"role": t["role"], "content": t["content"]}
        for t in _sessions[session_id]["history"]
    ]


def clear_history(session_id: str):
    _sessions[session_id]["history"] = []


# ── Cart ─────────────────────────────────────────────────────────────────────

def add_to_cart(session_id: str, item: dict):
    cart = _sessions[session_id]["cart"]
    existing = next(
        (i for i in cart
         if i["product_id"] == item["product_id"] and i.get("variant_id") == item.get("variant_id")),
        None,
    )
    if existing:
        existing["quantity"] += item.get("quantity", 1)
    else:
        cart.append({**item, "quantity": item.get("quantity", 1)})
    log.debug(f"Cart updated session={session_id}")


def remove_from_cart(session_id: str, product_id: str, variant_id: str = None):
    cart = _sessions[session_id]["cart"]
    _sessions[session_id]["cart"] = [
        i for i in cart
        if not (i["product_id"] == product_id and i.get("variant_id") == variant_id)
    ]


def get_cart(session_id: str) -> list[dict]:
    return _sessions[session_id]["cart"]


def clear_cart(session_id: str):
    _sessions[session_id]["cart"] = []


def format_cart_for_prompt(session_id: str) -> str:
    cart = get_cart(session_id)
    if not cart:
        return "Cart is empty."
    lines = [f"- {i['name']} x{i['quantity']} @ {i['price']}" for i in cart]
    return "Current cart:\n" + "\n".join(lines)
