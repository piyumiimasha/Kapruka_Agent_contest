from db.user_repository import (
    find_or_create_user,
    get_profile,
    upsert_profile,
    append_to_profile_array,
    format_profile_for_prompt,
)
from utils.logger import get_logger

log = get_logger("SemanticMemory")


async def load_user_context(session_id: str) -> tuple[dict, dict]:
    user = await find_or_create_user(session_id)
    profile = await get_profile(str(user["id"]))
    log.debug(f"Loaded context for user {user['id']}")
    return user, profile


async def update_preferences(user_id: str, updates: dict):
    await upsert_profile(user_id, updates)


async def add_recipient(user_id: str, name: str):
    await append_to_profile_array(user_id, "past_recipients", name)


async def add_interest(user_id: str, interest: str):
    await append_to_profile_array(user_id, "interests", interest)


async def add_dislike(user_id: str, dislike: str):
    await append_to_profile_array(user_id, "dislikes", dislike)


__all__ = [
    "load_user_context",
    "update_preferences",
    "add_recipient",
    "add_interest",
    "add_dislike",
    "format_profile_for_prompt",
]
