import json
from groq import AsyncGroq
from config.settings import settings
from prompts.discovery_prompts import build_discovery_prompt
from kapruka_mcp.tools.search_products import search_products
from kapruka_mcp.tools.get_product import get_product
from kapruka_mcp.tools.list_categories import list_categories
from utils.logger import get_logger

log = get_logger("DiscoveryAgent")
groq = AsyncGroq(api_key=settings.groq_api_key)

TOOLS = [
    {"type": "function", "function": {
        "name": "kapruka_search_products",
        "description": "Search Kapruka product catalog by keyword, category, price range, stock",
        "parameters": {"type": "object", "properties": {
            "q":             {"type": "string"},
            "category":      {"type": "string"},
            "min_price":     {"type": "number"},
            "max_price":     {"type": "number"},
            "in_stock_only": {"type": "boolean"},
            "sort":          {"type": "string", "enum": ["relevance", "price_asc", "price_desc"]},
            "limit":         {"type": "number"},
            "cursor":        {"type": "string"},
            "currency":      {"type": "string", "enum": ["LKR", "USD"]},
        }},
    }},
    {"type": "function", "function": {
        "name": "kapruka_get_product",
        "description": "Get full product details by ID",
        "parameters": {"type": "object", "required": ["product_id"], "properties": {
            "product_id": {"type": "string"},
            "currency":   {"type": "string"},
        }},
    }},
    {"type": "function", "function": {
        "name": "kapruka_list_categories",
        "description": "List all Kapruka top-level categories",
        "parameters": {"type": "object", "properties": {
            "depth": {"type": "number"},
        }},
    }},
]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "kapruka_search_products":
        return await search_products(**args)
    if name == "kapruka_get_product":
        return await get_product(**args)
    if name == "kapruka_list_categories":
        return await list_categories(**args)
    raise ValueError(f"Unknown tool: {name}")


async def run_discovery_agent(
    user_message: str,
    conversation_history: list[dict],
    memory_context: str,
) -> str:
    log.info(f"Discovery agent invoked: {user_message[:60]}")
    system = build_discovery_prompt(memory_context)
    messages = [*conversation_history, {"role": "user", "content": user_message}]

    response = await groq.chat.completions.create(
        model=settings.groq_agent_model,
        max_tokens=settings.groq_max_tokens,
        messages=[{"role": "system", "content": system}, *messages],
        tools=TOOLS,
        tool_choice="auto",
    )

    while response.choices[0].finish_reason == "tool_calls":
        assistant_msg = response.choices[0].message
        tool_results = []
        for call in assistant_msg.tool_calls:
            args = json.loads(call.function.arguments)
            log.debug(f"Tool call: {call.function.name} | {args}")
            result = await _dispatch(call.function.name, args)
            tool_results.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(result),
            })
        messages.append(assistant_msg.model_dump())
        messages.extend(tool_results)
        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=settings.groq_max_tokens,
            messages=[{"role": "system", "content": system}, *messages],
            tools=TOOLS,
            tool_choice="auto",
        )

    log.info("Discovery agent done")
    return response.choices[0].message.content
