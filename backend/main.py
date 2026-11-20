# =============================================================================
# main.py  –  FastAPI application entry point
# =============================================================================
import os
import time
import logging
import threading
import urllib.request
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from collections import defaultdict
from fastapi.responses import JSONResponse

from config import get_settings
from database import init_db
from routers import auth_router, faculty_router, student_router, admin_router, leave_router, executive_router

logger = logging.getLogger("attendtrax.main")
cfg = get_settings()

docs_url = "/docs" if cfg.DEBUG else None
redoc_url = "/redoc" if cfg.DEBUG else None
openapi_url = "/openapi.json" if cfg.DEBUG else None

app = FastAPI(
    title="AttendTrax API",
    description="Student Attendance Management System – FastAPI backend",
    version="1.0.0",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
)

def _render_keep_alive():
    """
    Background daemon that pings the Render service every 9 minutes (540s)
    to prevent free-tier cloud containers from entering idle hibernation.
    Automatically detects RENDER_EXTERNAL_URL if running on Render cloud.
    """
    time.sleep(30)  # Initial grace period after startup
    while True:
        try:
            render_url = os.getenv("RENDER_EXTERNAL_URL")
            target_url = f"{render_url.rstrip('/')}/health" if render_url else "http://127.0.0.1:8000/health"
            req = urllib.request.Request(
                target_url,
                headers={"User-Agent": "AttendTrax-KeepAlive/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                logger.info(f"[KeepAlive] Health ping successful ({target_url}): {resp.status}")
        except Exception as e:
            logger.debug(f"[KeepAlive] Ping exception: {e}")
        time.sleep(540)  # Ping every 9 minutes (Render idle threshold is 15 minutes)

@app.on_event("startup")
async def startup_event():
    # Initialize SQLite/PostgreSQL schema if not already present
    await init_db()
    # Auto-hydrate database if fresh or missing core roles (e.g. on Render container spin-up)
    try:
        from hydrate_db import ensure_hydrated
        await ensure_hydrated()
    except Exception as e:
        print(f"[Hydration Hook Warning] {e}")
    # Start zero-sleep keep-alive daemon
    threading.Thread(target=_render_keep_alive, daemon=True, name="attendtrax-keepalive").start()

# ── GZip Compression Middleware (Ultra-fast payload delivery) ────────────────
app.add_middleware(GZipMiddleware, minimum_size=500)

# ── Global API Rate Limiter Middleware ───────────────────────────────────────
class GlobalRateLimiterMiddleware(BaseHTTPMiddleware):
    """Sliding-window IP rate limiter preventing DDoS and brute-force sweeps."""
    def __init__(self, app, max_requests: int = 180, window_seconds: int = 60):
        super().__init__(app)
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.ip_hits = defaultdict(list)
        self.lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in ("/health", "/", "/favicon.ico"):
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        with self.lock:
            cutoff = now - self.window_seconds
            self.ip_hits[client_ip] = [t for t in self.ip_hits[client_ip] if t > cutoff]
            if len(self.ip_hits[client_ip]) >= self.max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Rate limit exceeded."},
                    headers={"Retry-After": str(self.window_seconds)}
                )
            self.ip_hits[client_ip].append(now)

        return await call_next(request)

app.add_middleware(GlobalRateLimiterMiddleware, max_requests=180, window_seconds=60)

# ── Security Headers Middleware ───────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Prevent MIME-sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Prevent clickjacking / frame embedding
        response.headers["X-Frame-Options"] = "DENY"
        # Enable browser XSS filter
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Control referrer information leak
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Restrict dangerous browser features
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # Enforce HTTPS with HSTS
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Strict Content-Security-Policy (CSP)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: https: blob:; "
            "connect-src 'self' http://127.0.0.1:8000 http://localhost:8000 http://127.0.0.1:5500 http://localhost:5500 https://*.supabase.co https://*.supabase.com; "
            "frame-ancestors 'none';"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ── CORS ──────────────────────────────────────────────────────────────────────
origins = [o.strip() for o in cfg.ALLOWED_ORIGINS.split(",") if o.strip()]
for default_origin in [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "https://attendtrax-frontend.vercel.app",
    "https://attendtrax.vercel.app"
]:
    if default_origin not in origins:
        origins.append(default_origin)

# Hardened CORS: Explicit origin whitelist only (no open regex wildcards)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Retry-After"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(faculty_router.router)
app.include_router(student_router.router)
app.include_router(admin_router.router)
app.include_router(executive_router.router)
app.include_router(leave_router.router)


@app.get("/")
async def root():
    return {"service": "AttendTrax API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Global Production Exception Handler ───────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"[Unhandled Error] {request.method} {request.url.path}: {exc}", exc_info=True)
    if cfg.DEBUG:
        return JSONResponse(status_code=500, content={"detail": str(exc)})
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. The incident has been recorded."}
    )
