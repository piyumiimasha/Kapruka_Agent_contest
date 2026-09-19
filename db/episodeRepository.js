import { pool } from "./userRepository.js";
import config from "../config/index.js";
import { createLogger } from "../utils/logger.js";

const log = createLogger("EpisodeRepository");

// ─────────────────────────────────────────
// Save episode + its embedding
// ─────────────────────────────────────────

export async function saveEpisode(userId, summary, metadata, embedding) {
  const res = await pool.query(
    `INSERT INTO episodes (user_id, summary, metadata, embedding)
     VALUES ($1, $2, $3, $4)
     RETURNING id`,
    [userId, summary, JSON.stringify(metadata), JSON.stringify(embedding)]
  );
  log.info("Episode saved", { userId, episodeId: res.rows[0].id });
  return res.rows[0].id;
}

// ─────────────────────────────────────────
// Retrieve top-K similar episodes (vector search)
// ─────────────────────────────────────────

export async function getSimilarEpisodes(userId, queryEmbedding) {
  const { similarityThreshold, topK } = config.vector;

  const res = await pool.query(
    `SELECT id, summary, metadata, created_at,
            1 - (embedding <=> $1::vector) AS similarity
     FROM episodes
     WHERE user_id = $2
       AND 1 - (embedding <=> $1::vector) >= $3
     ORDER BY embedding <=> $1::vector
     LIMIT $4`,
    [JSON.stringify(queryEmbedding), userId, similarityThreshold, topK]
  );

  log.debug("Similar episodes found", { count: res.rows.length });
  return res.rows;
}

// ─────────────────────────────────────────
// Fallback: latest N episodes (no embedding)
// ─────────────────────────────────────────

export async function getRecentEpisodes(userId, limit = config.memory.maxEpisodicInjectCount) {
  const res = await pool.query(
    `SELECT id, summary, metadata, created_at
     FROM episodes
     WHERE user_id = $1
     ORDER BY created_at DESC
     LIMIT $2`,
    [userId, limit]
  );
  return res.rows;
}

// ─────────────────────────────────────────
// Format episodes for prompt injection
// ─────────────────────────────────────────

export function formatEpisodesForPrompt(episodes) {
  if (!episodes.length) return "No past order history.";

  const lines = episodes.map((ep) => {
    const date = new Date(ep.created_at).toLocaleDateString("en-LK");
    return `- [${date}] ${ep.summary}`;
  });

  return `Past interactions (most relevant):\n${lines.join("\n")}`;
}
