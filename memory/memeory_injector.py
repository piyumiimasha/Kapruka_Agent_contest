from memory.episodic_memory import get_relevant_episodes, format_episodes_for_prompt
from db.user_repository import format_profile_for_prompt
from memory.short_term import format_cart_for_prompt
from utils.logger import get_logger

log = get_logger("MemoryInjector")


async def build_memory_context(
    session_id: str,
    user_id: str,
    profile: dict,
    current_query: str,
) -> str:
    episodes = await get_relevant_episodes(user_id, current_query)

    profile_block  = format_profile_for_prompt(profile)
    episode_block  = format_episodes_for_prompt(episodes)
    cart_block     = format_cart_for_prompt(session_id)

    log.debug(f"Memory context built for {user_id} | episodes={len(episodes)}")

    return f"""=== MEMORY CONTEXT ===

{profile_block}

{episode_block}

{cart_block}

=== END MEMORY CONTEXT ==="""
