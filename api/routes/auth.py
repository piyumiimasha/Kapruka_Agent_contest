from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import hashlib, secrets
from db.database import get_pool
from db.user_repository import find_or_create_user, upsert_profile
from api.middleware.auth import create_token
from utils.logger import get_logger

log = get_logger("AuthRoute")
router = APIRouter()


class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
    return f"{salt}:{h}"


def verify_password(password: str, hashed: str) -> bool:
    try:
        salt, h = hashed.split(":")
        return hashlib.sha256(f"{salt}{password}".encode()).hexdigest() == h
    except Exception:
        return False


@router.post("/register")
async def register(body: RegisterRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM auth_users WHERE email = $1", body.email
        )
        if existing:
            raise HTTPException(400, "Email already registered")

        hashed = hash_password(body.password)
        row = await conn.fetchrow(
            """INSERT INTO auth_users (email, name, password_hash)
               VALUES ($1, $2, $3) RETURNING id, email, name""",
            body.email, body.name, hashed,
        )

    # auth_user_id becomes the stable user identity across all sessions
    auth_user_id = str(row["id"])

    # Create user + profile records linked to this stable ID
    await find_or_create_user(auth_user_id)
    await upsert_profile(auth_user_id, {
        "name":     body.name,
        "email":    body.email,
        "currency": "LKR",
    })

    token = create_token(auth_user_id)
    log.info(f"Registered: {body.email} → {auth_user_id}")
    return {
        "token": token,
        "user":  {"id": auth_user_id, "email": body.email, "name": body.name},
    }


@router.post("/login")
async def login(body: LoginRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, name, password_hash FROM auth_users WHERE email = $1",
            body.email,
        )

    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Invalid email or password")

    auth_user_id = str(row["id"])

    # Ensure user record exists (handles users created before this fix)
    await find_or_create_user(auth_user_id)

    token = create_token(auth_user_id)
    log.info(f"Logged in: {body.email} → {auth_user_id}")
    return {
        "token": token,
        "user":  {"id": auth_user_id, "email": row["email"], "name": row["name"]},
    }