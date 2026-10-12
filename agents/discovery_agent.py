import json

from groq import AsyncGroq

from config.settings import settings
from prompts.discovery_prompts import build_discovery_prompt

from kapruka_mcp.tools.search_products import search_products
from kapruka_mcp.tools.get_product import get_product
from kapruka_mcp.tools.list_categories import list_categories

from utils.logger import get_logger


log = get_logger("DiscoveryAgent")

groq = AsyncGroq(
    api_key=settings.groq_api_key
)


# ============================================================
# GROQ TOOLS
# ============================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "kapruka_search_products",
            "description": (
                "Search the Kapruka product catalog by keyword, "
                "category, price range, stock status, and sorting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "q": {
                        "type": "string"
                    },
                    "category": {
                        "type": "string"
                    },
                    "min_price": {
                        "type": "number"
                    },
                    "max_price": {
                        "type": "number"
                    },
                    "in_stock_only": {
                        "type": "boolean"
                    },
                    "sort": {
                        "type": "string",
                        "enum": [
                            "relevance",
                            "price_asc",
                            "price_desc",
                        ],
                    },
                    "limit": {
                        "type": "integer"
                    },
                    "cursor": {
                        "type": "string"
                    },
                    "currency": {
                        "type": "string",
                        "enum": [
                            "LKR",
                            "USD",
                        ],
                    },
                },
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "kapruka_get_product",
            "description": (
                "Get full details for a Kapruka product by product ID. "
                "Use this when product images, variants, stock, "
                "or detailed product information are required."
            ),
            "parameters": {
                "type": "object",
                "required": [
                    "product_id"
                ],
                "properties": {
                    "product_id": {
                        "type": "string"
                    },
                    "currency": {
                        "type": "string",
                        "enum": [
                            "LKR",
                            "USD",
                        ],
                    },
                },
            },
        },
    },

    {
        "type": "function",
        "function": {
            "name": "kapruka_list_categories",
            "description": (
                "List all Kapruka top-level categories."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# ============================================================
# TOOL DISPATCH
# ============================================================

async def _dispatch(
    name: str,
    args: dict,
) -> dict:

    if name == "kapruka_search_products":
        return await search_products(**args)

    if name == "kapruka_get_product":
        return await get_product(**args)

    if name == "kapruka_list_categories":
        return await list_categories()

    raise ValueError(
        f"Unknown tool: {name}"
    )


# ============================================================
# DISCOVERY AGENT
# ============================================================

async def run_discovery_agent(
    user_message: str,
    conversation_history: list[dict],
    memory_context: str,
    lf_trace=None,
) -> str:

    log.info(
        f"Discovery agent invoked: "
        f"{user_message[:60]}"
    )

    system = build_discovery_prompt(
        memory_context
    )

    messages = [
        *conversation_history,
        {
            "role": "user",
            "content": user_message,
        },
    ]

    # --------------------------------------------------------
    # Safety limit.
    #
    # Prevent the LLM from repeatedly calling the same
    # search tool forever.
    # --------------------------------------------------------

    MAX_TOOL_LOOPS = 5

    loop_count = 0

    # --------------------------------------------------------
    # Keep structured MCP product results.
    #
    # We will use this later to send product images,
    # product IDs, prices, etc. to the frontend.
    # --------------------------------------------------------

    collected_products = []

    while loop_count < MAX_TOOL_LOOPS:

        loop_count += 1

        log.debug(
            f"Discovery LLM loop {loop_count}/{MAX_TOOL_LOOPS}"
        )

        gen = (
            lf_trace.generation(
                name=f"discovery-llm-{loop_count}",
                model=settings.groq_agent_model,
                input=messages,
            )
            if lf_trace
            else None
        )

        # ----------------------------------------------------
        # Ask Groq
        # ----------------------------------------------------

        response = await groq.chat.completions.create(
            model=settings.groq_agent_model,
            max_tokens=settings.groq_max_tokens,
            messages=[
                {
                    "role": "system",
                    "content": system,
                },
                *messages,
            ],
            tools=TOOLS,
            tool_choice="auto",
        )

        assistant_msg = response.choices[0].message

        if gen:

            gen.end(
                output=(
                    assistant_msg.content
                    or "[tool_call]"
                ),
                usage={
                    "input": response.usage.prompt_tokens,
                    "output": response.usage.completion_tokens,
                },
            )

        # ----------------------------------------------------
        # No more tool calls.
        #
        # This is the normal completion path.
        # ----------------------------------------------------

        if response.choices[0].finish_reason != "tool_calls":

            log.info(
                "Discovery agent finished normally"
            )

            break

        # ----------------------------------------------------
        # Process tool calls
        # ----------------------------------------------------

        tool_results = []

        for call in assistant_msg.tool_calls:

            # -----------------------------------------------
            # Parse tool arguments safely
            # -----------------------------------------------

            try:

                args = json.loads(
                    call.function.arguments
                )

            except json.JSONDecodeError as e:

                log.error(
                    "Invalid JSON generated by Groq "
                    f"for {call.function.name}: "
                    f"{call.function.arguments}"
                )

                # Tell the model that its previous tool
                # arguments were invalid.
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": (
                            "Invalid JSON arguments. "
                            "Do not call this tool again "
                            "with malformed JSON."
                        ),
                    }
                )

                continue

            log.debug(
                f"Tool call: "
                f"{call.function.name} | {args}"
            )

            # -----------------------------------------------
            # Trace tool call
            # -----------------------------------------------

            tool_span = (
                lf_trace.span(
                    name=f"tool-{call.function.name}",
                    metadata={
                        "args": args
                    },
                )
                if lf_trace
                else None
            )

            # -----------------------------------------------
            # Execute MCP tool
            # -----------------------------------------------

            try:

                result = await _dispatch(
                    call.function.name,
                    args,
                )

            except Exception as e:

                log.error(
                    f"Tool failed: "
                    f"{call.function.name}: {e}"
                )

                if tool_span:
                    tool_span.end(
                        metadata={
                            "error": str(e)
                        }
                    )

                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(
                            {
                                "error": str(e)
                            }
                        ),
                    }
                )

                continue

            # -----------------------------------------------
            # Log MCP result
            # -----------------------------------------------

            log.info(
                "MCP RESULT %s:\n%s",
                call.function.name,
                json.dumps(
                    result,
                    indent=2,
                    default=str,
                ),
            )

            if tool_span:

                tool_span.end(
                    metadata={
                        "result_keys": (
                            list(result.keys())
                            if isinstance(
                                result,
                                dict,
                            )
                            else "list"
                        )
                    }
                )

            # -----------------------------------------------
            # Preserve product results.
            #
            # At the moment the MCP search response is
            # mostly text. We keep the complete result so
            # we can extract product IDs and call
            # kapruka_get_product later.
            # -----------------------------------------------

            if (
                call.function.name
                == "kapruka_search_products"
            ):

                if isinstance(result, dict):

                    collected_products.append(
                        {
                            "source": "search",
                            "data": result,
                        }
                    )

            elif (
                call.function.name
                == "kapruka_get_product"
            ):

                if isinstance(result, dict):

                    collected_products.append(
                        {
                            "source": "product",
                            "data": result,
                        }
                    )

            # -----------------------------------------------
            # Return MCP result to Groq
            # -----------------------------------------------

            tool_results.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(
                        result,
                        default=str,
                    ),
                }
            )

        # ----------------------------------------------------
        # IMPORTANT
        #
        # Do NOT use:
        #
        # messages.append(assistant_msg.model_dump())
        #
        # because Groq can include:
        #
        # function_call=None
        #
        # which caused your previous 400 error.
        # ----------------------------------------------------

        assistant_payload = {
            "role": "assistant",
            "content": (
                assistant_msg.content
                or ""
            ),
        }

        if assistant_msg.tool_calls:

            assistant_payload[
                "tool_calls"
            ] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": (
                            call.function.arguments
                        ),
                    },
                }
                for call in assistant_msg.tool_calls
            ]

        messages.append(
            assistant_payload
        )

        messages.extend(
            tool_results
        )

    # ========================================================
    # MAX LOOP SAFETY
    # ========================================================

    if loop_count >= MAX_TOOL_LOOPS:

        log.warning(
            "Discovery agent reached maximum "
            f"tool loops ({MAX_TOOL_LOOPS})"
        )

        # If the last model response contains useful text,
        # use it. Otherwise return a safe response.
        final_reply = (
            response.choices[0].message.content
            or
            "I found some products, but I could not complete "
            "the search. Please try a more specific request."
        )

    else:

        final_reply = (
            response.choices[0].message.content
            or
            "I couldn't find suitable products."
        )

    log.info(
        "Discovery agent done | "
        f"loops={loop_count} | "
        f"collected_results={len(collected_products)}"
    )

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # Keep the function returning STRING for now.
    #
    # We are not changing the orchestrator contract yet.
    # Once the search/get_product flow is verified, we will
    # change the whole chain to return:
    #
    # {
    #     "reply": "...",
    #     "products": [...]
    # }
    #
    # That is when we connect real MCP images to frontend
    # cards.
    # --------------------------------------------------------

    return final_reply