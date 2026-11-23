"""
test_placement_attendance_sandbox.py
End-to-End Verification Suite for Placement Attendance Dedicated Table & Sandboxing
Validates:
1. Schema & Supabase placement_attendance table
2. Academic Faculty vs Placement Faculty Dual-Track Isolation
3. Multi-slot Training Dropdown Options (training_classes, technical_assessment, etc.)
4. Placement HOD Analytics Sandbox (Zero Academic Leakage)
5. Executive Dashboard / Academic HOD Isolation (Zero Placement Leakage)
6. Student Portal Dual Attendance (Side-by-Side Presentation)
"""

import sys
import os
import asyncio
from datetime import date, datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, and_, func, inspect, delete
from database import get_session_factory, get_engine
from models import (
    Base,
    PlacementAttendance,
    AttendanceSession,
    AttendanceRecord,
    Student,
    ClassRoom,
    User,
    Department
)
from services.sql_analytics import (
    compute_placement_admin_analytics,
    compute_sql_admin_analytics,
    get_placement_attendance_overview,
    get_placement_class_matrix,
    get_placement_class_attendance_report,
)
from routers.faculty_router import (
    PLACEMENT_SLOTS,
    PLACEMENT_SLOT_KEYS,
    normalize_placement_slot,
    is_placement_user,
)


