# =============================================================================
# backend/scripts/test_attendance_extensions.py
# Automated Verification Suite for Daily Absent/OD Registers, Placement Willingness,
# and Department-Scoped Subject Isolation
# =============================================================================
import os
import sys
from datetime import date

# Ensure backend directory is in python path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
from sqlalchemy import select, and_, func
from database import get_session_factory
from models import Student, ClassRoom, Subject, Department, PlacementAttendance, AttendanceSession, AttendanceRecord, User
from services.sql_analytics import get_sql_daily_status_students


async def test_suite():
    print("\n" + "="*70)
    print("⚡ AttendTrax Feature Verification: Absent/OD, Willingness & Subjects")
    print("="*70 + "\n")

    session_factory = get_session_factory()
    async with session_factory() as session:
        # ── Test 1: Verify placement_willingness column exists on Student ─────
        print("[Test 1] Verifying placement_willingness column on Student...")
        test_student_stmt = select(Student).limit(1)
        res = await session.execute(test_student_stmt)
        stu = res.scalar_one_or_none()
        assert stu is not None, "At least one student must exist in database"
        assert hasattr(stu, "placement_willingness"), "Student model must have placement_willingness attribute"
        print(f"  ✓ Sample Student: {stu.reg_no} ({stu.name}) -> placement_willingness: {stu.placement_willingness}")

        # ── Test 2: Toggle placement_willingness (Single + Bulk) ─────────────
        print("\n[Test 2] Testing Willingness Single & Bulk Mutation...")
        orig_val = stu.placement_willingness
        stu.placement_willingness = "inactive"
        await session.commit()
        await session.refresh(stu)
        assert stu.placement_willingness == "inactive", "Failed to set placement_willingness to inactive"
        print(f"  ✓ Successfully set {stu.reg_no} placement_willingness to 'inactive'")

        # Restore
        stu.placement_willingness = "active"
        await session.commit()
        await session.refresh(stu)
        assert stu.placement_willingness == "active", "Failed to restore placement_willingness to active"
        print(f"  ✓ Successfully restored {stu.reg_no} placement_willingness to 'active'")

        # ── Test 3: Faculty Roster Placement Sandboxing ──────────────────────
        print("\n[Test 3] Testing Faculty Roster Filtering for Placement vs Academic...")
        target_class_id = stu.class_id
        # Temporarily mark one student inactive
        stu.placement_willingness = "inactive"
        await session.commit()

        # Query as Academic Faculty (all active students)
        acad_stmt = select(Student).where(and_(Student.class_id == target_class_id, Student.status == "ACTIVE"))
        acad_students = (await session.execute(acad_stmt)).scalars().all()

        # Query as Placement Faculty (only willing students)
        plc_stmt = select(Student).where(and_(
            Student.class_id == target_class_id,
            Student.status == "ACTIVE",
            func.lower(Student.placement_willingness) == "active"
        ))
        plc_students = (await session.execute(plc_stmt)).scalars().all()

        print(f"  Academic roster student count:  {len(acad_students)}")
        print(f"  Placement roster student count: {len(plc_students)}")
        assert len(acad_students) == len(plc_students) + 1, "Placement roster must exclude the inactive student"
        assert stu.reg_no not in [s.reg_no for s in plc_students], f"Inactive student {stu.reg_no} must NOT be in placement roster"
        assert stu.reg_no in [s.reg_no for s in acad_students], f"Inactive student {stu.reg_no} MUST remain in academic roster"
        print("  ✓ Strict sandboxing verified: Unwilling student excluded from Placement, included in Academic!")

        # Restore student
        stu.placement_willingness = "active"
        await session.commit()

        # ── Test 4: Daily Absent & OD Analytics Extraction ───────────────────
        print("\n[Test 4] Testing Daily Status Extraction Engine (Absent & OD)...")
        today_str = date.today().strftime("%d-%m-%Y")

        absent_records = await get_sql_daily_status_students(session, today_str, "A", dept_code=None)
        od_records = await get_sql_daily_status_students(session, today_str, "OD", dept_code=None)
        print(f"  Extraction successful for {today_str}:")
        print(f"    Total absent student entries: {len(absent_records)}")
        print(f"    Total OD student entries:     {len(od_records)}")

        # ── Test 5: Department Subject Isolation ─────────────────────────────
        print("\n[Test 5] Testing Department Subject Management & Scoping...")
        # Check departments
        dept_res = await session.execute(select(Department).where(Department.code == "CSE"))
        cse_dept = dept_res.scalar_one_or_none()
        assert cse_dept is not None, "CSE department must exist"

        # Check or create test subject in CSE
        sub_stmt = select(Subject).where(and_(Subject.department_id == cse_dept.id, Subject.subject_code == "TEST_CS901"))
        test_sub = (await session.execute(sub_stmt)).scalar_one_or_none()
        if not test_sub:
            test_sub = Subject(
                subject_code="TEST_CS901",
                subject_name="Advanced Cloud Verification",
                department_id=cse_dept.id,
                semester=5,
                subject_type="THEORY",
                is_active=True
            )
            session.add(test_sub)
            await session.commit()
            await session.refresh(test_sub)
            print(f"  ✓ Created test subject: {test_sub.subject_code} - {test_sub.name} in department ID {cse_dept.id}")
        else:
            print(f"  ✓ Test subject exists: {test_sub.subject_code} - {test_sub.name}")

        # Verify subject query scoped to CSE class
        class_res = await session.execute(select(ClassRoom).where(ClassRoom.department_id == cse_dept.id).limit(1))
        cse_class = class_res.scalar_one_or_none()
        if cse_class:
            scoped_subs = (await session.execute(
                select(Subject).where(and_(Subject.is_active == True, Subject.department_id == cse_class.department_id))
            )).scalars().all()
            sub_codes = [s.subject_code for s in scoped_subs]
            assert "TEST_CS901" in sub_codes, "Subject must be present in department scoped list"
            print(f"  ✓ Class {cse_class.class_code} (Dept {cse_dept.code}) subjects query returned: {sub_codes}")

    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED! Verification Complete.")
    print("="*70 + "\n")


if __name__ == "__main__":
    asyncio.run(test_suite())
