import json
from groq import AsyncGroq
from config.settings import settings
from prompts.order_prompt import build_order_prompt
from kapruka_mcp.tools.create_order import create_order
from kapruka_mcp.tools.track_order import track_order
from memory.episodic_memory import record_episode
from utils.cart_manager import build_order_cart
from utils.logger import get_logger

log = get_logger("OrderAgent")
groq = AsyncGroq(api_key=settings.groq_api_key)

TOOLS = [
    {"type": "function", "function": {
        "name": "kapruka_create_order",
        "description": "Create a guest checkout order. Only call after explicit user confirmation.",
        "parameters": {"type": "object", "required": ["cart", "recipient", "delivery", "sender"], "properties": {
            "cart": {"type": "array", "items": {"type": "object"}},
            "recipient": {"type": "object"},
            "delivery":  {"type": "object"},
            "sender":    {"type": "object"},
            "gift_message": {"type": "string"},
            "currency":     {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "kapruka_track_order",
        "description": "Track an existing Kapruka order by order number",
        "parameters": {"type": "object", "required": ["order_number"], "properties": {
            "order_number": {"type": "string"},
        }},
    }},
]


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

    try:
        cart_payload = build_order_cart(session_id)
    except ValueError:
        cart_payload = []

    messages = [
        *conversation_history,
        {"role": "user", "content": f"{user_message}\n\n[Current cart: {json.dumps(cart_payload)}]"},
    ]

    order_args = None
    loop_count = 0

    while True:
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

        if gen:
            gen.end(
                output=response.choices[0].message.content or "[tool_call]",
                usage={"input": response.usage.prompt_tokens, "output": response.usage.completion_tokens},
            )

        if response.choices[0].finish_reason != "tool_calls":
            break

        assistant_msg = response.choices[0].message
        tool_results = []
        for call in assistant_msg.tool_calls:
            args = json.loads(call.function.arguments)
            log.debug(f"Tool call: {call.function.name}")

            tool_span = lf_trace.span(
                name=f"tool-{call.function.name}",
                metadata={"args": args},
            ) if lf_trace else None

            if call.function.name == "kapruka_create_order":
                result = await create_order(**args)
                order_args = args
            elif call.function.name == "kapruka_track_order":
                result = await track_order(args["order_number"])
            else:
                raise ValueError(f"Unknown tool: {call.function.name}")

            if tool_span:
                tool_span.end(metadata={"success": True})

            tool_results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })

        messages.append(assistant_msg.model_dump())
        messages.extend(tool_results)

    # Save episode after successful order
    if order_args and user_id:
        summary = (
            f"Ordered {len(order_args['cart'])} item(s) for "
            f"{order_args['recipient']['name']} in "
            f"{order_args['recipient']['city']} on {order_args['delivery']['date']}."
        )
        await record_episode(user_id, summary, {
            "city":      order_args["recipient"]["city"],
            "date":      order_args["delivery"]["date"],
            "recipient": order_args["recipient"]["name"],
            "outcome":   "order_placed",
        })

    log.info("Order agent done")
    return response.choices[0].message.content