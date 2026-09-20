import re
from utils.logger import get_logger

log = get_logger("IntentClassifier")

INTENT_BROWSE    = "browse"
INTENT_SEARCH    = "search"
INTENT_PRODUCT   = "product"
INTENT_DELIVERY  = "delivery"
INTENT_ORDER     = "order"
INTENT_TRACK     = "track"
INTENT_MEMORY    = "memory"
INTENT_CHITCHAT  = "chitchat"

_RULES = [
    (INTENT_TRACK,    [r"track", r"where is my order", r"order status", r"order number"]),
    (INTENT_ORDER,    [r"place.*order", r"confirm.*order", r"checkout", r"buy.*now", r"purchase", r"pay"]),
    (INTENT_DELIVERY, [r"deliver", r"can.*send.*to", r"ship.*to", r"available in", r"reach"]),
    (INTENT_PRODUCT,  [r"tell me more", r"details", r"more about", r"product id", r"show me that"]),
    (INTENT_SEARCH,   [r"find", r"search", r"look.*for", r"show me", r"under \d+", r"below \d+", r"gift.*for", r"want.*to.*buy"]),
    (INTENT_BROWSE,   [r"browse", r"categories", r"what.*have", r"what.*sell", r"what.*offer"]),
    (INTENT_MEMORY,   [r"i prefer", r"i like", r"i don.t like", r"i hate", r"my.*city", r"my.*budget", r"remember"]),
    (INTENT_CHITCHAT, [r"^hi", r"^hello", r"^hey", r"thanks", r"thank you", r"bye"]),
]


def classify_intent(message: str) -> tuple[str | None, bool]:
    """Returns (intent, confident)"""
    msg = message.strip().lower()
    for intent, patterns in _RULES:
        for p in patterns:
            if re.search(p, msg):
                log.debug(f"Intent matched: {intent}")
                return intent, True
    log.debug("Intent unclear — needs LLM fallback")
    return None, False


def route_intent(intent: str) -> str:
    """Maps intent to agent name"""
    if intent in (INTENT_BROWSE, INTENT_SEARCH, INTENT_PRODUCT):
        return "discovery"
    if intent == INTENT_DELIVERY:
        return "delivery"
    if intent in (INTENT_ORDER, INTENT_TRACK):
        return "order"
    return "orchestrator"
