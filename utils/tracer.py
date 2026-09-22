import os
from config.settings import settings
from utils.logger import get_logger

log = get_logger("Tracer")

# Set env vars before any langfuse import
os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key
os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key
os.environ["LANGFUSE_HOST"]       = settings.langfuse_host

from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry import trace as otel_trace

_initialized = False


def _init():
    global _initialized
    if _initialized:
        return

    # Langfuse v4 receives traces via its OTLP endpoint
    exporter = OTLPSpanExporter(
        endpoint=f"{settings.langfuse_host}/api/public/otel/v1/traces",
        headers={
            "Authorization": f"Bearer {settings.langfuse_public_key}:{settings.langfuse_secret_key}"
        },
    )

    provider = TracerProvider()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    otel_trace.set_tracer_provider(provider)

    _initialized = True
    log.info("Langfuse v4 tracing initialized via OTLP")


def _get_tracer():
    _init()
    return otel_trace.get_tracer("kapruka-agent")


# ── Public wrappers ──────────────────────────────────────────────────────────

class SpanCtx:
    def __init__(self, span, ctx_token=None):
        self._span = span
        self._ctx_token = ctx_token

    def set(self, key: str, value):
        self._span.set_attribute(key, str(value)[:500])

    def end(self, output=None, usage: dict = None, metadata: dict = None):
        if output:
            self._span.set_attribute("output", str(output)[:500])
        if usage:
            if "input"  in usage: self._span.set_attribute("gen_ai.usage.input_tokens",  usage["input"])
            if "output" in usage: self._span.set_attribute("gen_ai.usage.output_tokens", usage["output"])
        if metadata:
            for k, v in metadata.items():
                self._span.set_attribute(f"metadata.{k}", str(v)[:200])
        self._span.end()

    def span(self, name: str, metadata: dict = None) -> "SpanCtx":
        tracer = _get_tracer()
        child = tracer.start_span(name)
        if metadata:
            for k, v in metadata.items():
                child.set_attribute(f"metadata.{k}", str(v)[:200])
        return SpanCtx(child)

    def generation(self, name: str, model: str = None, input=None) -> "SpanCtx":
        tracer = _get_tracer()
        child = tracer.start_span(name)
        child.set_attribute("openinference.span.kind", "LLM")
        if model: child.set_attribute("gen_ai.system", model)
        if input: child.set_attribute("input", str(input)[:500])
        return SpanCtx(child)

    def update(self, output: str = None, user_id: str = None, metadata: dict = None):
        if output:   self._span.set_attribute("output", str(output)[:500])
        if user_id:  self._span.set_attribute("user.id", user_id)
        if metadata:
            for k, v in metadata.items():
                self._span.set_attribute(f"metadata.{k}", str(v)[:200])


def trace(name: str, session_id: str, user_id: str = None, metadata: dict = None) -> SpanCtx:
    tracer = _get_tracer()
    span = tracer.start_span(name)
    span.set_attribute("session.id", session_id)
    span.set_attribute("langfuse.session.id", session_id)
    if user_id:
        span.set_attribute("user.id", user_id)
        span.set_attribute("langfuse.user.id", user_id)
    if metadata:
        for k, v in metadata.items():
            span.set_attribute(f"metadata.{k}", str(v)[:200])
    return SpanCtx(span)