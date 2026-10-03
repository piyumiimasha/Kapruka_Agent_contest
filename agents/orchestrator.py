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


async def _classify_with_llm(message: str, span) -> str:
    generation = span.generation(
        name="intent-classification",
        model=settings.groq_agent_model,
        input=message,
    )
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
    result = response.choices[0].message.content.strip().lower()
    generation.end(output=result)
    return result


async def _extract_and_save_from_llm(user_id: str, user_message: str, agent_reply: str):
    """
    Use LLM to proactively extract profile info from every conversation turn.
    Runs after every reply — non-blocking, errors are swallowed.
    """
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

        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        extracted = json.loads(raw)
        if not extracted:
            return

        log.debug(f"Memory extracted: {extracted}")

        # Save each field
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

        for recipient in extracted.get("past_recipients", []):
            await add_recipient(user_id, recipient)

        for interest in extracted.get("interests", []):
            await add_interest(user_id, interest)

        from memory.semantic_memory import add_dislike
        for dislike in extracted.get("dislikes", []):
            await add_dislike(user_id, dislike)

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
        # 1. Load user context (semantic memory)
        user, profile = await load_user_context(session_id)
        user_id = str(user["id"])
        lf_trace.update(user_id=user_id)

        # 2. Build memory context
        memory_span = lf_trace.span(name="build-memory-context")
        memory_context = await build_memory_context(session_id, user_id, profile, user_message)
        memory_span.end()

        # 3. Get history — load from DB if in-memory is empty (new server start)
        history = get_history(session_id)
        if not history:
            history = await load_history_from_db(session_id)
            # Repopulate in-memory store
            for turn in history:
                add_turn(session_id, turn["role"], turn["content"])
            log.debug(f"Loaded {len(history)} turns from DB for {session_id}")

        # 4. Classify intent
        intent_span = lf_trace.span(name="classify-intent")
        intent, confident = classify_intent(user_message)
        if not confident:
            intent = await _classify_with_llm(user_message, lf_trace)
        intent_span.end(metadata={"intent": intent, "confident": confident})
        log.info(f"Intent: {intent}")

        # 5. Route to sub-agent
        target = route_intent(intent)
        agent_span = lf_trace.span(
            name=f"agent-{target}",
            metadata={"agent": target, "intent": intent},
        )

        if target == "discovery":
            reply = await run_discovery_agent(user_message, history, memory_context, lf_trace)
        elif target == "delivery":
            reply = await run_delivery_agent(user_message, history, memory_context, lf_trace)
        elif target == "order":
            reply = await run_order_agent(user_message, history, memory_context, session_id, user_id, lf_trace)
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
            gen.end(
                output=reply,
                usage={
                    "input": response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                },
            )

        agent_span.end()

        # 6. Persist both turns to DB + in-memory
        await add_turn_and_persist(session_id, user_id, "user",      user_message)
        await add_turn_and_persist(session_id, user_id, "assistant",  reply, agent=target)

        # 7. Proactively extract and save profile info from this turn
        await _extract_and_save_from_llm(user_id, user_message, reply)

        lf_trace.update(output=reply, metadata={"agent": target})
        log.info(f"Reply ready | agent={target}")
        return {"reply": reply, "agent": target}

    except Exception as e:
        lf_trace.update(metadata={"error": str(e)})
        raise