# =============================================================================
# test_pure_supabase_health.py
# End-to-End Verification of Pure Supabase PostgreSQL Architecture
# =============================================================================
import os
import sys
import asyncio
import requests

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select, func, delete
from database import get_session_factory, get_engine
from models import Department, User, ClassRoom, Student, Faculty, AttendanceSession, AttendanceRecord

BASE_URL = "http://127.0.0.1:8000"


async def check_db_direct():
    print("\n--- [Step 1] Direct Supabase PostgreSQL Integrity Check ---")
    session_factory = get_session_factory()
    async with session_factory() as session:
        dept_cnt = (await session.execute(select(func.count(Department.id)))).scalar()
        user_cnt = (await session.execute(select(func.count(User.id)))).scalar()
        class_cnt = (await session.execute(select(func.count(ClassRoom.id)))).scalar()
        stud_cnt = (await session.execute(select(func.count(Student.id)))).scalar()
        fac_cnt = (await session.execute(select(func.count(Faculty.id)))).scalar()

        print(f"  Departments : {dept_cnt} (Expected: 10)")
        print(f"  Users       : {user_cnt} (Expected: 13 admins)")
        print(f"  Classes     : {class_cnt} (Expected: 0)")
        print(f"  Students    : {stud_cnt} (Expected: 0)")
        print(f"  Faculty     : {fac_cnt} (Expected: 0)")

        assert dept_cnt == 10, f"Expected 10 departments, got {dept_cnt}"
        assert user_cnt == 13, f"Expected 13 users, got {user_cnt}"
        assert class_cnt == 0, f"Expected 0 classes, got {class_cnt}"
        assert stud_cnt == 0, f"Expected 0 students, got {stud_cnt}"
        assert fac_cnt == 0, f"Expected 0 faculty, got {fac_cnt}"
        print("  ✓ Pure Supabase baseline counts 100% verified!")


def test_auth_endpoints():
    print("\n--- [Step 2] API Authentication Verification ---")
    
    # 1. Admin login
    r_admin = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "AttendTrax@2026"})
    assert r_admin.status_code == 200, f"Admin login failed: {r_admin.status_code} {r_admin.text}"
    admin_data = r_admin.json()
    print(f"  ✓ Admin login OK: role={admin_data['role']}, user_id={admin_data['user_id']}")
    admin_token = admin_data["access_token"]

    # 2. Principal login
    r_prin = requests.post(f"{BASE_URL}/auth/login", json={"username": "principal", "password": "Principal@2026"})
    assert r_prin.status_code == 200, f"Principal login failed: {r_prin.status_code} {r_prin.text}"
    prin_data = r_prin.json()
    print(f"  ✓ Principal login OK: role={prin_data['role']}, user_id={prin_data['user_id']}")

    # 3. HOD CSE login
    r_hod = requests.post(f"{BASE_URL}/auth/login", json={"username": "hod.cse", "password": "Hod@2026"})
    assert r_hod.status_code == 200, f"HOD CSE login failed: {r_hod.status_code} {r_hod.text}"
    hod_data = r_hod.json()
    print(f"  ✓ HOD CSE login OK: role={hod_data['role']}, user_id={hod_data['user_id']}")

    # 4. Invalid login rejected
    r_bad = requests.post(f"{BASE_URL}/auth/login", json={"username": "admin", "password": "WrongPassword@999"})
    assert r_bad.status_code == 401, f"Bad password should fail with 401, got {r_bad.status_code}"
    print("  ✓ Invalid login rejected with HTTP 401 OK")

    return admin_token


