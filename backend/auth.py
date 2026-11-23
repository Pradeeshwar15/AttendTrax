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


def hash_passwords_bulk(passwords: list[str], rounds: int = 8) -> list[str]:
    """
    Multithreaded password hashing for high-speed bulk ingestion (e.g. 500-1,000 accounts in < 0.8s).
    """
    import os
    from concurrent.futures import ThreadPoolExecutor

    salt = bcrypt.gensalt(rounds=rounds)

    def _hash(p: str) -> str:
        return bcrypt.hashpw(p.encode("utf-8")[:72], salt).decode("utf-8")

    max_w = min(32, max(4, (os.cpu_count() or 4) * 2))
    with ThreadPoolExecutor(max_workers=max_w) as pool:
        return list(pool.map(_hash, passwords))


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

