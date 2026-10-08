from db.user_repository import (
    get_auth_user,
    get_profile,
    upsert_profile,
    append_to_profile_array,
    format_profile_for_prompt,
)
from utils.logger import get_logger

log = get_logger("SemanticMemory")


async def load_user_context(user_id: str) -> tuple[dict, dict]:
    """
    Load the authenticated user's context.

    user_id is the ID from auth_users.id.
    There is no users table anymore.
    """

    user = await get_auth_user(user_id)

    if not user:
        raise ValueError(
            f"Authenticated user not found: {user_id}"
        )

    profile = await get_profile(user_id)

    log.debug(
        f"Loaded context for user {user_id}"
    )

    return user, profile


async def update_preferences(user_id: str, updates: dict):
    await upsert_profile(user_id, updates)


async def add_recipient(user_id: str, name: str):
    await append_to_profile_array(
        user_id,
        "past_recipients",
        name,
    )


async def add_interest(user_id: str, interest: str):
    await append_to_profile_array(
        user_id,
        "interests",
        interest,
    )


async def add_dislike(user_id: str, dislike: str):
    await append_to_profile_array(
        user_id,
        "dislikes",
        dislike,
    )


__all__ = [
    "load_user_context",
    "update_preferences",
    "add_recipient",
    "add_interest",
    "add_dislike",
    "format_profile_for_prompt",
]