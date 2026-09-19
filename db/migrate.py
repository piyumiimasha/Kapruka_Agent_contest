import asyncio
import asyncpg
from db.schema import SCHEMA_SQL
from config.settings import settings
from utils.logger import get_logger

log = get_logger("Migrate")


async def run():
    conn = await asyncpg.connect(settings.database_url)
    log.info("Running migrations...")
    await conn.execute(SCHEMA_SQL)
    await conn.close()
    log.info("Migrations complete ✅")


if __name__ == "__main__":
    asyncio.run(run())
