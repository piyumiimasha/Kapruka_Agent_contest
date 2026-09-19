import pg from "pg";
import config from "../config/index.js";
import { schema } from "./schema.js";
import { createLogger } from "../utils/logger.js";

const log = createLogger("Migrate");

async function migrate() {
  const client = new pg.Client({ connectionString: config.db.url });
  await client.connect();
  log.info("Running migrations...");
  await client.query(schema);
  log.info("Migrations complete ✅");
  await client.end();
}

migrate().catch((err) => {
  console.error("Migration failed:", err);
  process.exit(1);
});
