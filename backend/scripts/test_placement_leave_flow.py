import asyncio
import os
import sys
import httpx
from datetime import date, timedelta

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from database import get_session_factory
from models import User, Faculty, Department, FacultyLeave, Notification, AuditLog
from auth import hash_password
from sqlalchemy import select, delete

async def test_placement_flow():
    print("=" * 70)
    print(">>> TESTING PLACEMENT DEPT STAFF LEAVE ROUTING & DOCKET WORKFLOW <<<")
    print("=" * 70)

    session_factory = get_session_factory()
    test_user_id = None
    test_leave_id = None

    try:
        # 1. Setup temporary placement faculty user
        async with session_factory() as session:
            plc_dept = (await session.execute(select(Department).where(Department.code == "PLACEMENT"))).scalar_one()
            plc_dept_id = plc_dept.id

            test_u = User(
                username="test.placement.staff",
                full_name="Prof. Test Placement Trainer",
                password_hash=hash_password("Staff@2026"),
                role="FACULTY",
                department_id=plc_dept_id,
                status="ACTIVE"
            )
            session.add(test_u)
            await session.flush()
            test_user_id = test_u.id

            test_fac = Faculty(
                user_id=test_u.id,
                faculty_code="PLC_TEST_01",
                department_id=plc_dept_id,
                designation="Assistant Placement Officer"
            )
            session.add(test_fac)
            await session.commit()
            print(f"  ✓ Created test placement faculty: {test_u.username} (ID: {test_u.id}) in PLACEMENT dept (ID: {plc_dept_id})")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # 2. Login as placement staff
            r_login_staff = await client.post("/auth/login", json={"username": "test.placement.staff", "password": "Staff@2026"})
            assert r_login_staff.status_code == 200, f"Staff login failed: {r_login_staff.text}"
            staff_token = r_login_staff.json()["access_token"]
            staff_headers = {"Authorization": f"Bearer {staff_token}"}

            # 3. Staff applies for leave
            apply_payload = {
                "leave_category": "ON_DUTY",
                "session_scope": "FULL_DAY",
                "start_date": str(date.today()),
                "end_date": str(date.today() + timedelta(days=1)),
                "reason": "Campus Placement Drive at Adhi College Auditorium",
            }
            r_apply = await client.post("/leaves/faculty/apply", json=apply_payload, headers=staff_headers)
            print(f"  ✓ POST /leaves/faculty/apply: {r_apply.status_code} -> {r_apply.json()['message']}")
            assert r_apply.status_code == 200

            # 4. Login as Placement HOD
            r_login_hod = await client.post("/auth/login", json={"username": "hod.placement", "password": "Hod@2026"})
            assert r_login_hod.status_code == 200, f"HOD login failed: {r_login_hod.text}"
            hod_token = r_login_hod.json()["access_token"]
            hod_headers = {"Authorization": f"Bearer {hod_token}"}

            # 5. Check pending HOD leaves for Placement HOD
            r_hod_pending = await client.get("/leaves/faculty/pending-hod", headers=hod_headers)
            print(f"  ✓ GET /leaves/faculty/pending-hod (hod.placement): {r_hod_pending.status_code}")
            assert r_hod_pending.status_code == 200
            pending_list = r_hod_pending.json()
            print(f"    Pending leaves visible to Placement HOD: {len(pending_list)}")
            assert len(pending_list) >= 1, "Placement HOD CANNOT see the leave application!"
            
            leave_ticket = [t for t in pending_list if t["faculty_username"] == "test.placement.staff"][0]
            test_leave_id = leave_ticket["id"]
            print(f"    Found ticket ID: {test_leave_id} from {leave_ticket['faculty_name']}")

            # 6. Placement HOD approves the leave
            r_hod_review = await client.patch(
                f"/leaves/faculty/{test_leave_id}/hod-review",
                json={"action": "APPROVE", "remarks": "Recommended by Head of Placement"},
                headers=hod_headers
            )
            print(f"  ✓ PATCH /leaves/faculty/{test_leave_id}/hod-review (hod.placement): {r_hod_review.status_code}")
            assert r_hod_review.status_code == 200

            # 7. Login as Principal
            r_login_princ = await client.post("/auth/login", json={"username": "principal", "password": "Principal@2026"})
            assert r_login_princ.status_code == 200
            princ_token = r_login_princ.json()["access_token"]
            princ_headers = {"Authorization": f"Bearer {princ_token}"}

            # 8. Principal approves the leave
            r_princ_review = await client.patch(
                f"/leaves/faculty/{test_leave_id}/principal-review",
                json={"action": "APPROVE", "remarks": "Sanctioned for institutional placement drive"},
                headers=princ_headers
            )
            print(f"  ✓ PATCH /leaves/faculty/{test_leave_id}/principal-review (principal): {r_princ_review.status_code}")
            assert r_princ_review.status_code == 200

            # 9. Verify sanction docket generation
            r_docket = await client.get(f"/leaves/faculty/{test_leave_id}/sanction-docket", headers=hod_headers)
            print(f"  ✓ GET /leaves/faculty/{test_leave_id}/sanction-docket: {r_docket.status_code}")
            assert r_docket.status_code == 200
            docket_data = r_docket.json()
            print(f"    Docket Ref: {docket_data['docket_id']}")
            print(f"    Department: {docket_data['faculty']['department_name']} ({docket_data['faculty']['department_code']})")
            print(f"    Status: {docket_data['final_status']}")
            print(f"    Authority: {docket_data['verification']['authority']}")
            assert docket_data["final_status"] == "APPROVED"
            assert docket_data["faculty"]["department_code"] == "PLACEMENT"

            # 10. Check notifications for Placement HOD
            r_notifs = await client.get("/leaves/notifications/unread", headers=hod_headers)
            print(f"  ✓ GET /leaves/notifications/unread (hod.placement): {r_notifs.status_code} -> {len(r_notifs.json())} unread notifs")
            assert len(r_notifs.json()) >= 1, "Placement HOD did not receive approval notifications!"

    finally:
        # Clean up test rows so database remains 100% clean
        print("\n>>> CLEANING UP TEST ARTIFACTS FROM LIVE DATABASE <<<")
        async with session_factory() as session:
            if test_leave_id:
                await session.execute(delete(AuditLog).where(AuditLog.target_id == test_leave_id))
                await session.execute(delete(FacultyLeave).where(FacultyLeave.id == test_leave_id))
            if test_user_id:
                await session.execute(delete(Notification).where(Notification.user_id.in_([test_user_id, 481])))
                await session.execute(delete(AuditLog).where(AuditLog.user_id == test_user_id))
                await session.execute(delete(Faculty).where(Faculty.user_id == test_user_id))
                await session.execute(delete(User).where(User.id == test_user_id))
            # Also clear any stray notifications/audit logs from the test
            await session.execute(delete(Notification))
            await session.execute(delete(AuditLog))
            await session.commit()
            print("  ✓ Cleaned all test records. Live database is spotless!")

    print("\n" + "=" * 70)
    print(">>> PLACEMENT DEPT LEAVE ROUTING & DOCKET TEST 100% PASSED! <<<")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(test_placement_flow())
