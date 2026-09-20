import json
from groq import AsyncGroq
from config.settings import settings
from prompts.delivery_prompt import build_delivery_prompt
from kapruka_mcp.tools.list_delivery_cities import list_delivery_cities
from kapruka_mcp.tools.check_delivery import check_delivery
from utils.logger import get_logger

log = get_logger("DeliveryAgent")
groq = AsyncGroq(api_key=settings.groq_api_key)

TOOLS = [
    {"type": "function", "function": {
        "name": "kapruka_list_delivery_cities",
        "description": "Search Kapruka delivery cities by name or alias",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "number"},
        }},
    }},
    {"type": "function", "function": {
        "name": "kapruka_check_delivery",
        "description": "Check delivery feasibility to a city on a date",
        "parameters": {"type": "object", "required": ["city", "delivery_date"], "properties": {
            "city":          {"type": "string"},
            "delivery_date": {"type": "string"},
            "product_id":    {"type": "string"},
        }},
    }},
]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "kapruka_list_delivery_cities":
        return await list_delivery_cities(**args)
    if name == "kapruka_check_delivery":
        return await check_delivery(**args)
    raise ValueError(f"Unknown tool: {name}")


async def run_delivery_agent(
    user_message: str,
    conversation_history: list[dict],
    memory_context: str,
    lf_trace=None,
) -> str:
    log.info(f"Delivery agent invoked: {user_message[:60]}")
    system = build_delivery_prompt(memory_context)
    messages = [*conversation_history, {"role": "user", "content": user_message}]

    loop_count = 0
    while True:
        loop_count += 1
        gen = lf_trace.generation(
            name=f"delivery-llm-{loop_count}",
            model=settings.groq_agent_model,
            input=messages,
        ) if lf_trace else None

        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
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
            log.debug(f"Tool call: {call.function.name} | {args}")

            tool_span = lf_trace.span(
                name=f"tool-{call.function.name}",
                metadata={"args": args},
            ) if lf_trace else None

            result = await _dispatch(call.function.name, args)

            if tool_span:
                tool_span.end(metadata={"result_keys": list(result.keys()) if isinstance(result, dict) else "list"})

            tool_results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })
        messages.append(assistant_msg.model_dump())
        messages.extend(tool_results)

    log.info("Delivery agent done")
    return response.choices[0].message.content