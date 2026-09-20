import re
from groq import AsyncGroq
from config.settings import settings
from utils.intent_classifier import classify_intent, route_intent, INTENT_MEMORY
from utils.logger import get_logger
from memory.memory_injector import build_memory_context
from memory.semantic_memory import load_user_context, update_preferences, add_recipient, add_interest
from memory.short_term import add_turn, get_history
from prompts.orchestator_prompt import build_orchestrator_prompt
from agents.discovery_agent import run_discovery_agent
from agents.delivery_agent import run_delivery_agent
from agents.order_agent import run_order_agent

log = get_logger("Orchestrator")
groq = AsyncGroq(api_key=settings.groq_api_key)


async def _classify_with_llm(message: str) -> str:
    response = await groq.chat.completions.create(
        model=settings.groq_agent_model,
        max_tokens=10,
        messages=[
            {"role": "system", "content": (
                "Classify the user message into exactly one of: "
                "browse, search, product, delivery, order, track, memory, chitchat. "
                "Reply with only the intent word."
            )},
            {"role": "user", "content": message},
        ],
    )
    return response.choices[0].message.content.strip().lower()


async def _extract_and_save_preferences(user_id: str, message: str):
    if m := re.search(r"my (?:city|location) is ([A-Za-z\s]+)", message, re.I):
        await update_preferences(user_id, {"preferred_city": m.group(1).strip()})
    if m := re.search(r"(?:for|send to) ([A-Za-z]+)(?:'s| birthday| anniversary)?", message, re.I):
        await add_recipient(user_id, m.group(1).strip())
    if m := re.search(r"i (?:like|love|prefer) ([A-Za-z\s,]+)", message, re.I):
        await add_interest(user_id, m.group(1).strip())


async def run_orchestrator(session_id: str, user_message: str) -> dict:
    log.info(f"Orchestrator received message session={session_id}")

    # 1. Load user context
    user, profile = await load_user_context(session_id)
    user_id = str(user["id"])

    # 2. Build memory context
    memory_context = await build_memory_context(session_id, user_id, profile, user_message)

    # 3. Short-term history
    history = get_history(session_id)

    # 4. Classify intent
    intent, confident = classify_intent(user_message)
    if not confident:
        intent = await _classify_with_llm(user_message)
    log.info(f"Intent: {intent}")

    # 5. Passive preference extraction
    if intent == INTENT_MEMORY:
        await _extract_and_save_preferences(user_id, user_message)

    # 6. Route to sub-agent
    target = route_intent(intent)

    if target == "discovery":
        reply = await run_discovery_agent(user_message, history, memory_context)
    elif target == "delivery":
        reply = await run_delivery_agent(user_message, history, memory_context)
    elif target == "order":
        reply = await run_order_agent(user_message, history, memory_context, session_id, user_id)
    else:
        # Chitchat / memory / unknown — handle directly
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

    # 7. Persist turns
    add_turn(session_id, "user", user_message)
    add_turn(session_id, "assistant", reply, agent=target)

    log.info(f"Reply ready | agent={target}")
    return {"reply": reply, "agent": target}
