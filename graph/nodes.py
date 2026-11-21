"""
Graph nodes. Each node wraps an EXISTING function - no agent logic lives here.
"""
from contextlib import contextmanager

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from config.settings import settings
from graph.context import current_trace
from graph.runs import protected
from graph.state import AgentState
from utils.intent_classifier import classify_intent
from utils.logger import get_logger
from memory.semantic_memory import load_user_context
from memory.memory_injector import build_memory_context
from agents.discovery_agent import run_discovery_agent
from agents.delivery_agent import run_delivery_agent
from agents.order_agent import run_order_agent
from agents.orchestrator import _force_classify, _classify_with_llm, direct_reply

log = get_logger("Graph")

VALID_INTENTS = {
    "browse", "search", "product", "delivery",
    "order", "track", "memory", "chitchat",
}


# ── helpers ──────────────────────────────────────────────────────────────────

@contextmanager
def _span(name: str, **meta):
    """Langfuse span around a node. No-op if there is no active trace."""
    lf = current_trace.get()
    span = lf.span(name=name, metadata=meta) if lf else None
    try:
        yield lf
    finally:
        if span:
            span.end()


def _latest_text(state: AgentState) -> str:
    # While a turn runs, the last message is always the new user message.
    return state["messages"][-1].content


def _history(state: AgentState) -> list[dict]:
    """
    Everything BEFORE the newest user message, as plain role/content dicts
    (the format the agents already expect). Tool traffic never enters state,
    so there are no function_call / tool_calls fields to break Groq.
    """
    turns = []
    for m in state["messages"][:-1]:
        if isinstance(m, HumanMessage):
            role = "user"
        elif isinstance(m, AIMessage):
            role = "assistant"
        else:
            continue
        turns.append({"role": role, "content": m.content or ""})
    return turns[-settings.max_short_term_turns:]


def _thread_id(config: RunnableConfig) -> str:
    return config["configurable"]["thread_id"]


def _ai(text: str, agent: str, products: list | None = None) -> AIMessage:
    # The agent and its product cards ride on the message itself, so re-opening an old
    # thread (or forking it) restores exactly what the user saw. additional_kwargs never
    # reach the LLM: _history() passes role/content only.
    return AIMessage(content=text,
                     additional_kwargs={"agent": agent, "products": products or []})


# ── nodes ────────────────────────────────────────────────────────────────────

async def load_context(state: AgentState, config: RunnableConfig):
    """Profile (semantic) + episodes (episodic) + cart -> one memory block."""
    user_id = state["user_id"]
    with _span("build-memory-context"):
        _, profile = await load_user_context(user_id)
        ctx = await build_memory_context(
            _thread_id(config), user_id, profile, _latest_text(state)
        )
    return {"memory_context": ctx}


async def classify(state: AgentState, config: RunnableConfig):
    """Same 3 layers as before: rules -> keyword override -> LLM -> default."""
    text = _latest_text(state)
    with _span("classify-intent") as lf:
        intent, confident = classify_intent(text)
        log.info(f"Rule classifier: intent='{intent}' confident={confident}")

        if not confident or not intent:
            forced = _force_classify(text)
            if forced:
                intent = forced
                log.info(f"Keyword override: intent='{intent}'")
            else:
                intent = await _classify_with_llm(text, lf)
                log.info(f"LLM fallback: intent='{intent}'")

        if intent not in VALID_INTENTS:
            log.warning(f"Unknown intent '{intent}', defaulting to search")
            intent = "search"

    log.info(f"Final intent: {intent}")
    return {"intent": intent}


async def discovery(state: AgentState, config: RunnableConfig):
    with _span("agent-discovery", agent="discovery") as lf:
        result = await run_discovery_agent(
            _latest_text(state), _history(state),
            state.get("memory_context", ""), lf,
        )
    return {
        "messages": [_ai(result["reply"], "discovery", result.get("products", []))],
        "products": result.get("products", []),
        "agent": "discovery",
    }


async def delivery(state: AgentState, config: RunnableConfig):
    with _span("agent-delivery", agent="delivery") as lf:
        reply = await run_delivery_agent(
            _latest_text(state), _history(state),
            state.get("memory_context", ""), lf,
        )
    return {
        "messages": [_ai(reply, "delivery")],
        "products": [],
        "agent": "delivery",
    }


async def order(state: AgentState, config: RunnableConfig):
    # The order agent can place a real order inside its tool loop: refuse "Stop" meanwhile.
    with protected(_thread_id(config)), _span("agent-order", agent="order") as lf:
        reply = await run_order_agent(
            _latest_text(state), _history(state),
            state.get("memory_context", ""),
            _thread_id(config), state["user_id"], lf,
        )
    return {
        "messages": [_ai(reply, "order")],
        "products": [],
        "agent": "order",
    }


async def chat(state: AgentState, config: RunnableConfig):
    """Greetings, preference statements, off-topic: direct reply, no tools."""
    with _span("agent-orchestrator", agent="orchestrator") as lf:
        reply = await direct_reply(
            _history(state), _latest_text(state),
            state.get("memory_context", ""), lf,
        )
    return {
        "messages": [_ai(reply, "orchestrator")],
        "products": [],
        "agent": "orchestrator",
    }
