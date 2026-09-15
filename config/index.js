import dotenv from "dotenv";
dotenv.config();

function required(key) {
  const val = process.env[key];
  if (!val) throw new Error(`Missing required env var: ${key}`);
  return val;
}

function optional(key, defaultVal) {
  return process.env[key] ?? defaultVal;
}

const config = {
  // ─────────────────────────────────────────
  // Groq
  // ─────────────────────────────────────────
  groq: {
    apiKey: required("GROQ_API_KEY"),
    orchestratorModel: optional("GROQ_ORCHESTRATOR_MODEL", optional("GROQ_MODEL", "llama-3.3-70b-versatile")),
    agentModel: optional("GROQ_AGENT_MODEL", optional("GROQ_MODEL", "llama-3.1-8b-instant")),
    maxTokens: parseInt(optional("GROQ_MAX_TOKENS", "1024")),
  },

  // ─────────────────────────────────────────
  // OpenRouter (embeddings)
  // ─────────────────────────────────────────
  openRouter: {
    apiKey: required("OPENROUTER_API_KEY"),
    baseUrl: optional("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
    embeddingModel: optional("OPENROUTER_EMBEDDING_MODEL", "text-embedding-3-small"),
  },

  // ─────────────────────────────────────────
  // Kapruka MCP
  // ─────────────────────────────────────────
  kapruka: {
    mcpBaseUrl: optional("KAPRUKA_MCP_BASE_URL", "https://mcp.kapruka.com"),
    defaultCurrency: optional("KAPRUKA_DEFAULT_CURRENCY", "LKR"),
    cacheTtlSeconds: parseInt(optional("KAPRUKA_CACHE_TTL_SECONDS", "1800")),
  },

  // ─────────────────────────────────────────
  // Rate limits
  // ─────────────────────────────────────────
  rateLimits: {
    requestsPerMinute: parseInt(optional("RATE_LIMIT_REQUESTS_PER_MINUTE", "60")),
    createOrderPerHour: parseInt(optional("RATE_LIMIT_CREATE_ORDER_PER_HOUR", "30")),
  },

  // ─────────────────────────────────────────
  // Database
  // ─────────────────────────────────────────
  db: {
    url: required("DATABASE_URL"),
    host: optional("DB_HOST", "localhost"),
    port: parseInt(optional("DB_PORT", "5432")),
    name: optional("DB_NAME", "kapruka_agent"),
    user: optional("DB_USER", "postgres"),
    password: optional("DB_PASSWORD", ""),
  },

  // ─────────────────────────────────────────
  // pgvector
  // ─────────────────────────────────────────
  vector: {
    dimensions: parseInt(optional("VECTOR_DIMENSIONS", "1536")),
    similarityThreshold: parseFloat(optional("VECTOR_SIMILARITY_THRESHOLD", "0.75")),
    topK: parseInt(optional("VECTOR_TOP_K", "5")),
  },

  // ─────────────────────────────────────────
  // Auth
  // ─────────────────────────────────────────
  auth: {
    sessionSecret: required("SESSION_SECRET"),
    jwtSecret: required("JWT_SECRET"),
    jwtExpiresIn: optional("JWT_EXPIRES_IN", "7d"),
  },

  // ─────────────────────────────────────────
  // Server
  // ─────────────────────────────────────────
  server: {
    port: parseInt(optional("PORT", "3000")),
    nodeEnv: optional("NODE_ENV", "development"),
    isDev: optional("NODE_ENV", "development") === "development",
    logLevel: optional("LOG_LEVEL", "debug"),
  },

  // ─────────────────────────────────────────
  // Memory
  // ─────────────────────────────────────────
  memory: {
    maxShortTermTurns: parseInt(optional("MAX_SHORT_TERM_TURNS", "20")),
    maxEpisodicInjectCount: parseInt(optional("MAX_EPISODIC_INJECT_COUNT", "5")),
    maxSemanticProfileTokens: parseInt(optional("MAX_SEMANTIC_PROFILE_TOKENS", "300")),
  },
};

export default config;