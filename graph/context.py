"""
Carries the Langfuse trace of the current request into graph nodes.

A ContextVar is used instead of putting the trace in the graph config/state,
because config values are copied into checkpoint metadata and state is
persisted - a trace object must never be serialised.
"""
from contextvars import ContextVar

current_trace: ContextVar = ContextVar("current_trace", default=None)
