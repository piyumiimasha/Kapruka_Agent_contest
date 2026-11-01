import re
import json
from groq import AsyncGroq
from config.settings import settings
from utils.intent_classifier import classify_intent, route_intent, INTENT_MEMORY
from utils.logger import get_logger
from utils.tracer import trace
from memory.memory_injector import build_memory_context
from memory.semantic_memory import load_user_context, update_preferences, add_recipient, add_interest
from memory.short_term import add_turn, add_turn_and_persist, get_history, load_history_from_db
from prompts.orchestator_prompt import build_orchestrator_prompt
from prompts.memory_extraction_prompt import build_memory_extraction_prompt
from agents.discovery_agent import run_discovery_agent
from agents.delivery_agent import run_delivery_agent
from agents.order_agent import run_order_agent

log = get_logger("Orchestrator")
groq = AsyncGroq(api_key=settings.groq_api_key)

DISCOVERY_KEYWORDS = [
    "cake", "cakes", "chocolate", "flower", "flowers", "gift", "gifts",
    "birthday", "anniversary", "product", "products", "buy", "shop",
    "show me", "find", "search", "looking for", "i need", "i want",
    "under lkr", "below lkr", "less than", "price", "lkr", "rs.",
    "food", "drink", "fruit", "sweets", "candy", "toy", "book",
    "electronics", "gadget", "jewellery", "clothing", "hamper",
    "watch", "perfume", "cosmetic", "plant", "vegetable",
]


def _force_classify(message: str) -> str | None:
    msg = message.lower()
    if any(kw in msg for kw in DISCOVERY_KEYWORDS):
        return "search"
    if any(kw in msg for kw in ["deliver", "delivery", "ship", "city", "send to", "reach"]):
        return "delivery"
    if any(kw in msg for kw in ["place order", "confirm order", "checkout", "pay now"]):
        return "order"
    if any(kw in msg for kw in ["track", "where is my order", "order status", "order number"]):
        return "track"
    return None


async def _classify_with_llm(message: str, span) -> str:
    generation = span.generation(
        name="intent-classification",
        model=settings.groq_agent_model,
        input=message,
    )
    try:
        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=5,
            messages=[
                {"role": "system", "content": (
                    "Classify into one word only — no punctuation, no explanation:\n"
                    "browse | search | product | delivery | order | track | memory | chitchat\n"
                    "Reply with exactly one of those words."
                )},
                {"role": "user", "content": message},
            ],
        )
        result = response.choices[0].message.content.strip().lower()
        result = re.sub(r"[^a-z]", " ", result).split()[0] if result else ""
        log.info(f"LLM classified intent: '{result}'")
        generation.end(output=result)
        return result
    except Exception as e:
        log.warning(f"LLM intent classification failed: {e}")
        generation.end(output="search")
        return "search"


async def _extract_and_save_from_llm(user_id: str, user_message: str, agent_reply: str):
    """Extract ONLY permanent profile facts — not session-scoped info like budget."""
    try:
        conversation = f"User: {user_message}\nAssistant: {agent_reply}"
        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=200,
            messages=[
                {"role": "system", "content": build_memory_extraction_prompt()},
                {"role": "user", "content": conversation},
            ],
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        extracted = json.loads(raw)
        if not extracted:
            return

        updates = {}
        if extracted.get("preferred_city"):
            updates["preferred_city"] = extracted["preferred_city"]
        if extracted.get("about_recipients"):
            updates["about_recipients"] = extracted["about_recipients"]

        if updates:
            await update_preferences(user_id, updates)

        for r in extracted.get("past_recipients", []):
            await add_recipient(user_id, r)
        for i in extracted.get("interests", []):
            await add_interest(user_id, i)
        from memory.semantic_memory import add_dislike
        for d in extracted.get("dislikes", []):
            await add_dislike(user_id, d)

        if extracted:
            log.info(f"Profile updated for {user_id}: {list(extracted.keys())}")
    except Exception as e:
        log.warning(f"Memory extraction failed (non-fatal): {e}")


def _get_user_id_from_session(session_id: str) -> str:
    """
    session_id format: {user_id}_{chat_id}
    Extract the user_id part for profile/episode lookups.
    Falls back to session_id if no underscore pattern found (old format).
    """
    # UUID is 36 chars: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    # session_id = "{36-char-uuid}_{36-char-uuid}"
    if len(session_id) > 36 and session_id[36] == "_":
        return session_id[:36]
    return session_id

