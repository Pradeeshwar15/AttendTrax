# =============================================================================
# dependencies.py  –  FastAPI dependency injection helpers
# Supports Enterprise RBAC (Pure Supabase / PostgreSQL Engine)
# =============================================================================
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from auth import decode_token, get_hardcoded_user
from config import get_settings
from database import get_session_factory
from models import User, Student, ClassRoom

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

    cfg = get_settings()

    # ── 1. Hardcoded Enterprise Accounts (Principal, VP, HODs, Admin) ────────
    hardcoded = get_hardcoded_user(username)
    if hardcoded:
        return {
            "UserID": str(hardcoded["user_id"]),
            "user_id": hardcoded["user_id"],
            "Name": hardcoded["name"],
            "full_name": hardcoded["name"],
            "Username": hardcoded["username"],
            "sub": hardcoded["username"],
            "PasswordHash": "",
            "Role": hardcoded["role"],
            "role": hardcoded["role"],
            "department_id": hardcoded["department_id"],
            "department_code": hardcoded.get("department_code", ""),
            "ClassID": hardcoded.get("class_id", ""),
            "class_id": hardcoded.get("class_id", ""),
        }

    # ── 2. Primary: Look up in Relational SQL Database ───────────────────────
    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            stmt = select(User).where(User.username == username)
            res = await session.execute(stmt)
            user_obj = res.scalar_one_or_none()
            if user_obj:
                cls_id = ""
                reg_no = user_obj.username
                if user_obj.role == "STUDENT":
                    s_stmt = (
                        select(Student.reg_no, ClassRoom.class_code)
                        .outerjoin(ClassRoom, Student.class_id == ClassRoom.id)
                        .where(Student.user_id == user_obj.id)
                    )
                    s_res = await session.execute(s_stmt)
                    s_row = s_res.first()
                    if s_row:
                        reg_no = s_row[0] or reg_no
                        cls_id = s_row[1] or ""

                return {
                    "UserID": str(user_obj.id),
                    "user_id": user_obj.id,
                    "Name": user_obj.full_name,
                    "full_name": user_obj.full_name,
                    "Username": user_obj.username,
                    "sub": user_obj.username,
                    "Role": user_obj.role.upper(),
                    "role": user_obj.role.upper(),
                    "department_id": user_obj.department_id,
                    "ClassID": cls_id,
                    "class_id": cls_id,
                    "RegNo": reg_no,
                    "reg_no": reg_no,
                }
    except Exception as exc:
        print(f"[AUTH DB LOOKUP ERROR] {exc}")

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")


def require_role(*roles: str):
    async def checker(current_user: dict = Depends(get_current_user)):
        user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
        allowed = [r.upper() for r in roles]

        # Hierarchy: SUPER_ADMIN and ADMIN have access to all admin/faculty/warden management endpoints
        if user_role in ["SUPER_ADMIN", "ADMIN"]:
            if any(r in ["SUPER_ADMIN", "ADMIN", "DEPT_ADMIN", "CLASS_INCHARGE", "FACULTY", "WARDEN"] for r in allowed):
                return current_user

        if user_role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access restricted to roles: {', '.join(roles)}. Current role: {user_role}",
            )
        return current_user
    return checker
