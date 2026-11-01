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
    (INTENT_ORDER,    [r"place.*order", r"confirm.*order", r"checkout", r"buy.*now",
                       r"purchase", r"pay", r"yes.*order", r"go ahead", r"i want to order",
                       r"proceed", r"confirm"]),
    (INTENT_DELIVERY, [r"^can you deliver", r"^do you deliver", r"^is delivery available",
                       r"delivery available", r"deliver to my"]),
    (INTENT_PRODUCT,  [r"tell me more", r"more details", r"more about", r"product id",
                       r"show me that", r"more info"]),
    (INTENT_SEARCH,   [r"find", r"search", r"look.*for", r"show me", r"under \d+",
                       r"below \d+", r"less than \d+", r"gift.*for", r"want.*to.*buy",
                       r"need.*a", r"i need", r"looking for", r"cake", r"flower",
                       r"chocolate", r"vanilla", r"fruit", r"gift"]),
    (INTENT_BROWSE,   [r"browse", r"categories", r"what.*have", r"what.*sell", r"what.*offer"]),
    (INTENT_MEMORY,   [r"i prefer", r"i like", r"i love", r"i don.t like", r"i hate",
                       r"my.*city", r"my.*budget", r"remember"]),
    (INTENT_CHITCHAT, [r"^hi$", r"^hello$", r"^hey$", r"^thanks$", r"^thank you$",
                       r"^bye$", r"^ok$", r"^okay$"]),
]

# These patterns mean the user is in the MIDDLE of an order conversation
# giving delivery/recipient details — should stay in order agent
_ORDER_CONTEXT_PATTERNS = [
    r"recipient",
    r"sender",
    r"deliver.*to",
    r"delivery.*date",
    r"gift.*message",
    r"\d{10}",          # phone number
    r"\d{2,3}/\d",      # address like 23/5
    r"within \d+ days",
    r"tomorrow",
    r"next week",
    r"\d{4}-\d{2}-\d{2}",  # date format
]


def _is_order_context(message: str) -> bool:
    """
    Detect if message looks like the user is providing order details
    (recipient info, delivery date, address etc) mid-checkout.
    """
    msg = message.lower()
    matches = sum(1 for p in _ORDER_CONTEXT_PATTERNS if re.search(p, msg))
    return matches >= 2  # at least 2 order-context signals


def classify_intent(message: str) -> tuple[str | None, bool]:
    msg = message.strip().lower()

    # Short messages defer to LLM
    words = msg.split()
    if len(words) <= 2 and not any(
        re.search(p, msg) for _, patterns in _RULES[:4] for p in patterns
    ):
        log.debug(f"Short answer, deferring to LLM: '{msg}'")
        return None, False

    # If message contains multiple order-context signals, keep in order flow
    if _is_order_context(message):
        log.debug(f"Order context detected, routing to order agent")
        return INTENT_ORDER, True

    for intent, patterns in _RULES:
        for p in patterns:
            if re.search(p, msg):
                log.debug(f"Intent matched: {intent} | '{msg}'")
                return intent, True

    log.debug(f"Intent unclear — needs LLM fallback")
    return None, False


def route_intent(intent: str) -> str:
    if intent in (INTENT_BROWSE, INTENT_SEARCH, INTENT_PRODUCT):
        return "discovery"
    if intent == INTENT_DELIVERY:
        return "delivery"
    if intent in (INTENT_ORDER, INTENT_TRACK):
        return "order"
    return "orchestrator"