_REFINE_RE = re.compile(
    r"\b(budget|under|below|within|less than|up to|cheaper|cheap|other|another|"
    r"different|something else|more options|similar|instead|suggest)\b|\b\d{3,6}\b",
    re.I,
)

def _is_search_refinement(message: str) -> bool:
    return bool(_REFINE_RE.search(message))

async def run_orchestrator(session_id: str, user_message: str) -> dict:
    log.info(f"Orchestrator received message session={session_id}")

    lf_trace = trace(
        name="orchestrator",
        session_id=session_id,
        metadata={"message_preview": user_message[:100]},
    )

    try:
        # Extract stable user_id from composite session_id
        user_id = _get_user_id_from_session(session_id)

        # Load user profile using stable user_id
        user, profile = await load_user_context(user_id)
        lf_trace.update(user_id=user_id)

        memory_span = lf_trace.span(name="build-memory-context")
        memory_context = await build_memory_context(session_id, user_id, profile, user_message)
        memory_span.end()

        # History is scoped to this chat session (session_id includes chat_id)
        history = get_history(session_id)
        if not history:
            history = await load_history_from_db(session_id, user_id)
            for turn in history:
                add_turn(session_id, turn["role"], turn["content"])
            log.debug(f"Loaded {len(history)} turns from DB for {session_id}")

        # Intent classification — 3 layers
        intent_span = lf_trace.span(name="classify-intent")

        intent, confident = classify_intent(user_message)
        log.info(f"Rule classifier: intent='{intent}' confident={confident}")

        if not confident or not intent:
            forced = _force_classify(user_message)
            if forced:
                intent = forced
                confident = True
                log.info(f"Keyword override: intent='{intent}'")

        if not confident or not intent:
            intent = await _classify_with_llm(user_message, lf_trace)
            log.info(f"LLM fallback: intent='{intent}'")

        if not intent or intent not in (
            "browse", "search", "product", "delivery",
            "order", "track", "memory", "chitchat"
        ):
            log.warning(f"Unknown intent '{intent}', defaulting to search")
            intent = "search"

        # Mid-chat refinements ("my budget is 3000", "show me other types")
        # should re-run the search, not get a chat-only reply.
        if intent in ("memory", "chitchat") and history and _is_search_refinement(user_message):
            log.info(f"Refinement override: '{intent}' -> search")
            intent = "search"

        intent_span.end(metadata={"intent": intent, "confident": confident})
        log.info(f"Final intent: {intent}")

        target = route_intent(intent)
        log.info(f"Routing to: {target}")

        agent_span = lf_trace.span(
            name=f"agent-{target}",
            metadata={"agent": target, "intent": intent},
        )

        products = []

        if target == "discovery":
            result   = await run_discovery_agent(user_message, history, memory_context, lf_trace)
            reply    = result["reply"]
            products = result.get("products", [])

        elif target == "delivery":
            reply = await run_delivery_agent(user_message, history, memory_context, lf_trace)

        elif target == "order":
            reply = await run_order_agent(
                user_message, history, memory_context, session_id, user_id, lf_trace
            )

        else:
            gen = lf_trace.generation(
                name="orchestrator-direct",
                model=settings.groq_orchestrator_model,
                input=[*history, {"role": "user", "content": user_message}],
            )
            response = await groq.chat.completions.create(
                model=settings.groq_orchestrator_model,
                max_tokens=settings.groq_max_tokens,
                messages=[
                    {"role": "system", "content": build_orchestrator_prompt(memory_context)},
                    *history,
                    {"role": "user", "content": user_message},
                ],
            )
            reply = response.choices[0].message.content
            gen.end(output=reply, usage={
                "input": response.usage.prompt_tokens,
                "output": response.usage.completion_tokens,
            })

        agent_span.end()

        await add_turn_and_persist(session_id, user_id, "user",      user_message)
        await add_turn_and_persist(session_id, user_id, "assistant",  reply, agent=target)

        # Only save permanent facts — not session budget/preferences
        await _extract_and_save_from_llm(user_id, user_message, reply)

        lf_trace.update(output=reply, metadata={"agent": target})
        log.info(f"Reply ready | agent={target} | products={len(products)}")

        return {"reply": reply, "agent": target, "products": products}

    except Exception as e:
        lf_trace.update(metadata={"error": str(e)})
        raise