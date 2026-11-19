# =============================================================================
# routers/auth_router.py  –  Login endpoint with Rate Limiting
# =============================================================================
import time
import threading
from typing import Dict, List
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from auth import verify_password, create_access_token, hash_password, get_hardcoded_user
from config import get_settings
from database import get_session_factory
from dependencies import get_current_user
from models import User, Student, ClassRoom
from sqlalchemy import select, or_

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
    username: str = ""
    class_id: str = ""


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, request: Request):
    cfg = get_settings()
    client_ip = _get_client_ip(request)
    uname = body.username.strip()

    # Rate limit check before verification
    login_rate_limiter.check(client_ip, uname)

    # ── 1. Check institutional hardcoded credentials first ────────────────
    hardcoded = get_hardcoded_user(uname)
    if hardcoded and hardcoded.get("password_hash"):
        if verify_password(body.password, hardcoded["password_hash"]):
            login_rate_limiter.record_success(client_ip, uname)
            token = create_access_token({
                "sub": hardcoded["username"],
                "role": hardcoded["role"],
                "user_id": hardcoded["user_id"],
                "department_id": hardcoded.get("department_id"),
                "department_code": hardcoded.get("department_code", ""),
            })
            return LoginResponse(
                access_token=token,
                role=hardcoded["role"],
                name=hardcoded["name"],
                user_id=str(hardcoded["user_id"]),
                username=hardcoded["username"],
                class_id=hardcoded.get("class_id", ""),
            )
        else:
            login_rate_limiter.record_failure(client_ip, uname)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )

    # ── 2. Primary: Look up in Relational SQL Database (Supabase / SQLite) ──
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = (
                select(User, Student, ClassRoom.class_code)
                .outerjoin(Student, Student.user_id == User.id)
                .outerjoin(ClassRoom, Student.class_id == ClassRoom.id)
                .where(or_(User.username == uname, Student.reg_no == uname))
            )
            res = await session.execute(stmt)
            match_row = res.first()
            if match_row:
                u_obj, st_obj, cls_code = match_row
                pwd_ok = verify_password(body.password, u_obj.password_hash)
                
                # Institutional default fallbacks for students: <RegNo>@2026 or <RegNo>@CSE
                if not pwd_ok and u_obj.role == "STUDENT":
                    reg_val = (st_obj.reg_no if st_obj else u_obj.username).strip()
                    allowed_defaults = {
                        f"{reg_val}@2026".upper(),
                        f"{u_obj.username}@2026".upper(),
                        f"{reg_val}@CSE".upper(),
                        f"{u_obj.username}@CSE".upper(),
                    }
                    if body.password.strip().upper() in allowed_defaults:
                        pwd_ok = True
                        try:
                            u_obj.password_hash = hash_password(body.password.strip())
                            await session.commit()
                        except Exception as upd_err:
                            print(f"[AUTH PWD SYNC WARNING] {upd_err}")

                if pwd_ok:
                    login_rate_limiter.record_success(client_ip, uname)
                    token = create_access_token({
                        "sub": u_obj.username,
                        "role": u_obj.role,
                        "user_id": u_obj.id,
                        "department_id": u_obj.department_id,
                    })

                    return LoginResponse(
                        access_token=token,
                        role=u_obj.role,
                        name=u_obj.full_name,
                        user_id=str(u_obj.id),
                        username=u_obj.username,
                        class_id=cls_code or "",
                    )
                else:
                    login_rate_limiter.record_failure(client_ip, uname)
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid username or password.",
                    )
    except HTTPException:
        raise
    except Exception as exc:
        print(f"[AUTH ERROR] {exc}")

    login_rate_limiter.record_failure(client_ip, uname)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid username or password.",
    )


class ChangePasswordRequest(BaseModel):
    new_password: str


@router.post("/change-password")
async def change_password(
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
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(User).where(User.username == username)
        u_obj = (await session.execute(stmt)).scalar_one_or_none()
        if not u_obj:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User '{username}' was not found in the database.",
            )
        u_obj.password_hash = new_hash
        await session.commit()

    return {"message": "Password changed successfully!"}

