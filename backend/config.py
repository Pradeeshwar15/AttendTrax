# =============================================================================
# AttendTrax – FastAPI Backend
# config.py  –  Settings loaded from environment variables / .env file
# =============================================================================
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # ── Google Sheets ──────────────────────────────────────────────────────
    # Paste the entire service-account JSON as a single-line string
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    SPREADSHEET_FOLDER_ID: str = "1xs4IOox6GFrptID5U4ik-wIfx-Z-Mvv9"          # Google Drive folder ID
    USERS_SHEET_ID: str = ""                 # Spreadsheet ID for Users sheet
    CLASSES_SHEET_ID: str = ""               # Spreadsheet ID for Classes sheet
    STUDENTS_SHEET_ID: str = ""              # Spreadsheet ID for Students sheet
    SUBJECTS_SHEET_ID: str = ""              # Spreadsheet ID for Subjects sheet
    ATTENDANCE_LOG_SHEET_ID: str = ""        # Spreadsheet ID for Attendance_Log

    # ── Hardcoded Admin Credentials ───────────────────────────────────────
    # Change these values to secure credentials before going to production.
    # ADMIN_PASSWORD_HASH is a bcrypt hash of the plain-text password.
    # To regenerate: python -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('your_password'))"
    ADMIN_USERNAME: str = "admin"
    # Default password: AttendTrax@2026  (change this or override in .env!)
    ADMIN_PASSWORD_HASH: str = "$2b$12$hJ13qK5FuQEklbE9aBIdtOTTNVZo6DFe5yE86KVaf5lQDe1zlyzGi"
    ADMIN_NAME: str = "System Administrator"

    # ── Auth ──────────────────────────────────────────────────────────────
    SECRET_KEY: str = "CHANGE_ME_IN_PRODUCTION_PLEASE"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480   # 8 hours (one school day)

    # ── CORS ──────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: str = "http://localhost:5500,https://attendtrax.vercel.app"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
