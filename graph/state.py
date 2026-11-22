from typing import Annotated, TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Persisted per thread_id by the checkpointer (= this chat's history)
    messages: Annotated[list, add_messages]

    # Supplied on every call
    user_id: str

    # Recomputed every turn. Because state persists between turns, anything
    # per-turn MUST be reset or overwritten each call (see run_orchestrator).
    memory_context: str
    intent: str
    agent: str
    products: list
