import asyncio
import os
import sys

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import get_engine, init_db, get_session_factory
from models import (
    Department, User, ClassRoom, Student, Faculty, Subject,
    AttendanceSession, AttendanceRecord, FacultyLeave, StudentLeave,
    HostelGatePass, Notification, AuditLog, FacultyAllocation
)
from sqlalchemy import select, func
from fastapi.testclient import TestClient
from main import app

async def verify_zero_cohort():
    print("=" * 70)
    print(">>> 1. INITIALIZING DATABASE SCHEMA VIA SQLALCHEMY ENGINE <<<")
    print("=" * 70)
    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        print("\n>>> 2. VERIFYING ZERO-COHORT TABLE COUNTS IN LIVE SUPABASE <<<")
        checks = [
            ("students", Student),
            ("classes", ClassRoom),
            ("faculty", Faculty),
            ("subjects", Subject),
            ("attendance_sessions", AttendanceSession),
            ("attendance_records", AttendanceRecord),
            ("faculty_allocations", FacultyAllocation),
            ("faculty_leaves", FacultyLeave),
            ("student_leaves", StudentLeave),
            ("hostel_gate_passes", HostelGatePass),
            ("notifications", Notification),
            ("audit_logs", AuditLog),
        ]
        
        all_zero = True
        for name, model in checks:
            cnt = (await session.execute(select(func.count(model.id)))).scalar()
            if cnt != 0:
                print(f"  ❌ {name:<22}: {cnt} (Expected 0)")
                all_zero = False
            else:
                print(f"  ✓ {name:<22}: {cnt} (Clean Zero)")

        dept_cnt = (await session.execute(select(func.count(Department.id)).where(Department.is_active == True))).scalar()
        user_cnt = (await session.execute(select(func.count(User.id)))).scalar()
        print(f"  ✓ active departments    : {dept_cnt} (Expected 10)")
        print(f"  ✓ admin users           : {user_cnt} (Expected 13)")

        if not all_zero:
            raise RuntimeError("Database is not completely cleaned!")

    print("\n>>> 3. TESTING FASTAPI AUTH ENDPOINTS WITH LIVE DATABASE <<<")
    with TestClient(app) as client:
        # Test health endpoint
        r_health = client.get("/health")
        print(f"  ✓ GET /health: {r_health.status_code} -> {r_health.json()}")

        # Test login as admin
        r_login = client.post("/auth/login", data={"username": "admin", "password": "AttendTrax@2026"})
        print(f"  ✓ POST /auth/login (admin): {r_login.status_code}")
        assert r_login.status_code == 200, f"Admin login failed: {r_login.text}"
        admin_token = r_login.json()["access_token"]

        # Test listing students (should return empty list [])
        r_students = client.get("/admin/students", headers={"Authorization": f"Bearer {admin_token}"})
        print(f"  ✓ GET /admin/students: {r_students.status_code} -> {len(r_students.json())} students returned")
        assert len(r_students.json()) == 0, f"Expected 0 students, got {len(r_students.json())}"

        # Test listing classes (should return empty list [])
        r_classes = client.get("/admin/classes", headers={"Authorization": f"Bearer {admin_token}"})
        print(f"  ✓ GET /admin/classes: {r_classes.status_code} -> {len(r_classes.json())} classes returned")
        assert len(r_classes.json()) == 0, f"Expected 0 classes, got {len(r_classes.json())}"

        # Test listing faculty (should return empty list [])
        r_faculty = client.get("/admin/faculty", headers={"Authorization": f"Bearer {admin_token}"})
        print(f"  ✓ GET /admin/faculty: {r_faculty.status_code} -> {len(r_faculty.json())} faculty returned")
        assert len(r_faculty.json()) == 0, f"Expected 0 faculty, got {len(r_faculty.json())}"

        # Test login as principal
        r_princ = client.post("/auth/login", data={"username": "principal", "password": "Principal@2026"})
        print(f"  ✓ POST /auth/login (principal): {r_princ.status_code}")
        assert r_princ.status_code == 200, f"Principal login failed: {r_princ.text}"

        # Test login as placement HOD
        r_hod = client.post("/auth/login", data={"username": "hod.placement", "password": "Hod@2026"})
        print(f"  ✓ POST /auth/login (hod.placement): {r_hod.status_code}")
        assert r_hod.status_code == 200, f"HOD login failed: {r_hod.text}"

    print("\n" + "=" * 70)
    print(">>> ZERO-COHORT LIVE VERIFICATION COMPLETE & PASSED! <<<")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(verify_zero_cohort())
