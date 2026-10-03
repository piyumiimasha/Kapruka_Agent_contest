from collections import defaultdict
from config.settings import settings
from utils.logger import get_logger

log = get_logger("ShortTerm")

_sessions: dict[str, dict] = defaultdict(lambda: {"history": [], "cart": []})


def add_turn(session_id: str, role: str, content: str, agent: str = None):
    session = _sessions[session_id]
    session["history"].append({"role": role, "content": content, "agent": agent})
    while len(session["history"]) > settings.max_short_term_turns:
        session["history"].pop(0)
    log.debug(f"Turn added [{role}] session={session_id} agent={agent}")


async def add_turn_and_persist(session_id: str, user_id: str, role: str, content: str, agent: str = None):
    """Add to in-memory store AND persist to conversation_logs in Supabase."""
    add_turn(session_id, role, content, agent)
    try:
        from db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE session_id = $1", session_id
            )
            if user_row:
                await conn.execute(
                    """INSERT INTO conversation_logs (user_id, session_id, role, content, agent)
                       VALUES ($1, $2, $3, $4, $5)""",
                    user_row["id"], session_id, role, content, agent,
                )
                log.debug(f"Persisted turn [{role}] to DB for {session_id}")
    except Exception as e:
        log.error(f"Failed to persist turn to DB: {e}")


async def load_history_from_db(session_id: str, limit: int = None) -> list[dict]:
    """Load conversation history from DB on session resume."""
    limit = limit or settings.max_short_term_turns
    try:
        from db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "SELECT id FROM users WHERE session_id = $1", session_id
            )
            if not user_row:
                return []
            rows = await conn.fetch(
                """SELECT role, content FROM conversation_logs
                   WHERE user_id = $1
                   ORDER BY created_at DESC LIMIT $2""",
                user_row["id"], limit,
            )
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    except Exception as e:
        log.error(f"Failed to load history from DB: {e}")
        return []


def get_history(session_id: str) -> list[dict]:
    """Get in-memory history. If empty, caller should load from DB."""
    return [
        {"role": t["role"], "content": t["content"]}
        for t in _sessions[session_id]["history"]
    ]


def clear_history(session_id: str):
    _sessions[session_id]["history"] = []


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


def remove_from_cart(session_id: str, product_id: str, variant_id: str = None):
    _sessions[session_id]["cart"] = [
        i for i in _sessions[session_id]["cart"]
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