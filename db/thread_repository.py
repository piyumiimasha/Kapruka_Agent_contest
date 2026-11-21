"""
Sidebar index of a user's chats. The conversation itself lives in the
LangGraph checkpoints; this small table only stores what the checkpointer
cannot list cheaply: which chats a user has, their title and recency.
"""
from db.database import get_pool


async def ensure_threads_table() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_threads (
                user_id    TEXT        NOT NULL,
                chat_id    TEXT        NOT NULL,
                title      TEXT        NOT NULL DEFAULT 'New chat',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (user_id, chat_id)
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS chat_threads_user_updated
            ON chat_threads (user_id, updated_at DESC)
        """)


async def touch_thread(user_id: str, chat_id: str, title: str) -> None:
    """Create the row on first message; afterwards only bump updated_at."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO chat_threads (user_id, chat_id, title)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, chat_id) DO UPDATE SET updated_at = NOW()
            """,
            user_id, chat_id, title,
        )


async def set_title(user_id: str, chat_id: str, title: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chat_threads SET title = $3, updated_at = NOW() "
            "WHERE user_id = $1 AND chat_id = $2",
            user_id, chat_id, title,
        )


async def list_threads(user_id: str, limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chat_id, title, updated_at FROM chat_threads "
            "WHERE user_id = $1 ORDER BY updated_at DESC LIMIT $2",
            user_id, limit,
        )
    return [dict(r) for r in rows]


async def thread_exists(user_id: str, chat_id: str) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM chat_threads WHERE user_id = $1 AND chat_id = $2",
            user_id, chat_id,
        )
    return row is not None


async def delete_thread(user_id: str, chat_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM chat_threads WHERE user_id = $1 AND chat_id = $2",
            user_id, chat_id,
        )
