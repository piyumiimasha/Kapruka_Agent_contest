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

# ── Keyword override list ────────────────────────────────────────────────────
DISCOVERY_KEYWORDS = [
    "cake", "cakes", "chocolate", "flower", "flowers", "gift", "gifts",
    "birthday", "anniversary", "product", "products", "buy", "shop",
    "show me", "find", "search", "looking for", "i need", "i want",
    "under lkr", "below lkr", "less than", "price", "lkr", "rs.",
    "food", "drink", "fruit", "sweets", "candy", "toy", "book",
    "electronics", "gadget", "jewellery", "clothing", "hamper",
    "watch", "perfume", "cosmetic", "plant", "fruit", "vegetable",
]


def _force_classify(message: str) -> str | None:
    """Keyword-based override — catches what the LLM misses."""
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
        # Strip punctuation and take first word only
        result = re.sub(r"[^a-z]", " ", result).split()[0] if result else ""
        log.info(f"LLM classified intent: '{result}'")
        generation.end(output=result)
        return result
    except Exception as e:
        log.warning(f"LLM intent classification failed: {e}")
        generation.end(output="search")
        return "search"


async def _extract_and_save_from_llm(user_id: str, user_message: str, agent_reply: str):
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
        if extracted.get("budget_min") is not None:
            updates["budget_min"] = extracted["budget_min"]
        if extracted.get("budget_max") is not None:
            updates["budget_max"] = extracted["budget_max"]
        if extracted.get("currency"):
            updates["currency"] = extracted["currency"]

        if updates:
            await update_preferences(user_id, updates)

        for r in extracted.get("past_recipients", []):
            await add_recipient(user_id, r)
        for i in extracted.get("interests", []):
            await add_interest(user_id, i)
        from memory.semantic_memory import add_dislike
        for d in extracted.get("dislikes", []):
            await add_dislike(user_id, d)

        log.info(f"Profile updated from conversation for {user_id}")
    except Exception as e:
        log.warning(f"Memory extraction failed (non-fatal): {e}")


async def run_orchestrator(session_id: str, user_message: str) -> dict:
    log.info(f"Orchestrator received message session={session_id}")

    lf_trace = trace(
        name="orchestrator",
        session_id=session_id,
        metadata={"message_preview": user_message[:100]},
    )

    try:
        # 1. Load user context
        user, profile = await load_user_context(session_id)
        user_id = str(user["id"])
        lf_trace.update(user_id=user_id)

        # 2. Build memory context
        memory_span = lf_trace.span(name="build-memory-context")
        memory_context = await build_memory_context(session_id, user_id, profile, user_message)
        memory_span.end()

        # 3. Load history
        history = get_history(session_id)
        if not history:
            history = await load_history_from_db(session_id, user_id)
            for turn in history:
                add_turn(session_id, turn["role"], turn["content"])
            log.debug(f"Loaded {len(history)} turns from DB for {session_id}")

        # 4. Intent classification — 3 layers
        intent_span = lf_trace.span(name="classify-intent")

        # Layer 1: rule-based fast classifier
        intent, confident = classify_intent(user_message)
        log.info(f"Rule classifier: intent='{intent}' confident={confident}")

        # Layer 2: keyword override
        if not confident or not intent:
            forced = _force_classify(user_message)
            if forced:
                intent = forced
                confident = True
                log.info(f"Keyword override: intent='{intent}'")

        # Layer 3: LLM fallback
        if not confident or not intent:
            intent = await _classify_with_llm(user_message, lf_trace)
            log.info(f"LLM fallback: intent='{intent}'")

        # Safety default
        if not intent or intent not in (
            "browse", "search", "product", "delivery",
            "order", "track", "memory", "chitchat"
        ):
            log.warning(f"Unknown intent '{intent}', defaulting to search")
            intent = "search"

        intent_span.end(metadata={"intent": intent, "confident": confident})
        log.info(f"Final intent: {intent}")

        # 5. Route to sub-agent
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

        # 6. Persist turns
        await add_turn_and_persist(session_id, user_id, "user",      user_message)
        await add_turn_and_persist(session_id, user_id, "assistant",  reply, agent=target)

        # 7. Extract and save profile info
        await _extract_and_save_from_llm(user_id, user_message, reply)

        lf_trace.update(output=reply, metadata={"agent": target})
        log.info(f"Reply ready | agent={target} | products={len(products)}")

        return {"reply": reply, "agent": target, "products": products}

    except Exception as e:
        lf_trace.update(metadata={"error": str(e)})
        raise