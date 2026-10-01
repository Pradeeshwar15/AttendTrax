# =============================================================================
# routers/auth_router.py  –  Login endpoint
# =============================================================================
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from auth import verify_password, create_access_token
from config import get_settings
from sheets import get_user_by_username

router = APIRouter(prefix="/auth", tags=["Auth"])


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
async def login(body: LoginRequest):
    cfg = get_settings()

    # ── 1. Check hardcoded Admin credentials first ────────────────────────
    if body.username.strip().lower() == cfg.ADMIN_USERNAME.strip().lower():
        if not verify_password(body.password, cfg.ADMIN_PASSWORD_HASH):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        token = create_access_token({"sub": cfg.ADMIN_USERNAME, "role": "ADMIN"})
        return LoginResponse(
            access_token=token,
            role="ADMIN",
            name=cfg.ADMIN_NAME,
            user_id="admin",
            class_id="",
        )

    # ── 2. Fall back to Google Sheets for Faculty / Student logins ────────
    user = get_user_by_username(body.username)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    if not verify_password(body.password, str(user.get("PasswordHash", ""))):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token = create_access_token({"sub": body.username, "role": user["Role"]})
    return LoginResponse(
        access_token=token,
        role=str(user.get("Role", "")),
        name=str(user.get("Name", "")),
        user_id=str(user.get("UserID", "")),
        class_id=str(user.get("ClassID", "")),
    )
