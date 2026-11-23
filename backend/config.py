# =============================================================================
# AttendTrax – FastAPI Backend
# config.py  –  Settings loaded from environment variables / .env file
# =============================================================================
import os
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Environment & Security ────────────────────────────────────────────
    DEBUG: bool = False
    ENVIRONMENT: str = "production"

    # ── Hardcoded Admin Credentials ───────────────────────────────────────
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD_HASH: str = "$2b$12$7i3dcYcR4JezUB.A8tsJb.GwL2VyCJKLJ0McXZ44KiIUzUWd7n2zW"
    ADMIN_NAME: str = "System Administrator"

    # ── Database (PostgreSQL / Supabase) ──────────────────────────────────
    DATABASE_URL: str = ""
    REDIS_URL: str = ""

    # ── Auth ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = os.getenv("SECRET_KEY", "b3a8c1f9d4e207b55f196a8473c2e10495f269a7c3e5d1b7a9f02c4e6813579b")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480   # 8 hours (one school day)

    # ── CORS ──────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:5500,http://127.0.0.1:5500,http://localhost:3000,http://127.0.0.1:3000,https://attendtrax.vercel.app,https://attendtrax-frontend.vercel.app"

    def get_database_url(self) -> str:
        """Return standardized async connection string for PostgreSQL / Supabase."""
        url = self.DATABASE_URL.strip()
        if not url:
            raise RuntimeError("DATABASE_URL is not configured. Live Supabase PostgreSQL connection is required.")
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
