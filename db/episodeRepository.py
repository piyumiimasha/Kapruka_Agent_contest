import json
from typing import Optional
from db.database import get_pool
from config.settings import settings
from utils.logger import get_logger

log = get_logger("EpisodeRepository")


async def save_episode(
    user_id: str,
    summary: str,
    metadata: dict,
    embedding: list[float],
) -> str:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO episodes (user_id, summary, metadata, embedding)
            VALUES ($1, $2, $3::jsonb, $4::vector)
            RETURNING id
            """,
            user_id,
            summary,
            json.dumps(metadata),
            str(embedding),          # asyncpg sends vector as string repr
        )
    episode_id = str(row["id"])
    log.info(f"Episode saved: {episode_id}")
    return episode_id


async def get_similar_episodes(user_id: str, query_embedding: list[float]) -> list[dict]:
    pool = await get_pool()
    threshold = settings.vector_similarity_threshold
    top_k = settings.vector_top_k

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, summary, metadata, created_at,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM episodes
            WHERE user_id = $2
              AND 1 - (embedding <=> $1::vector) >= $3
            ORDER BY embedding <=> $1::vector
            LIMIT $4
            """,
            str(query_embedding),
            user_id,
            threshold,
            top_k,
        )
    log.debug(f"Similar episodes found: {len(rows)}")
    return [dict(r) for r in rows]


async def get_recent_episodes(
    user_id: str,
    limit: Optional[int] = None,
) -> list[dict]:
    limit = limit or settings.max_episodic_inject_count
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, summary, metadata, created_at
            FROM episodes
            WHERE user_id = $1
            ORDER BY created_at DESC
            LIMIT $2
            """,
            user_id,
            limit,
        )
    return [dict(r) for r in rows]


def format_episodes_for_prompt(episodes: list[dict]) -> str:
    if not episodes:
        return "No past order history."
    lines = [
        f"- [{ep['created_at'].strftime('%d %b %Y')}] {ep['summary']}"
        for ep in episodes
    ]
    return "Past interactions (most relevant):\n" + "\n".join(lines)
