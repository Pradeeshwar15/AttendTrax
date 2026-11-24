# =============================================================================
# backend/scripts/test_dynamic_department_subjects.py
# Automated Verification Suite for:
# 1. Department-Scoped Subject Creation (Placement, CSE, IT, etc.)
# 2. Dynamic Placement vs Academic Subject Resolution in Faculty API
# 3. Placement Attendance Submission with Dynamic Subject Topic
# =============================================================================
import os
import sys
from datetime import date

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
from sqlalchemy import select, and_, delete
from database import get_session_factory
from models import Subject, Department, ClassRoom, Student, User, PlacementAttendance
from routers.faculty_router import list_subjects, submit_attendance, SubmitAttendanceRequest, AttendanceEntry
from routers.admin_router import add_subject, AddSubjectRequest, list_all_subjects, delete_subject


async def run_suite():
    print("\n" + "="*75)
    print("⚡ AttendTrax Verification: Dynamic Department Subjects & Placement Flow")
    print("="*75 + "\n")

    session_factory = get_session_factory()
    async with session_factory() as session:
        # ── Step 1: Ensure PLACEMENT Department Exists ───────────────────────
        print("[Step 1] Verifying PLACEMENT Department exists in Supabase...")
        d_stmt = select(Department).where(Department.code == "PLACEMENT")
        plc_dept = (await session.execute(d_stmt)).scalar_one_or_none()
        assert plc_dept is not None, "PLACEMENT department must exist in database"
        print(f"  ✓ PLACEMENT Department ID: {plc_dept.id} ({plc_dept.name})")

        # ── Step 2: Add Dynamic Placement & CSE Subjects via Admin Handler ───
        print("\n[Step 2] Creating dynamic Placement & Academic subjects...")
        admin_user = {"role": "SUPER_ADMIN", "Username": "admin"}
        
        # 2a. Placement subject
        req_plc_sub = AddSubjectRequest(
            subject_id="PLC_PY501",
            subject_name="Full-Stack Python & Cloud Engineering",
            department_code="PLACEMENT",
            subject_type="TRAINING"
        )
        msg_plc = await add_subject(body=req_plc_sub, current_user=admin_user, db=session)
        print(f"  ✓ Added: {msg_plc['message']}")

        # 2b. CSE subject
        req_cse_sub = AddSubjectRequest(
            subject_id="CS_DIST502",
            subject_name="Distributed Cloud Storage",
            department_code="CSE",
            subject_type="THEORY"
        )
        msg_cse = await add_subject(body=req_cse_sub, current_user=admin_user, db=session)
        print(f"  ✓ Added: {msg_cse['message']}")

        # ── Step 3: Admin List Subjects Filtered by Department ─────────────────
        print("\n[Step 3] Verifying Admin Department-Filtered Subject Query...")
        plc_subs = await list_all_subjects(department_code="PLACEMENT", current_user=admin_user, db=session)
        plc_codes = [s["SubjectID"] for s in plc_subs]
        print(f"  Placement subjects count: {len(plc_subs)} -> {plc_codes}")
        assert "PLC_PY501" in plc_codes, "PLC_PY501 must be returned in PLACEMENT subjects filter"
        assert "CS_DIST502" not in plc_codes, "CS_DIST502 must NOT be in PLACEMENT subjects filter"

        cse_subs = await list_all_subjects(department_code="CSE", current_user=admin_user, db=session)
        cse_codes = [s["SubjectID"] for s in cse_subs]
        print(f"  CSE subjects count: {len(cse_subs)} -> {cse_codes}")
        assert "CS_DIST502" in cse_codes, "CS_DIST502 must be returned in CSE subjects filter"
        assert "PLC_PY501" not in cse_codes, "PLC_PY501 must NOT be in CSE subjects filter"

        # ── Step 4: Faculty Dynamic Subject Resolution ────────────────────────
        print("\n[Step 4] Verifying Dynamic Subject Resolution in Faculty API...")
        # Get a CSE class
        cls = (await session.execute(select(ClassRoom).where(ClassRoom.class_code == "CSE2A"))).scalar_one_or_none()
        if not cls:
            cls = (await session.execute(select(ClassRoom).limit(1))).scalar_one_or_none()
        assert cls is not None

        # 4a. Query as Academic Faculty (CSE Faculty)
        acad_faculty_user = {"role": "faculty", "sub": "faculty.cse", "department": "CSE"}
        acad_res = await list_subjects(class_id=cls.class_code, current_user=acad_faculty_user, db=session)
        acad_sub_ids = [s["SubjectID"] for s in acad_res]
        print(f"  Academic Faculty received subjects for {cls.class_code}: {acad_sub_ids}")
        assert "CS_DIST502" in acad_sub_ids, "Academic faculty must receive CSE subjects for CSE class"
        assert "PLC_PY501" not in acad_sub_ids, "Academic faculty must NOT receive Placement subjects"

        # 4b. Query as Placement Faculty for the SAME CSE class
        plc_faculty_user = {"role": "faculty", "sub": "faculty.placement", "department": "PLACEMENT"}
        plc_res = await list_subjects(class_id=cls.class_code, current_user=plc_faculty_user, db=session)
        plc_sub_ids = [s["SubjectID"] for s in plc_res]
        print(f"  Placement Faculty received subjects for {cls.class_code}: {plc_sub_ids}")
        assert "PLC_PY501" in plc_sub_ids, "Placement faculty MUST receive Placement subjects regardless of class"
        assert "CS_DIST502" not in plc_sub_ids, "Placement faculty must NOT receive CSE academic subjects"
        print("  ✓ Strict dynamic scoping verified: Placement faculty receives Placement subjects across any class!")

        # ── Step 5: Test Placement Attendance Submission with Dynamic Subject ─
        print("\n[Step 5] Testing Placement Attendance Submission with Dynamic Subject...")
        today = date.today()
        test_slot = "technical_assessment"
        topic_title = "PLC_PY501 - Full-Stack Python & Cloud Engineering"

        # Clean prior test records
        await session.execute(delete(PlacementAttendance).where(
            and_(PlacementAttendance.class_id == cls.id, PlacementAttendance.attendance_date == today, PlacementAttendance.slot_type == test_slot)
        ))
        await session.commit()

        # Fetch active class students
        stus = (await session.execute(select(Student).where(and_(Student.class_id == cls.id, Student.status == "ACTIVE")))).scalars().all()
        mock_entries = [AttendanceEntry(reg_no=s.reg_no, status="P") for s in stus[:5]] # test with first 5

        # Get faculty user id
        fac = (await session.execute(select(User).limit(1))).scalar_one_or_none()

        req = SubmitAttendanceRequest(
            class_id=cls.class_code,
            subject_id=topic_title,
            hour=test_slot,
            attendance=mock_entries
        )
        current_user_plc = {
            "user_id": fac.id,
            "sub": "faculty.placement",
            "role": "faculty",
            "department": "PLACEMENT"
        }

        resp = await submit_attendance(body=req, current_user=current_user_plc, db=session)
        print(f"  ✓ Submission response: {resp}")
        assert resp["status"] == "CONFIRMED"
        assert resp["inserted"] == len(mock_entries)

        # Verify saved in placement_attendance table with topic
        saved_recs = (await session.execute(
            select(PlacementAttendance).where(
                and_(PlacementAttendance.class_id == cls.id, PlacementAttendance.attendance_date == today, PlacementAttendance.slot_type == test_slot)
            )
        )).scalars().all()
        assert len(saved_recs) == len(mock_entries)
        for r in saved_recs:
            assert r.training_topic == topic_title
            assert r.slot_type == test_slot
        print(f"  ✓ Successfully verified {len(saved_recs)} records saved in 'placement_attendance' with topic='{topic_title}' and slot='{test_slot}'")

        # ── Step 6: Cleanup Test Data ─────────────────────────────────────────
        print("\n[Step 6] Cleaning up test records...")
        await session.execute(delete(PlacementAttendance).where(
            and_(PlacementAttendance.class_id == cls.id, PlacementAttendance.attendance_date == today, PlacementAttendance.slot_type == test_slot)
        ))
        # Deactivate test subjects
        await delete_subject(subject_id="PLC_PY501", _=admin_user, db=session)
        await delete_subject(subject_id="CS_DIST502", _=admin_user, db=session)
        await session.commit()
        print("  ✓ Cleanup complete.")

        print("\n" + "="*75)
        print("🎉 ALL TESTS PASSED! Dynamic Department Subjects & Placement Flow Verified.")
        print("="*75 + "\n")


if __name__ == "__main__":
    asyncio.run(run_suite())