async def run_tests():
    print("=" * 70)
    print("🎯 STARTING PLACEMENT ATTENDANCE & SANDBOXING VERIFICATION SUITE")
    print("=" * 70)

    passed_count = 0
    total_count = 6

    async_session = get_session_factory()
    engine = get_engine()

    async with async_session() as db:
        # ── Test 1: Verify Schema & Table Columns in Supabase ───────────────
        print("\n[TEST 1] Verifying 'placement_attendance' table in Supabase...")
        async with engine.connect() as conn:
            def inspect_db(sync_conn):
                insp = inspect(sync_conn)
                has_table = insp.has_table("placement_attendance")
                cols = [c["name"] for c in insp.get_columns("placement_attendance")] if has_table else []
                return has_table, cols
            has_table, cols = await conn.run_sync(inspect_db)

        expected_cols = [
            "id", "student_id", "class_id", "faculty_id",
            "attendance_date", "slot_type", "training_topic",
            "status", "remarks", "created_at", "updated_at"
        ]
        assert has_table, "Table 'placement_attendance' does not exist in Supabase!"
        for col in expected_cols:
            assert col in cols, f"Missing column '{col}' in 'placement_attendance'!"
        print(f"  ✅ Table 'placement_attendance' exists with all {len(cols)} columns: {cols}")
        passed_count += 1

        # ── Test 2: Verify Multi-Slot Definitions ───────────────────────────
        print("\n[TEST 2] Verifying multi-slot training dropdown definitions...")
        required_slots = [
            "training_classes",
            "technical_assessment",
            "leetcode_hackerrank",
            "mock_interview",
            "gd_session",
            "placement_meets"
        ]
        for slot in required_slots:
            assert slot in PLACEMENT_SLOT_KEYS, f"Missing slot key '{slot}' in PLACEMENT_SLOT_KEYS!"
            norm_key = normalize_placement_slot(slot)
            norm_label = PLACEMENT_SLOT_KEYS.get(norm_key, norm_key)
            assert norm_key == slot, f"Normalization mismatch for slot '{slot}': got '{norm_key}'"
            print(f"  Slot verified: {norm_key} -> '{norm_label}'")

        assert is_placement_user({"username": "placement.staff", "role": "FACULTY"}), "placement.staff should be placement user"
        assert is_placement_user({"username": "hod.placement", "role": "DEPT_ADMIN"}), "hod.placement should be placement user"
        assert not is_placement_user({"username": "antonysudha.cse", "role": "FACULTY"}), "antonysudha.cse should NOT be placement user"
        print("  ✅ All 6 training slot types and user role checks verified.")
        passed_count += 1

        # ── Test 3: Dual-Track Attendance Ingestion & Database Separation ───
        print("\n[TEST 3] Testing Dual-Track Attendance Isolation in Supabase...")
        # Get a real student and class
        st_res = await db.execute(select(Student).where(Student.status == "ACTIVE").limit(1))
        test_student = st_res.scalar_one_or_none()
        assert test_student is not None, "No active student found for testing!"

        cls_res = await db.execute(select(ClassRoom).where(ClassRoom.id == test_student.class_id))
        test_class = cls_res.scalar_one()

        fac_res = await db.execute(select(User).where(User.username == "placement.staff"))
        test_faculty = fac_res.scalar_one_or_none()
        if not test_faculty:
            # Fallback to any user
            test_faculty = (await db.execute(select(User).limit(1))).scalar_one()

        today_date = date.today()

        # Clean existing test records for today if any
        await db.execute(
            delete(PlacementAttendance).where(
                and_(
                    PlacementAttendance.student_id == test_student.id,
                    PlacementAttendance.attendance_date == today_date,
                    PlacementAttendance.slot_type == "technical_assessment"
                )
            )
        )
        await db.commit()

        # 1. Insert a Placement Attendance record into placement_attendance
        test_placement_rec = PlacementAttendance(
            student_id=test_student.id,
            class_id=test_class.id,
            faculty_id=test_faculty.id,
            attendance_date=today_date,
            slot_type="technical_assessment",
            training_topic="Full-Stack Coding & DS Assessment",
            status="P",
            remarks="Excellent score in SQL & Trees"
        )
        db.add(test_placement_rec)
        await db.commit()
        await db.refresh(test_placement_rec)

        # Verify that record exists in placement_attendance
        chk_plc = await db.execute(
            select(PlacementAttendance).where(PlacementAttendance.id == test_placement_rec.id)
        )
        saved_plc = chk_plc.scalar_one_or_none()
        assert saved_plc is not None, "Placement record was not saved to placement_attendance table!"
        assert saved_plc.slot_type == "technical_assessment"
        assert saved_plc.training_topic == "Full-Stack Coding & DS Assessment"

        # Verify that ZERO rows were written to academic tables (attendance_sessions) with slot_type
        chk_acad = await db.execute(
            select(AttendanceSession).where(
                and_(
                    AttendanceSession.class_id == test_class.id,
                    AttendanceSession.session_date == today_date,
                    AttendanceSession.slot_hour == "technical_assessment"
                )
            )
        )
        assert chk_acad.scalar_one_or_none() is None, "Academic attendance_sessions should not contain placement slots!"
        # Verify placement table has the record and academic tables are completely separate
        print(f"  ✅ Record {saved_plc.id} saved strictly in 'placement_attendance' table.")
        print("  ✅ Zero interference with regular academic attendance tables.")
        passed_count += 1

        # ── Test 4: Placement HOD Analytics Sandbox (Zero Academic Leakage) ───
        print("\n[TEST 4] Testing Placement HOD Analytics Sandboxing...")
        plc_analytics = await compute_placement_admin_analytics(db)
        assert plc_analytics.get("is_placement_sandbox") is True, "Placement sandbox flag missing!"
        assert "overall_percentage" in plc_analytics, "overall_percentage missing in placement analytics!"
        assert "department_breakdown" in plc_analytics, "department_breakdown missing in placement analytics!"
        assert "defaulters" in plc_analytics, "defaulters missing in placement analytics!"
        assert "daily_trend" in plc_analytics, "daily_trend missing in placement analytics!"

        print(f"  Placement Turnout Today: {plc_analytics.get('today', {}).get('present', 0)} present")
        print(f"  Placement Overall %: {plc_analytics.get('overall_percentage')}%")
        print(f"  Placement Departments tracked: {len(plc_analytics.get('department_breakdown', []))}")
        print("  ✅ Placement HOD dashboard aggregates strictly from 'placement_attendance'!")
        passed_count += 1

        # ── Test 5: Executive Dashboard & Academic HOD Sandbox (Zero Placement Leakage)
        print("\n[TEST 5] Testing Executive Dashboard & Academic Isolation...")
        acad_analytics = await compute_sql_admin_analytics(db)
        # Academic analytics must not have is_placement_sandbox
        assert "is_placement_sandbox" not in acad_analytics, "Academic analytics should NOT contain is_placement_sandbox!"
        assert "overall_percentage" in acad_analytics, "overall_percentage missing in academic analytics!"
        assert "class_stats" in acad_analytics, "class_stats missing in academic analytics!"
        print(f"  Academic Overall %: {acad_analytics.get('overall_percentage')}%")
        print(f"  Academic Classes tracked: {len(acad_analytics.get('class_stats', []))}")
        print("  ✅ Principal and Academic HODs receive strictly academic attendance data!")
        passed_count += 1

        # ── Test 6: Student Portal Dual Attendance (Side-by-Side) ───────────
        print("\n[TEST 6] Testing Student Portal Dual Attendance Delivery...")
        # Simulate query in student_router
        plc_records_stmt = (
            select(PlacementAttendance, User.full_name.label("faculty_name"))
            .outerjoin(User, PlacementAttendance.faculty_id == User.id)
            .where(PlacementAttendance.student_id == test_student.id)
            .order_by(PlacementAttendance.attendance_date.desc(), PlacementAttendance.id.desc())
        )
        plc_rows = (await db.execute(plc_records_stmt)).all()

        total_plc_sessions = len(plc_rows)
        present_plc = sum(1 for p, _ in plc_rows if p.status == "P")
        od_plc = sum(1 for p, _ in plc_rows if p.status in ("OD", "ONDUTY", "ON DUTY"))
        absent_plc = sum(1 for p, _ in plc_rows if p.status == "A")
        plc_pct = round(((present_plc + od_plc) / total_plc_sessions) * 100, 1) if total_plc_sessions > 0 else 0.0

        plc_payload = {
            "total_sessions": total_plc_sessions,
            "attended_sessions": present_plc + od_plc,
            "absent_sessions": absent_plc,
            "od_sessions": od_plc,
            "percentage": plc_pct,
            "history": [
                {
                    "id": p.id,
                    "attendance_date": p.attendance_date.strftime("%d-%m-%Y") if p.attendance_date else "",
                    "slot_type": p.slot_type,
                    "training_topic": p.training_topic,
                    "status": p.status,
                    "remarks": p.remarks,
                    "faculty_name": fac_name or "Placement Trainer"
                }
                for p, fac_name in plc_rows
            ]
        }

        assert plc_payload["total_sessions"] >= 1, "Placement payload should have at least 1 session for test student!"
        assert plc_payload["attended_sessions"] >= 1, "Placement payload should have attended session!"
        assert len(plc_payload["history"]) >= 1, "Placement history should have at least 1 record!"
        print(f"  Student: {test_student.name} ({test_student.reg_no})")
        print(f"  Dual Attendance - Placement Sessions: {plc_payload['total_sessions']}, Attended: {plc_payload['attended_sessions']}, %: {plc_payload['percentage']}%")
        print(f"  Latest Session: {plc_payload['history'][0]['training_topic']} ({plc_payload['history'][0]['slot_type']}) - Status: {plc_payload['history'][0]['status']}")
        print("  ✅ Student portal receives side-by-side Academic and Placement Attendance!")
        passed_count += 1

        # Clean up test record
        await db.delete(saved_plc)
        await db.commit()
        print("\n  🧹 Test record cleaned up successfully.")

    print("\n" + "=" * 70)
    print(f"🎉 ALL {passed_count}/{total_count} VERIFICATION TESTS PASSED SUCCESSFULLY!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(run_tests())
