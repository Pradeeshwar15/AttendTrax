import asyncio
import os
import sys
import httpx

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database import get_engine

async def test_live_fastapi():
    print("=" * 70)
    print(">>> TESTING FASTAPI ASYNC CLIENT AGAINST LIVE SUPABASE <<<")
    print("=" * 70)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Health check
        r_health = await client.get("/health")
        print(f"  ✓ GET /health: {r_health.status_code} -> {r_health.json()}")

        # Admin login
        r_login = await client.post("/auth/login", json={"username": "admin", "password": "AttendTrax@2026"})
        print(f"  ✓ POST /auth/login (admin): {r_login.status_code}")
        assert r_login.status_code == 200, f"Login failed: {r_login.text}"
        token = r_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Students list
        r_students = await client.get("/admin/students", headers=headers)
        print(f"  ✓ GET /admin/students: {r_students.status_code} -> {len(r_students.json())} students")
        assert len(r_students.json()) == 0

        # Classes list
        r_classes = await client.get("/admin/classes", headers=headers)
        print(f"  ✓ GET /admin/classes: {r_classes.status_code} -> {len(r_classes.json())} classes")
        assert len(r_classes.json()) == 0

        # Faculty list
        r_faculty = await client.get("/admin/faculty", headers=headers)
        print(f"  ✓ GET /admin/faculty: {r_faculty.status_code} -> {len(r_faculty.json())} faculty")
        assert len(r_faculty.json()) == 0

        # Principal login
        r_princ = await client.post("/auth/login", json={"username": "principal", "password": "Principal@2026"})
        print(f"  ✓ POST /auth/login (principal): {r_princ.status_code}")
        assert r_princ.status_code == 200

        # Placement HOD login
        r_hod = await client.post("/auth/login", json={"username": "hod.placement", "password": "Hod@2026"})
        print(f"  ✓ POST /auth/login (hod.placement): {r_hod.status_code}")
        assert r_hod.status_code == 200

    print("\n>>> ALL API ENDPOINTS FUNCTIONING PERFECTLY WITH ZERO-COHORT LIVE SUPABASE! <<<")

if __name__ == "__main__":
    asyncio.run(test_live_fastapi())