async def test_crud_lifecycle(admin_token: str):
    print("\n--- [Step 3] Pure Supabase CRUD Verification (Class & Student) ---")
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 1. Create a Class via API
    class_payload = {
        "class_id": "CSE_TEST_LIVE",
        "class_name": "CSE Live Test Class",
        "department_code": "CSE",
        "year": "2",
        "semester": "3",
        "section": "A",
        "academic_year": "2026-2027"
    }
    r_cls = requests.post(f"{BASE_URL}/admin/classes", json=class_payload, headers=headers)
    assert r_cls.status_code in [200, 201], f"Create class failed: {r_cls.status_code} {r_cls.text}"
    print(f"  ✓ Class created via API: {r_cls.json()}")

    # Verify directly in Supabase
    session_factory = get_session_factory()
    async with session_factory() as session:
        stmt = select(ClassRoom).where(ClassRoom.class_code == "CSE_TEST_LIVE")
        cls_row = (await session.execute(stmt)).scalar_one_or_none()
        assert cls_row is not None, "Class not found in live Supabase classes table!"
        print(f"  ✓ Direct Supabase check: Found class id={cls_row.id}, code={cls_row.class_code}")

    # 2. Create a Student via API
    student_payload = {
        "reg_no": "410125999",
        "name": "Live Test Student",
        "class_id": "CSE_TEST_LIVE",
        "class_name": "CSE Live Test Class",
        "password": "Password@2026"
    }
    r_stu = requests.post(f"{BASE_URL}/admin/students", json=student_payload, headers=headers)
    assert r_stu.status_code in [200, 201], f"Create student failed: {r_stu.status_code} {r_stu.text}"
    print(f"  ✓ Student created via API: {r_stu.json()}")

    # Verify student directly in Supabase
    async with session_factory() as session:
        stmt = select(Student).where(Student.reg_no == "410125999")
        stu_row = (await session.execute(stmt)).scalar_one_or_none()
        assert stu_row is not None, "Student not found in live Supabase students table!"
        print(f"  ✓ Direct Supabase check: Found student id={stu_row.id}, reg_no={stu_row.reg_no}")

        stmt_u = select(User).where(User.username == "410125999")
        u_row = (await session.execute(stmt_u)).scalar_one_or_none()
        assert u_row is not None, "Student User account not found in live Supabase users table!"
        print(f"  ✓ Direct Supabase check: Found User account id={u_row.id}, role={u_row.role}")

    # 3. Test Student Login
    r_stu_login = requests.post(f"{BASE_URL}/auth/login", json={"username": "410125999", "password": "Password@2026"})
    assert r_stu_login.status_code == 200, f"Student login failed: {r_stu_login.status_code} {r_stu_login.text}"
    stu_login_data = r_stu_login.json()
    assert stu_login_data["role"] == "STUDENT", f"Expected STUDENT role, got {stu_login_data['role']}"
    print(f"  ✓ Student Login OK: role={stu_login_data['role']}, class_id={stu_login_data['class_id']}")

    # 4. Clean up test records
    print("\n--- [Step 4] Teardown & Clean Test Records ---")
    async with session_factory() as session:
        # Delete student & user
        await session.execute(delete(Student).where(Student.reg_no == "410125999"))
        await session.execute(delete(User).where(User.username == "410125999"))
        await session.execute(delete(ClassRoom).where(ClassRoom.class_code == "CSE_TEST_LIVE"))
        await session.commit()
        print("  ✓ Test student and class cleanly removed from Supabase.")

    # 5. Check no SQLite files created
    print("\n--- [Step 5] Verify Zero Local SQLite Files ---")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sqlite_backend = os.path.join(backend_dir, "attendtrax.db")
    sqlite_root = os.path.join(os.path.dirname(backend_dir), "attendtrax.db")
    assert not os.path.exists(sqlite_backend), f"Error: {sqlite_backend} exists!"
    assert not os.path.exists(sqlite_root), f"Error: {sqlite_root} exists!"
    print("  ✓ Confirmed: ZERO attendtrax.db or local SQLite files exist.")
    print("\n=======================================================")
    print("ALL TESTS PASSED! 100% PURE SUPABASE POSTGRESQL VERIFIED")
    print("=======================================================")


async def main():
    await check_db_direct()
    admin_token = test_auth_endpoints()
    await test_crud_lifecycle(admin_token)


if __name__ == "__main__":
    asyncio.run(main())
