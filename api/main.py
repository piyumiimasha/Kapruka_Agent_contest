from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from db.database import get_pool, close_pool
from api.routes.chat import router as chat_router
from kapruka_mcp.mcp_client import RateLimitError, McpError
from config.settings import settings
from utils.logger import get_logger

log = get_logger("Server")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await get_pool()          # warm DB pool on startup
    log.info(f"Kapruka agent started | env={settings.env} | model={settings.groq_orchestrator_model}")
    yield
    await close_pool()


app = FastAPI(title="Kapruka Agent", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api/chat")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.env}


@app.exception_handler(RateLimitError)
async def rate_limit_handler(request: Request, exc: RateLimitError):
    return JSONResponse(
        status_code=429,
        content={"error": "Rate limit reached", "retry_after_ms": exc.retry_after_ms, "message": str(exc)},
    )


@app.exception_handler(McpError)
async def mcp_error_handler(request: Request, exc: McpError):
    return JSONResponse(
        status_code=502,
        content={"error": "Kapruka MCP error", "message": str(exc), "status": exc.status},
    )


@app.exception_handler(Exception)
async def generic_handler(request: Request, exc: Exception):
    log.error(f"Unhandled error: {exc}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "message": str(exc) if settings.is_dev else "Something went wrong"},
    )
