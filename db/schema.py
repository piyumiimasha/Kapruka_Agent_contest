from db.connection import get_pool


AUTH_USERS_SQL = """
CREATE TABLE IF NOT EXISTS auth_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


USER_PROFILES_SQL = """
CREATE TABLE IF NOT EXISTS user_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL
        REFERENCES auth_users(id)
        ON DELETE CASCADE,
    profile JSONB NOT NULL DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id)
);
"""


EPISODES_SQL = """
CREATE TABLE IF NOT EXISTS episodes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL
        REFERENCES auth_users(id)
        ON DELETE CASCADE,
    summary TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    embedding vector(1536),
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


CONVERSATION_LOGS_SQL = """
CREATE TABLE IF NOT EXISTS conversation_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    user_id UUID NOT NULL
        REFERENCES auth_users(id)
        ON DELETE CASCADE,

    session_id TEXT NOT NULL,

    role TEXT NOT NULL
        CHECK (role IN ('user', 'assistant')),

    content TEXT NOT NULL,

    agent TEXT,

    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS logs_user_session_idx
ON conversation_logs(user_id, session_id);
"""


async def init_db():
    pool = await get_pool()

    async with pool.acquire() as conn:
        await conn.execute(AUTH_USERS_SQL)
        await conn.execute(USER_PROFILES_SQL)
        await conn.execute(EPISODES_SQL)
        await conn.execute(CONVERSATION_LOGS_SQL)