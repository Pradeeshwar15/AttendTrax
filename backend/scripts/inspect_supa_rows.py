import asyncio
import asyncpg

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings

DATABASE_URL = get_settings().DATABASE_URL
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured in .env")

async def inspect():
    conn = await asyncpg.connect(DATABASE_URL)
    tables = [
        "departments", "users", "classes", "subjects", "students", "faculty",
        "attendance_sessions", "attendance_records", "faculty_allocations",
        "faculty_leaves", "student_leaves", "hostel_gate_passes", "notifications", "audit_logs"
    ]
    print("=== LIVE SUPABASE ROW COUNTS ===")
    for t in tables:
        try:
            cnt = await conn.fetchval(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t}: {cnt}")
        except Exception as e:
            print(f"  {t}: ERROR {e}")
    await conn.close()

if __name__ == "__main__":
    asyncio.run(inspect())
