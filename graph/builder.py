from langgraph.graph import StateGraph, START, END

from graph.state import AgentState
from graph import nodes
from utils.intent_classifier import route_intent

# route_intent() returns "discovery" | "delivery" | "order" | "orchestrator"
_ROUTES = {
    "discovery":    "discovery",
    "delivery":     "delivery",
    "order":        "order",
    "orchestrator": "chat",
}


def _route(state: AgentState) -> str:
    return _ROUTES.get(route_intent(state.get("intent") or "search"), "chat")


def build_graph(checkpointer=None):
    g = StateGraph(AgentState)

    g.add_node("load_context", nodes.load_context)
    g.add_node("classify",     nodes.classify)
    g.add_node("discovery",    nodes.discovery)
    g.add_node("delivery",     nodes.delivery)
    g.add_node("order",        nodes.order)
    g.add_node("chat",         nodes.chat)

    g.add_edge(START, "load_context")
    g.add_edge("load_context", "classify")
    g.add_conditional_edges("classify", _route, {
        "discovery": "discovery",
        "delivery":  "delivery",
        "order":     "order",
        "chat":      "chat",
    })
    for n in ("discovery", "delivery", "order", "chat"):
        g.add_edge(n, END)

    return g.compile(checkpointer=checkpointer)
