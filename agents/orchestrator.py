import re
import json
from groq import AsyncGroq
from config.settings import settings
from utils.intent_classifier import classify_intent, route_intent, INTENT_MEMORY
from utils.logger import get_logger
from utils.tracer import trace
from memory.memory_injector import build_memory_context
from memory.semantic_memory import (
    load_user_context,
    update_preferences,
    add_recipient,
    add_interest,
)
from memory.short_term import (
    add_turn,
    add_turn_and_persist,
    get_history,
    load_history_from_db,
)
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
            {
                "role": "system",
                "content": (
                    "Classify the user message into exactly one of: "
                    "browse, search, product, delivery, order, track, memory, chitchat. "
                    "Reply with only the intent word."
                ),
            },
            {
                "role": "user",
                "content": message,
            },
        ],
    )

    result = response.choices[0].message.content.strip().lower()

    generation.end(output=result)

    return result


async def _extract_and_save_from_llm(
    user_id: str,
    user_message: str,
    agent_reply: str,
):
    """
    Use LLM to proactively extract profile information
    from every conversation turn.

    Runs after every reply.
    Errors are non-fatal.
    """

    try:
        conversation = (
            f"User: {user_message}\n"
            f"Assistant: {agent_reply}"
        )

        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=200,
            messages=[
                {
                    "role": "system",
                    "content": build_memory_extraction_prompt(),
                },
                {
                    "role": "user",
                    "content": conversation,
                },
            ],
        )

        raw = response.choices[0].message.content.strip()

        # Strip markdown fences if present.
        if raw.startswith("```"):
            raw = raw.split("```")[1]

            if raw.startswith("json"):
                raw = raw[4:]

        extracted = json.loads(raw)

        if not extracted:
            return

        log.debug(f"Memory extracted: {extracted}")

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

        log.info(
            f"Profile updated from conversation for {user_id}"
        )

    except Exception as e:
        log.warning(
            f"Memory extraction failed (non-fatal): {e}"
        )


async def run_orchestrator(
    session_id: str,
    user_message: str,
) -> dict:

    log.info(
        f"Orchestrator received message session={session_id}"
    )

    lf_trace = trace(
        name="orchestrator",
        session_id=session_id,
        metadata={
            "message_preview": user_message[:100]
        },
    )

    try:

        # ============================================================
        # 1. LOAD USER CONTEXT
        # ============================================================

        # session_id currently contains auth_users.id.
        user_id = str(session_id)

        user, profile = await load_user_context(user_id)

        lf_trace.update(user_id=user_id)

        # ============================================================
        # 2. BUILD MEMORY CONTEXT
        # ============================================================

        memory_span = lf_trace.span(
            name="build-memory-context"
        )

        memory_context = await build_memory_context(
            session_id,
            user_id,
            profile,
            user_message,
        )

        memory_span.end()

        # ============================================================
        # 3. LOAD CONVERSATION HISTORY
        # ============================================================

        history = get_history(session_id)

        log.info(
            f"========== HISTORY BEFORE DB ==========\n"
            f"session_id: {session_id}\n"
            f"turn_count: {len(history)}\n"
            f"history: {history}\n"
            f"======================================="
        )

        if not history:

            history = await load_history_from_db(
                session_id,
                user_id,
            )

            log.info(
                f"========== HISTORY FROM DB ==========\n"
                f"session_id: {session_id}\n"
                f"turn_count: {len(history)}\n"
                f"history: {history}\n"
                f"====================================="
            )

            # Repopulate in-memory history.
            for turn in history:
                add_turn(
                    session_id,
                    turn["role"],
                    turn["content"],
                )

        log.info(
            f"========== HISTORY SENT TO AGENT ==========\n"
            f"session_id: {session_id}\n"
            f"turn_count: {len(history)}\n"
            f"history: {history}\n"
            f"=========================================="
        )

        # ============================================================
        # 4. CLASSIFY INTENT
        # ============================================================

        intent_span = lf_trace.span(
            name="classify-intent"
        )

        intent, confident = classify_intent(
            user_message
        )

        if not confident:
            intent = await _classify_with_llm(
                user_message,
                lf_trace,
            )

        intent_span.end(
            metadata={
                "intent": intent,
                "confident": confident,
            }
        )

        log.info(
            f"Intent: {intent}"
        )

        # ============================================================
        # 5. ROUTE TO SUB-AGENT
        # ============================================================

        target = route_intent(intent)

        agent_span = lf_trace.span(
            name=f"agent-{target}",
            metadata={
                "agent": target,
                "intent": intent,
            },
        )

        # ------------------------------------------------------------
        # IMPORTANT
        #
        # Product results are optional.
        #
        # Discovery can return:
        #
        # {
        #     "reply": "...",
        #     "products": [...]
        # }
        #
        # Other agents simply return a normal string.
        # ------------------------------------------------------------

        products = []

        # ============================================================
        # DISCOVERY
        # ============================================================

        if target == "discovery":

            discovery_result = await run_discovery_agent(
                user_message,
                history,
                memory_context,
                lf_trace,
            )

            # New structured discovery response.
            if isinstance(discovery_result, dict):

                reply = discovery_result.get(
                    "reply",
                    "",
                )

                products = discovery_result.get(
                    "products",
                    [],
                )

                log.info(
                    "Discovery result | "
                    f"products={len(products)}"
                )

            # Backward compatibility in case discovery still
            # returns a plain string.
            else:

                reply = str(
                    discovery_result
                )

                products = []

        # ============================================================
        # DELIVERY
        # ============================================================

        elif target == "delivery":

            reply = await run_delivery_agent(
                user_message,
                history,
                memory_context,
                lf_trace,
            )

        # ============================================================
        # ORDER
        # ============================================================

        elif target == "order":

            reply = await run_order_agent(
                user_message,
                history,
                memory_context,
                session_id,
                user_id,
                lf_trace,
            )

        # ============================================================
        # DIRECT ORCHESTRATOR
        # ============================================================

        else:

            gen = lf_trace.generation(
                name="orchestrator-direct",
                model=settings.groq_orchestrator_model,
                input=[
                    *history,
                    {
                        "role": "user",
                        "content": user_message,
                    },
                ],
            )

            response = await groq.chat.completions.create(
                model=settings.groq_orchestrator_model,
                max_tokens=settings.groq_max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": build_orchestrator_prompt(
                            memory_context
                        ),
                    },
                    *history,
                    {
                        "role": "user",
                        "content": user_message,
                    },
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

        # ============================================================
        # 6. PERSIST CONVERSATION
        # ============================================================

        await add_turn_and_persist(
            session_id,
            user_id,
            "user",
            user_message,
        )

        await add_turn_and_persist(
            session_id,
            user_id,
            "assistant",
            reply,
            agent=target,
        )

        # ============================================================
        # 7. MEMORY EXTRACTION
        # ============================================================

        await _extract_and_save_from_llm(
            user_id,
            user_message,
            reply,
        )

        # ============================================================
        # 8. TRACE
        # ============================================================

        lf_trace.update(
            output=reply,
            metadata={
                "agent": target,
                "product_count": len(products),
            },
        )

        log.info(
            f"Reply ready | "
            f"agent={target} | "
            f"products={len(products)}"
        )

        # ============================================================
        # 9. FINAL API RESPONSE
        # ============================================================

        return {
            "reply": reply,
            "agent": target,
            "products": products,
        }

    except Exception as e:

        lf_trace.update(
            metadata={
                "error": str(e)
            }
        )

        raise