import pg from "pg";
import config from "../config/index.js";
import { createLogger } from "../utils/logger.js";
import { DEFAULT_PROFILE } from "./schema.js";

const log = createLogger("UserRepository");
const pool = new pg.Pool({ connectionString: config.db.url });

// ─────────────────────────────────────────
// User (identity)
// ─────────────────────────────────────────

export async function findOrCreateUser(sessionId) {
  const existing = await pool.query(
    `SELECT * FROM users WHERE session_id = $1`,
    [sessionId]
  );
  if (existing.rows.length > 0) return existing.rows[0];

  const created = await pool.query(
    `INSERT INTO users (session_id) VALUES ($1) RETURNING *`,
    [sessionId]
  );
  log.info("Created new user", { sessionId });
  return created.rows[0];
}

export async function getUserBySessionId(sessionId) {
  const res = await pool.query(
    `SELECT * FROM users WHERE session_id = $1`,
    [sessionId]
  );
  return res.rows[0] ?? null;
}

// ─────────────────────────────────────────
// Semantic profile
// ─────────────────────────────────────────

export async function getProfile(userId) {
  const res = await pool.query(
    `SELECT profile FROM user_profiles WHERE user_id = $1`,
    [userId]
  );
  return res.rows[0]?.profile ?? { ...DEFAULT_PROFILE };
}

export async function upsertProfile(userId, updates) {
  // Merge updates into existing profile (JSONB concat operator ||)
  await pool.query(
    `INSERT INTO user_profiles (user_id, profile)
     VALUES ($1, $2)
     ON CONFLICT (user_id)
     DO UPDATE SET profile = user_profiles.profile || $2::jsonb,
                   updated_at = NOW()`,
    [userId, JSON.stringify(updates)]
  );
  log.debug("Profile updated", { userId, updates });
}

// Append to an array field in the profile (e.g. past_recipients, interests)
export async function appendToProfileArray(userId, field, value) {
  await pool.query(
    `UPDATE user_profiles
     SET profile = jsonb_set(
       profile,
       $1,
       (COALESCE(profile->$2, '[]'::jsonb) || $3::jsonb)
     ),
     updated_at = NOW()
     WHERE user_id = $4`,
    [`{${field}}`, field, JSON.stringify(value), userId]
  );
  log.debug(`Appended to profile.${field}`, { userId, value });
}

// ─────────────────────────────────────────
// Profile summary string (injected into prompts)
// ─────────────────────────────────────────

export function formatProfileForPrompt(profile) {
  const lines = [];

  if (profile.preferred_city)
    lines.push(`- Preferred delivery city: ${profile.preferred_city}`);

  if (profile.currency)
    lines.push(`- Preferred currency: ${profile.currency}`);

  if (profile.budget_min != null || profile.budget_max != null) {
    const min = profile.budget_min ?? "any";
    const max = profile.budget_max ?? "any";
    lines.push(`- Typical budget: ${min} – ${max} ${profile.currency ?? "LKR"}`);
  }

  if (profile.past_recipients?.length)
    lines.push(`- Known recipients: ${profile.past_recipients.join(", ")}`);

  if (profile.dislikes?.length)
    lines.push(`- Dislikes / avoid: ${profile.dislikes.join(", ")}`);

  if (profile.interests?.length)
    lines.push(`- Interests: ${profile.interests.join(", ")}`);

  return lines.length
    ? `User profile:\n${lines.join("\n")}`
    : "No profile data available yet.";
}

export { pool };
