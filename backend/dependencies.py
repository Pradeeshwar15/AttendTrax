# =============================================================================
# dependencies.py  –  FastAPI dependency injection helpers
# =============================================================================
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth import decode_token
from config import get_settings
from sheets import get_user_by_username

bearer_scheme = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad token payload.")

    # ── Hardcoded admin shortcut – never look up in Google Sheets ─────────
    cfg = get_settings()
    if username.strip().lower() == cfg.ADMIN_USERNAME.strip().lower():
        return {
            "UserID":       "admin",
            "Name":         cfg.ADMIN_NAME,
            "Username":     cfg.ADMIN_USERNAME,
            "PasswordHash": cfg.ADMIN_PASSWORD_HASH,
            "Role":         "ADMIN",
            "ClassID":      "",
        }

    # ── Regular users – look up in Google Sheets ──────────────────────────
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    return user


def require_role(*roles: str):
    async def checker(current_user: dict = Depends(get_current_user)):
        if current_user.get("Role", "").upper() not in [r.upper() for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to roles: {', '.join(roles)}.",
            )
        return current_user
    return checker
