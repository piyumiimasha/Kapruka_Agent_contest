import json
import re
from groq import AsyncGroq
from config.settings import settings
from prompts.order_prompt import build_order_prompt
from prompts.episode_summary_prompt import build_episode_summary_prompt
from kapruka_mcp.tools.create_order import create_order
from kapruka_mcp.tools.track_order import track_order
from memory.episodic_memory import record_episode
from utils.logger import get_logger

log = get_logger("OrderAgent")
groq = AsyncGroq(api_key=settings.groq_api_key)

TOOLS = [
    {"type": "function", "function": {
        "name": "kapruka_create_order",
        "description": "Create a guest checkout order on Kapruka. Only call after explicit user confirmation.",
        "parameters": {"type": "object", "required": ["cart", "recipient", "delivery", "sender"], "properties": {
            "cart": {
                "type": "array",
                "items": {"type": "object", "properties": {
                    "product_id": {"type": "string"},
                    "quantity":   {"type": "integer"},
                }},
            },
            "recipient": {
                "type": "object",
                "properties": {
                    "name":    {"type": "string"},
                    "phone":   {"type": "string"},
                    "address": {"type": "string"},
                    "city":    {"type": "string"},
                },
            },
            "delivery": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD format"},
                },
            },
            "sender": {
                "type": "object",
                "properties": {
                    "name":  {"type": "string"},
                    "phone": {"type": "string"},
                },
            },
            "gift_message": {"type": "string"},
            "currency":     {"type": "string", "enum": ["LKR", "USD"]},
        }},
    }},
    {"type": "function", "function": {
        "name": "kapruka_track_order",
        "description": "Track an existing Kapruka order by order number.",
        "parameters": {"type": "object", "required": ["order_number"], "properties": {
            "order_number": {"type": "string"},
        }},
    }},
]


def _safe_parse_json(raw: str) -> dict | None:
    """Parse tool call JSON safely — handles malformed output from gpt-oss-120b."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Fix trailing garbage after last closing brace
    cleaned = raw.strip()
    last_brace = cleaned.rfind("}")
    if last_brace != -1:
        cleaned = cleaned[:last_brace + 1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
    # Fix quoted numbers
    cleaned = re.sub(r'"(\d+)"(\s*[,}])', r'\1\2', raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    log.error(f"Could not parse JSON: {raw[:200]}")
    return None


def _clean_history_for_groq(history: list[dict]) -> list[dict]:
    """
    Remove any function_call fields from history messages.
    gpt-oss-120b rejects messages with function_call=null.
    """
    clean = []
    for msg in history:
        m = {"role": msg["role"], "content": msg.get("content") or ""}
        # Only include tool_calls if present and non-empty
        if msg.get("tool_calls"):
            m["tool_calls"] = msg["tool_calls"]
        clean.append(m)
    return clean


async def _summarize_order(order_args: dict, conversation_history: list[dict]) -> str:
    try:
        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=150,
            messages=[{
                "role": "user",
                "content": build_episode_summary_prompt(order_args, conversation_history),
            }],
        )
        summary = response.choices[0].message.content.strip()
        log.info(f"Order summary: {summary[:80]}")
        return summary
    except Exception as e:
        log.warning(f"Summarization failed: {e}")
        return (
            f"Ordered {len(order_args['cart'])} item(s) for "
            f"{order_args['recipient']['name']} in "
            f"{order_args['recipient']['city']}."
        )


async def run_order_agent(
    user_message: str,
    conversation_history: list[dict],
    memory_context: str,
    session_id: str,
    user_id: str,
    lf_trace=None,
) -> str:
    log.info(f"Order agent invoked: {user_message[:60]}")
    system = build_order_prompt(memory_context)

    # Clean history to avoid function_call=null errors
    clean_history = _clean_history_for_groq(conversation_history)

    messages = [
        *clean_history,
        {"role": "user", "content": user_message},
    ]

    order_args = None
    loop_count = 0
    MAX_LOOPS  = 6

    while loop_count < MAX_LOOPS:
        loop_count += 1

        gen = lf_trace.generation(
            name=f"order-llm-{loop_count}",
            model=settings.groq_orchestrator_model,
            input=messages,
        ) if lf_trace else None

        response = await groq.chat.completions.create(
            model=settings.groq_orchestrator_model,
            max_tokens=settings.groq_max_tokens,
            messages=[{"role": "system", "content": system}, *messages],
            tools=TOOLS,
            tool_choice="auto",
        )

        choice       = response.choices[0]
        assistant_msg = choice.message

        if gen:
            gen.end(
                output=assistant_msg.content or "[tool_call]",
                usage={
                    "input":  response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                },
            )

        # No tool call — conversational response (collecting details or confirmation)
        if choice.finish_reason != "tool_calls":
            log.info("Order agent — conversational response")
            break

        tool_results = []

        for call in assistant_msg.tool_calls:
            args = _safe_parse_json(call.function.arguments)
            if args is None:
                tool_results.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": "Error: could not parse arguments. Please retry.",
                })
                continue

            log.debug(f"Tool call: {call.function.name}")

            tool_span = lf_trace.span(
                name=f"tool-{call.function.name}", metadata={"args": args}
            ) if lf_trace else None

            try:
                if call.function.name == "kapruka_create_order":
                    result     = await create_order(**args)
                    order_args = args
                elif call.function.name == "kapruka_track_order":
                    result = await track_order(args["order_number"])
                else:
                    raise ValueError(f"Unknown tool: {call.function.name}")

                if tool_span:
                    tool_span.end(metadata={"success": True})

            except Exception as e:
                log.error(f"Tool failed: {call.function.name}: {e}")
                if tool_span:
                    tool_span.end(metadata={"error": str(e)})
                tool_results.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps({"error": str(e)}),
                })
                continue

            tool_results.append({
                "role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result, default=str),
            })

        # Build assistant payload without function_call=null
        assistant_payload = {
            "role":    "assistant",
            "content": assistant_msg.content or "",
        }
        if assistant_msg.tool_calls:
            assistant_payload["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {
                    "name": c.function.name, "arguments": c.function.arguments,
                }}
                for c in assistant_msg.tool_calls
            ]

        messages.append(assistant_payload)
        messages.extend(tool_results)

    reply = response.choices[0].message.content or "I'm ready to help place your order."

    # Save episode after successful order
    if order_args and user_id:
        summary = await _summarize_order(order_args, conversation_history)
        await record_episode(
            user_id, summary,
            metadata={
                "city":         order_args["recipient"]["city"],
                "date":         order_args["delivery"]["date"],
                "recipient":    order_args["recipient"]["name"],
                "item_count":   len(order_args["cart"]),
                "gift_message": order_args.get("gift_message", ""),
                "currency":     order_args.get("currency", "LKR"),
                "outcome":      "order_placed",
            },
        )

    log.info("Order agent done")
    return reply