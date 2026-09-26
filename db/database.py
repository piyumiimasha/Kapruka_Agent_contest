import asyncpg
from config.settings import settings
from utils.logger import get_logger

log = get_logger("Database")
_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
            ssl="require",
            statement_cache_size=0,
        )
        log.info("DB pool created")
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        log.info("DB pool closed")
