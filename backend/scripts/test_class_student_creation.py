import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database import get_session_factory
from models import ClassRoom, Student, User
from sqlalchemy import select, delete

async def test_create_class_and_student():
    print("=" * 70)
    print(">>> TESTING CLASS AND STUDENT CREATION ON LIVE SUPABASE <<<")
    print("=" * 70)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login as admin
        r_login = await client.post("/auth/login", json={"username": "admin", "password": "AttendTrax@2026"})
        assert r_login.status_code == 200, f"Login failed: {r_login.text}"
        token = r_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 2. Add Class
        class_payload = {
            "class_id": "CSE_TEST_CLASS",
            "class_name": "CSE Test Class III A",
            "department_code": "CSE",
            "year": "3",
            "section": "A",
            "semester": "5"
        }
        r_add_class = await client.post("/admin/classes", json=class_payload, headers=headers)
        print(f"  ✓ POST /admin/classes: {r_add_class.status_code} -> {r_add_class.json()}")
        assert r_add_class.status_code == 200, f"Add class failed: {r_add_class.text}"

        # 3. Add Student to that class
        student_payload = {
            "reg_no": "410199999",
            "name": "Live Test Student",
            "class_id": "CSE_TEST_CLASS",
            "residence_type": "DAY_SCHOLAR"
        }
        r_add_stu = await client.post("/admin/students", json=student_payload, headers=headers)
        print(f"  ✓ POST /admin/students: {r_add_stu.status_code} -> {r_add_stu.json()}")
        assert r_add_stu.status_code == 200, f"Add student failed: {r_add_stu.text}"

        # 4. Verify directly in live Supabase database via session factory
        session_factory = get_session_factory()
        async with session_factory() as session:
            cls_in_db = (await session.execute(select(ClassRoom).where(ClassRoom.class_code == "CSE_TEST_CLASS"))).scalar_one_or_none()
            print(f"  ✓ Database Check Class: Found in Supabase ID={cls_in_db.id if cls_in_db else None}, Code={cls_in_db.class_code if cls_in_db else None}")
            assert cls_in_db is not None, "Class was NOT written to Supabase!"

            stu_in_db = (await session.execute(select(Student).where(Student.reg_no == "410199999"))).scalar_one_or_none()
            print(f"  ✓ Database Check Student: Found in Supabase ID={stu_in_db.id if stu_in_db else None}, RegNo={stu_in_db.reg_no if stu_in_db else None}")
            assert stu_in_db is not None, "Student was NOT written to Supabase!"

        # 5. Clean up test records
        async with session_factory() as session:
            await session.execute(delete(Student).where(Student.reg_no == "410199999"))
            await session.execute(delete(User).where(User.username == "410199999"))
            await session.execute(delete(ClassRoom).where(ClassRoom.class_code == "CSE_TEST_CLASS"))
            await session.commit()
            print("  ✓ Cleaned up test records from Supabase.")

    print("\n" + "=" * 70)
    print(">>> VERIFICATION COMPLETE: DATABASE CREATES AND WRITES PROPERLY! <<<")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_create_class_and_student())
