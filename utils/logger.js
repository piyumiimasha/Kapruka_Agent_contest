import config from "../config/index.js";

const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 };
const current = LEVELS[config.server.logLevel] ?? 0;

const colours = {
  debug: "\x1b[36m",   // cyan
  info:  "\x1b[32m",   // green
  warn:  "\x1b[33m",   // yellow
  error: "\x1b[31m",   // red
  reset: "\x1b[0m",
};

function timestamp() {
  return new Date().toISOString();
}

function log(level, context, message, meta) {
  if (LEVELS[level] < current) return;

  const colour = colours[level] ?? colours.reset;
  const prefix = `${colour}[${level.toUpperCase()}]${colours.reset}`;
  const ctx    = context ? `\x1b[35m[${context}]${colours.reset}` : "";
  const line   = `${timestamp()} ${prefix} ${ctx} ${message}`;

  if (level === "error") {
    console.error(line, meta !== undefined ? meta : "");
  } else {
    console.log(line, meta !== undefined ? meta : "");
  }
}

// Logger factory — call logger("MyModule") to get a scoped logger
export function createLogger(context) {
  return {
    debug: (msg, meta) => log("debug", context, msg, meta),
    info:  (msg, meta) => log("info",  context, msg, meta),
    warn:  (msg, meta) => log("warn",  context, msg, meta),
    error: (msg, meta) => log("error", context, msg, meta),
  };
}

// Root logger (no context)
export default createLogger(null);
