import json
from groq import AsyncGroq
from config.settings import settings
from prompts.discovery_prompts import build_discovery_prompt
from kapruka_mcp.tools.search_products import search_products
from kapruka_mcp.tools.get_product import get_product
from kapruka_mcp.tools.list_categories import list_categories
from utils.product_parser import extract_products_from_search, extract_single_product
from utils.logger import get_logger

log = get_logger("DiscoveryAgent")
groq = AsyncGroq(api_key=settings.groq_api_key)

TOOLS = [
    {"type": "function", "function": {
        "name": "kapruka_search_products",
        "description": "Search the Kapruka product catalog by keyword, category, price range, stock status.",
        "parameters": {"type": "object", "properties": {
            "q":             {"type": "string"},
            "category":      {"type": "string"},
            "min_price":     {"type": "number"},
            "max_price":     {"type": "number"},
            "in_stock_only": {"type": "boolean"},
            "sort":          {"type": "string", "enum": ["relevance", "price_asc", "price_desc"]},
            "limit":         {"type": "integer"},
            "cursor":        {"type": "string"},
            "currency":      {"type": "string", "enum": ["LKR", "USD"]},
        }},
    }},
    {"type": "function", "function": {
        "name": "kapruka_list_categories",
        "description": "List all Kapruka top-level categories.",
        "parameters": {"type": "object", "properties": {}},
    }},
]


async def _dispatch(name: str, args: dict) -> dict:
    if name == "kapruka_search_products":
        return await search_products(**args)
    if name == "kapruka_list_categories":
        return await list_categories()
    raise ValueError(f"Unknown tool: {name}")


async def _fetch_images_for_products(products: list[dict]) -> list[dict]:
    """
    Fetch full product details (including images) for top 3 products.
    Done in code — not left to the LLM to decide.
    """
    enriched = []
    for p in products[:3]:
        pid = p.get("id")
        if not pid:
            enriched.append(p)
            continue
        try:
            result  = await get_product(product_id=pid, currency="LKR")
            details = extract_single_product(result)
            if details:
                # Merge: keep search data, add image_url and product_url from details
                merged = {**p, **{k: v for k, v in details.items() if v}}
                enriched.append(merged)
                log.debug(f"Enriched {p.get('name')} with image: {bool(details.get('image_url'))}")
            else:
                enriched.append(p)
        except Exception as e:
            log.warning(f"Could not fetch image for {pid}: {e}")
            enriched.append(p)

    # Add remaining products without images
    enriched.extend(products[3:])
    return enriched


async def run_discovery_agent(
    user_message: str,
    conversation_history: list[dict],
    memory_context: str,
    lf_trace=None,
) -> dict:
    """
    Returns:
        {"reply": str, "products": list[dict]}
    """
    log.info(f"Discovery agent invoked: {user_message[:60]}")
    system   = build_discovery_prompt(memory_context)
    messages = [*conversation_history, {"role": "user", "content": user_message}]

    MAX_TOOL_LOOPS = 5
    loop_count     = 0
    collected_products: list[dict] = []

    while loop_count < MAX_TOOL_LOOPS:
        loop_count += 1

        gen = lf_trace.generation(
            name=f"discovery-llm-{loop_count}",
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

        assistant_msg = response.choices[0].message

        if gen:
            gen.end(
                output=assistant_msg.content or "[tool_call]",
                usage={"input": response.usage.prompt_tokens,
                       "output": response.usage.completion_tokens},
            )

        if response.choices[0].finish_reason != "tool_calls":
            log.info("Discovery agent finished normally")
            break

        tool_results = []

        for call in assistant_msg.tool_calls:
            try:
                args = json.loads(call.function.arguments)
            except json.JSONDecodeError:
                log.error(f"Invalid JSON for {call.function.name}")
                tool_results.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": "Invalid JSON arguments.",
                })
                continue

            log.debug(f"Tool call: {call.function.name} | {args}")

            tool_span = lf_trace.span(
                name=f"tool-{call.function.name}", metadata={"args": args}
            ) if lf_trace else None

            try:
                result = await _dispatch(call.function.name, args)
            except Exception as e:
                log.error(f"Tool failed: {call.function.name}: {e}")
                if tool_span:
                    tool_span.end(metadata={"error": str(e)})
                tool_results.append({
                    "role": "tool", "tool_call_id": call.id,
                    "content": json.dumps({"error": str(e)}),
                })
                continue

            if tool_span:
                tool_span.end(metadata={"result_keys": list(result.keys()) if isinstance(result, dict) else "list"})

            # ── Parse products from search result ────────────────────────
            if call.function.name == "kapruka_search_products":
                parsed = extract_products_from_search(result)
                if parsed:
                    collected_products.extend(parsed)
                    log.info(f"Parsed {len(parsed)} products from search")

            tool_results.append({
                "role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result, default=str),
            })

        # Build assistant payload safely
        assistant_payload = {
            "role": "assistant",
            "content": assistant_msg.content or "",
        }
        if assistant_msg.tool_calls:
            assistant_payload["tool_calls"] = [
                {"id": c.id, "type": "function", "function": {
                    "name": c.function.name,
                    "arguments": c.function.arguments,
                }}
                for c in assistant_msg.tool_calls
            ]

        messages.append(assistant_payload)
        messages.extend(tool_results)

    if loop_count >= MAX_TOOL_LOOPS:
        log.warning(f"Discovery agent hit max loops ({MAX_TOOL_LOOPS})")

    final_reply = (
        response.choices[0].message.content
        or "I couldn't find suitable products. Please try a different search."
    )

    # ── Deduplicate ──────────────────────────────────────────────────────
    seen = set()
    unique_products = []
    for p in collected_products:
        pid = p.get("id") or p.get("name")
        if pid and pid not in seen:
            seen.add(pid)
            unique_products.append(p)

    # ── Fetch images in code — don't rely on LLM ────────────────────────
    if unique_products:
        log.info(f"Fetching images for {min(3, len(unique_products))} products...")
        unique_products = await _fetch_images_for_products(unique_products)

    log.info(f"Discovery done | loops={loop_count} | products={len(unique_products)}")

    return {
        "reply":    final_reply,
        "products": unique_products[:6],
    }