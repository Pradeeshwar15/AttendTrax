# =============================================================================
# routers/auth_router.py  –  Login endpoint with Rate Limiting
# =============================================================================
import time
import threading
from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from auth import verify_password, create_access_token, hash_password
from config import get_settings
from dependencies import get_current_user
from sheets import get_user_by_username, update_user_password

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Sliding-Window Login Rate Limiter ─────────────────────────────────────────
class LoginRateLimiter:
    """Thread-safe in-memory rate limiter tracking failed logins per IP and username."""
    def __init__(self, max_attempts: int = 5, window_seconds: int = 180):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._ip_attempts: Dict[str, List[float]] = {}
        self._user_attempts: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def _clean_old(self, timestamps: List[float], now: float) -> List[float]:
        return [t for t in timestamps if now - t < self.window_seconds]

    def check(self, ip: str, username: str) -> None:
        now = time.time()
        with self._lock:
            # Clean and check IP
            ip_records = self._clean_old(self._ip_attempts.get(ip, []), now)
            self._ip_attempts[ip] = ip_records
            if len(ip_records) >= self.max_attempts:
                oldest = ip_records[0]
                retry_after = int(self.window_seconds - (now - oldest)) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Too many failed login attempts from this IP. Please try again in {retry_after} seconds.",
                    headers={"Retry-After": str(retry_after)},
                )

            # Clean and check Username
            user_key = username.strip().lower()
            if user_key:
                user_records = self._clean_old(self._user_attempts.get(user_key, []), now)
                self._user_attempts[user_key] = user_records
                if len(user_records) >= self.max_attempts:
                    oldest = user_records[0]
                    retry_after = int(self.window_seconds - (now - oldest)) + 1
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail=f"Too many failed login attempts for this account. Please try again in {retry_after} seconds.",
                        headers={"Retry-After": str(retry_after)},
                    )

    def record_failure(self, ip: str, username: str) -> None:
        now = time.time()
        user_key = username.strip().lower()
        with self._lock:
            self._ip_attempts.setdefault(ip, []).append(now)
            if user_key:
                self._user_attempts.setdefault(user_key, []).append(now)

    def record_success(self, ip: str, username: str) -> None:
        user_key = username.strip().lower()
        with self._lock:
            self._ip_attempts.pop(ip, None)
            if user_key:
                self._user_attempts.pop(user_key, None)


login_rate_limiter = LoginRateLimiter(max_attempts=5, window_seconds=180)


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "127.0.0.1"


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    name: str
    user_id: str
    class_id: str = ""


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request):
    cfg = get_settings()
    client_ip = _get_client_ip(request)
    uname = body.username.strip()

    # Rate limit check before verification
    login_rate_limiter.check(client_ip, uname)

    # ── 1. Check hardcoded Admin credentials first ────────────────────────
    if uname.lower() == cfg.ADMIN_USERNAME.strip().lower():
        if not verify_password(body.password, cfg.ADMIN_PASSWORD_HASH):
            login_rate_limiter.record_failure(client_ip, uname)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        login_rate_limiter.record_success(client_ip, uname)
        token = create_access_token({"sub": cfg.ADMIN_USERNAME, "role": "ADMIN"})
        return LoginResponse(
            access_token=token,
            role="ADMIN",
            name=cfg.ADMIN_NAME,
            user_id="admin",
            class_id="",
        )

    # ── 2. Fall back to Google Sheets for Faculty / Student logins ────────
    user = get_user_by_username(uname)
    if not user:
        login_rate_limiter.record_failure(client_ip, uname)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if not verify_password(body.password, str(user.get("PasswordHash", ""))):
        login_rate_limiter.record_failure(client_ip, uname)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    login_rate_limiter.record_success(client_ip, uname)
    token = create_access_token({"sub": uname, "role": user["Role"]})
    return LoginResponse(
        access_token=token,
        role=str(user.get("Role", "")),
        name=str(user.get("Name", "")),
        user_id=str(user.get("UserID", "")),
        class_id=str(user.get("ClassID", "")),
    )


class ChangePasswordRequest(BaseModel):
    new_password: str


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
):
    new_pwd = body.new_password.strip()
    if not new_pwd or len(new_pwd) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 6 characters long.",
        )

    username = current_user.get("Username") or current_user.get("sub") or ""
    cfg = get_settings()
    if username.strip().lower() == cfg.ADMIN_USERNAME.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin credentials cannot be changed through this portal.",
        )

    new_hash = hash_password(new_pwd)
    success = update_user_password(username, new_hash)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User '{username}' was not found in the database.",
        )
    return {"message": "Password changed successfully!"}

