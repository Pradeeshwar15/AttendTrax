# =============================================================================
# main.py  –  FastAPI application entry point
# =============================================================================
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from routers import auth_router, faculty_router, student_router, admin_router

cfg = get_settings()

app = FastAPI(
    title="AttendTrax API",
    description="Student Attendance Management System – FastAPI backend",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ──────────────────────────────────────────────────────────────────────
origins = [o.strip() for o in cfg.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth_router.router)
app.include_router(faculty_router.router)
app.include_router(student_router.router)
app.include_router(admin_router.router)


@app.get("/")
async def root():
    return {"service": "AttendTrax API", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "ok"}
