import json
from typing import Optional
from db.database import get_pool
from db.schema import DEFAULT_PROFILE
from utils.logger import get_logger

log = get_logger("UserRepository")


# ── Users ──────────────────────────────────────────────────────────────────

async def find_or_create_user(session_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE session_id = $1", session_id
        )
        if row:
            return dict(row)
        row = await conn.fetchrow(
            "INSERT INTO users (session_id) VALUES ($1) RETURNING *", session_id
        )
        log.info(f"New user created: {session_id}")
        return dict(row)


# ── Semantic profile ────────────────────────────────────────────────────────

async def get_profile(user_id: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT profile FROM user_profiles WHERE user_id = $1", user_id
        )
        if row:
            return json.loads(row["profile"]) if isinstance(row["profile"], str) else dict(row["profile"])
        return dict(DEFAULT_PROFILE)


async def upsert_profile(user_id: str, updates: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_profiles (user_id, profile)
            VALUES ($1, $2::jsonb)
            ON CONFLICT (user_id)
            DO UPDATE SET
                profile    = user_profiles.profile || $2::jsonb,
                updated_at = NOW()
            """,
            user_id,
            json.dumps(updates),
        )
    log.debug(f"Profile updated for {user_id}: {updates}")


async def append_to_profile_array(user_id: str, field: str, value: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            UPDATE user_profiles
            SET profile = jsonb_set(
                profile,
                '{{{field}}}',
                (COALESCE(profile->'{field}', '[]'::jsonb) || $1::jsonb)
            ),
            updated_at = NOW()
            WHERE user_id = $2
            """,
            json.dumps(value),
            user_id,
        )
    log.debug(f"Appended to profile.{field} for {user_id}")


# ── Prompt formatting ───────────────────────────────────────────────────────

def format_profile_for_prompt(profile: dict) -> str:
    lines = []
    if profile.get("preferred_city"):
        lines.append(f"- Preferred delivery city: {profile['preferred_city']}")
    if profile.get("currency"):
        lines.append(f"- Preferred currency: {profile['currency']}")
    bmin, bmax = profile.get("budget_min"), profile.get("budget_max")
    if bmin is not None or bmax is not None:
        currency = profile.get("currency", "LKR")
        lines.append(f"- Typical budget: {bmin or 'any'} – {bmax or 'any'} {currency}")
    if profile.get("past_recipients"):
        lines.append(f"- Known recipients: {', '.join(profile['past_recipients'])}")
    if profile.get("dislikes"):
        lines.append(f"- Dislikes / avoid: {', '.join(profile['dislikes'])}")
    if profile.get("interests"):
        lines.append(f"- Interests: {', '.join(profile['interests'])}")

    return "User profile:\n" + "\n".join(lines) if lines else "No profile data available yet."
