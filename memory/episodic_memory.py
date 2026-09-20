import httpx
from config.settings import settings
from db.episode_repository import (
    save_episode,
    get_similar_episodes,
    get_recent_episodes,
    format_episodes_for_prompt,
)
from utils.logger import get_logger

log = get_logger("EpisodicMemory")


async def _embed(text: str) -> list[float]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            f"{settings.openrouter_base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={"model": settings.openrouter_embedding_model, "input": text},
        )
    if response.status_code != 200:
        raise RuntimeError(f"Embedding error {response.status_code}: {response.text}")
    return response.json()["data"][0]["embedding"]


async def record_episode(user_id: str, summary: str, metadata: dict = None) -> str | None:
    try:
        embedding = await _embed(summary)
        episode_id = await save_episode(user_id, summary, metadata or {}, embedding)
        log.info(f"Episode recorded: {episode_id}")
        return episode_id
    except Exception as e:
        log.error(f"Failed to record episode: {e}")
        return None   # non-fatal


async def get_relevant_episodes(user_id: str, query: str) -> list[dict]:
    try:
        embedding = await _embed(query)
        episodes = await get_similar_episodes(user_id, embedding)
        if episodes:
            return episodes
        return await get_recent_episodes(user_id)
    except Exception as e:
        log.warning(f"Vector search failed, falling back to recency: {e}")
        return await get_recent_episodes(user_id)


__all__ = ["record_episode", "get_relevant_episodes", "format_episodes_for_prompt"]
