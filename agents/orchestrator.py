"""
Orchestrator - now a thin wrapper around the LangGraph graph.

Routing, history and per-chat state live in the graph (graph/*).
This module keeps the helpers the graph nodes reuse:
  _force_classify, _classify_with_llm, direct_reply, post_turn
"""
import re
import json
from groq import AsyncGroq
from langchain_core.messages import HumanMessage

from config.settings import settings
from graph.context import current_trace
from memory.semantic_memory import (
    update_preferences, add_recipient, add_interest, add_dislike,
)
from memory.short_term import add_turn_and_persist
from prompts.orchestator_prompt import build_orchestrator_prompt
from prompts.memory_extraction_prompt import build_memory_extraction_prompt
from utils.logger import get_logger
from utils.tracer import trace

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
    ) if span else None
    try:
        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=5,
            messages=[
                {"role": "system", "content": (
                    "Classify into one word only - no punctuation, no explanation:\n"
                    "browse | search | product | delivery | order | track | memory | chitchat\n"
                    "Reply with exactly one of those words."
                )},
                {"role": "user", "content": message},
            ],
        )
        result = (response.choices[0].message.content or "").strip().lower()
        result = re.sub(r"[^a-z]", " ", result).split()[0] if result.strip() else ""
        log.info(f"LLM classified intent: '{result}'")
        if generation:
            generation.end(output=result)
        return result
    except Exception as e:
        log.warning(f"LLM intent classification failed: {e}")
        if generation:
            generation.end(output="search")
        return "search"


async def direct_reply(history: list[dict], user_message: str,
                       memory_context: str, lf_trace=None) -> str:
    """Orchestrator's own reply (no tools): greetings, preferences, off-topic."""
    gen = lf_trace.generation(
        name="orchestrator-direct",
        model=settings.groq_orchestrator_model,
        input=[*history, {"role": "user", "content": user_message}],
    ) if lf_trace else None

    response = await groq.chat.completions.create(
        model=settings.groq_orchestrator_model,
        max_tokens=settings.groq_max_tokens,
        messages=[
            {"role": "system", "content": build_orchestrator_prompt(memory_context)},
            *history,
            {"role": "user", "content": user_message},
        ],
    )
    reply = response.choices[0].message.content or ""
    if gen:
        gen.end(output=reply, usage={
            "input": response.usage.prompt_tokens,
            "output": response.usage.completion_tokens,
        })
    return reply or "Sorry, I didn't catch that - could you rephrase?"


async def _extract_and_save_from_llm(user_id: str, user_message: str, agent_reply: str):
    """Extract ONLY permanent profile facts - not session-scoped info like budget."""
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
        raw = (response.choices[0].message.content or "").strip()
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
        for d in extracted.get("dislikes", []):
            await add_dislike(user_id, d)

        log.info(f"Profile updated for {user_id}: {list(extracted.keys())}")
    except Exception as e:
        log.warning(f"Memory extraction failed (non-fatal): {e}")


def _get_user_id_from_session(session_id: str) -> str:
    """session_id = '{user_uuid}_{chat_uuid}' -> the user_uuid part."""
    if len(session_id) > 36 and session_id[36] == "_":
        return session_id[:36]
    return session_id


async def post_turn(session_id: str, user_id: str,
                    user_message: str, reply: str, agent: str):
    """
    Runs AFTER the response is sent (FastAPI BackgroundTasks):
      1. audit/UI log in conversation_logs
      2. permanent-profile extraction (one LLM call, kept off the request path)
    """
    await add_turn_and_persist(session_id, user_id, "user", user_message)
    await add_turn_and_persist(session_id, user_id, "assistant", reply, agent=agent)
    await _extract_and_save_from_llm(user_id, user_message, reply)


async def run_orchestrator(graph, session_id: str, user_message: str) -> dict:
    """
    session_id doubles as the LangGraph thread_id: same chat -> same thread
    -> checkpointer restores that chat's messages. user_id (profile/episodes)
    is derived from it and is shared across all of a user's chats.
    """
    log.info(f"Orchestrator received message session={session_id}")
    user_id = _get_user_id_from_session(session_id)

    lf_trace = trace(
        name="orchestrator",
        session_id=session_id,
        metadata={"message_preview": user_message[:100]},
    )
    lf_trace.update(user_id=user_id)
    token = current_trace.set(lf_trace)

    try:
        out = await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_message)],
                "user_id": user_id,
                "products": [],          # reset per-turn field (state persists!)
            },
            {"configurable": {"thread_id": session_id}},
        )
        reply    = out["messages"][-1].content
        agent    = out.get("agent", "orchestrator")
        products = out.get("products", [])

        lf_trace.update(output=reply, metadata={"agent": agent})
        log.info(f"Reply ready | agent={agent} | products={len(products)}")
        return {"reply": reply, "agent": agent, "products": products}

    except Exception as e:
        lf_trace.update(metadata={"error": str(e)})
        raise
    finally:
        current_trace.reset(token)
