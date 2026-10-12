import json

from db.database import get_pool


async def get_auth_user(user_id: str):
    """
    Get the authenticated user directly from auth_users.

    user_id must be auth_users.id.
    """

    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, name, created_at
            FROM auth_users
            WHERE id = $1
            """,
            user_id,
        )

    return dict(row) if row else None


async def get_profile(user_id: str):
    """
    Get the profile directly using auth_users.id.
    Always return a dictionary.
    """
    pool = await get_pool()

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT profile
            FROM user_profiles
            WHERE user_id = $1
            """,
            user_id,
        )

    if not row:
        return {}

    profile = row["profile"]

    if profile is None:
        return {}

    if isinstance(profile, str):
        try:
            profile = json.loads(profile)
        except json.JSONDecodeError:
            return {}

    if isinstance(profile, dict):
        return profile

    return {}


async def upsert_profile(user_id: str, updates: dict):
    """
    Create or update the user's profile.

    user_id is auth_users.id.
    """

    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_profiles (
                user_id,
                profile
            )
            VALUES (
                $1,
                $2::jsonb
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                profile =
                    user_profiles.profile ||
                    EXCLUDED.profile,
                updated_at = NOW()
            """,
            user_id,
            json.dumps(updates),
        )


async def ensure_profile(user_id: str):
    """
    Make sure a profile row exists for the authenticated user.
    """

    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_profiles (
                user_id,
                profile
            )
            VALUES ($1, '{}'::jsonb)
            ON CONFLICT (user_id)
            DO NOTHING
            """,
            user_id,
        )


async def append_to_profile_array(
    user_id: str,
    field: str,
    value: str,
):
    """
    Append a value to an array field in the user's JSONB profile.

    user_id is auth_users.id.
    """

    allowed_fields = {
        "past_recipients",
        "interests",
        "dislikes",
    }

    if field not in allowed_fields:
        raise ValueError(f"Invalid profile array field: {field}")

    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_profiles (
                user_id,
                profile
            )
            VALUES (
                $1,
                jsonb_build_object(
                    $2,
                    jsonb_build_array($3)
                )
            )
            ON CONFLICT (user_id)
            DO UPDATE SET
                profile =
                    jsonb_set(
                        user_profiles.profile,
                        ARRAY[$2],
                        COALESCE(
                            user_profiles.profile->$2,
                            '[]'::jsonb
                        ) || jsonb_build_array($3)
                    ),
                updated_at = NOW()
            """,
            user_id,
            field,
            value,
        )


def format_profile_for_prompt(profile: dict) -> str:
    """
    Convert the stored profile into prompt-friendly text.
    """

    if not profile:
        return "No saved user preferences."

    lines = []

    for key, value in profile.items():
        if value in (None, "", [], {}):
            continue

        if isinstance(value, list):
            value = ", ".join(str(item) for item in value)

        readable_key = key.replace("_", " ").title()
        lines.append(f"- {readable_key}: {value}")

    if not lines:
        return "No saved user preferences."

    return "User profile:\n" + "\n".join(lines)