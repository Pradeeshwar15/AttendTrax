# =============================================================================
# auth.py  –  Password hashing + JWT token logic
# =============================================================================
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from jose import JWTError, jwt

from config import get_settings


def hash_password(plain: str) -> str:
    pwd_bytes = plain.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8")[:72], hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    cfg = get_settings()
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=cfg.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, cfg.SECRET_KEY, algorithm=cfg.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    cfg = get_settings()
    try:
        return jwt.decode(token, cfg.SECRET_KEY, algorithms=[cfg.ALGORITHM])
    except JWTError:
        return None


# Pre-computed enterprise password hashes for instant offline/fail-safe verification
_ENTERPRISE_HASHES = {
    "principal": hash_password("Principal@2026"),
    "vp": hash_password("VP@2026"),
    "hod": hash_password("Hod@2026"),
    "staff": hash_password("Staff@2026"),
}


def get_hardcoded_user(username: str) -> Optional[dict]:
    cfg = get_settings()
    u = username.strip().lower()
    if u == cfg.ADMIN_USERNAME.strip().lower():
        return {
            "user_id": 1,
            "name": cfg.ADMIN_NAME,
            "username": cfg.ADMIN_USERNAME,
            "role": "SUPER_ADMIN",
            "department_id": None,
            "department_code": "ALL",
            "class_id": "",
            "password_hash": cfg.ADMIN_PASSWORD_HASH,
        }
    if u == "principal":
        return {
            "user_id": 2,
            "name": "Dr. Devaraju (Principal)",
            "username": "principal",
            "role": "SUPER_ADMIN",
            "department_id": None,
            "department_code": "ALL",
            "class_id": "",
            "password_hash": _ENTERPRISE_HASHES["principal"],
        }
    if u == "viceprincipal":
        return {
            "user_id": 3,
            "name": "Dr. Basker (Vice Principal)",
            "username": "viceprincipal",
            "role": "SUPER_ADMIN",
            "department_id": None,
            "department_code": "ALL",
            "class_id": "",
            "password_hash": _ENTERPRISE_HASHES["vp"],
        }
    if u == "hod.placement":
        return {
            "user_id": 99,
            "name": "Dr. K. Sridhar (Head - Training & Placement)",
            "username": "hod.placement",
            "role": "DEPT_ADMIN",
            "department_id": 10,
            "department_code": "PLACEMENT",
            "class_id": "",
            "password_hash": _ENTERPRISE_HASHES["hod"],
        }
    if u in ("placement.staff", "placement.officer"):
        return {
            "user_id": 100,
            "name": "Prof. Rajesh M (Placement Trainer)",
            "username": u,
            "role": "FACULTY",
            "department_id": 10,
            "department_code": "PLACEMENT",
            "class_id": "",
            "password_hash": _ENTERPRISE_HASHES["staff"],
        }
    return None
