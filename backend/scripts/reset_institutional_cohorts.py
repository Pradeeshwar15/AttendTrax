# =============================================================================
# AttendTrax Enterprise – Institutional Reset & Academic Cohort Purge CLI
# reset_institutional_cohorts.py – Clears Students, Classes & Past Attendances
# =============================================================================
import asyncio
import os
import sys

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Ensure backend directory is in python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import select, delete, func, update
from database import init_db, get_session_factory
from models import (
    Department, User, ClassRoom, Student, Faculty, Subject,
    AttendanceSession, AttendanceRecord, StudentLeave, FacultyAllocation, AuditLog,
    HostelGatePass, Notification
)


async def reset_cohorts():
    print("=" * 65)
    print("ATTENDTRAX ENTERPRISE - INSTITUTIONAL RESET & COHORT PURGE")
    print("=" * 65)

    await init_db()
    session_factory = get_session_factory()

    async with session_factory() as session:
        print("[1/5] Checking baseline institutional state...")
        dept_cnt = (await session.execute(select(func.count(Department.id)))).scalar() or 0
        fac_cnt = (await session.execute(select(func.count(Faculty.id)))).scalar() or 0
        cls_cnt = (await session.execute(select(func.count(ClassRoom.id)))).scalar() or 0
        std_cnt = (await session.execute(select(func.count(Student.id)))).scalar() or 0
        att_cnt = (await session.execute(select(func.count(AttendanceRecord.id)))).scalar() or 0
        stu_usr_cnt = (await session.execute(select(func.count(User.id)).where(User.role == "STUDENT"))).scalar() or 0

        print(f"  Current Database Counts:")
        print(f"    - Departments: {dept_cnt}")
        print(f"    - Faculty: {fac_cnt}")
        print(f"    - Classes: {cls_cnt}")
        print(f"    - Students: {std_cnt}")
        print(f"    - Student User Logins: {stu_usr_cnt}")
        print(f"    - Attendance Records: {att_cnt}")

        print("\n[2/5] Purging attendance records, sessions, gate passes, and leaves in SQL...")
        del_att_rec = await session.execute(delete(AttendanceRecord))
        del_att_ses = await session.execute(delete(AttendanceSession))
        del_gate_pass = await session.execute(delete(HostelGatePass))
        del_stu_lve = await session.execute(delete(StudentLeave))
        del_fac_alc = await session.execute(delete(FacultyAllocation))

        # Disconnect student user IDs from audit logs (set user_id = NULL) and delete student notifications
        subq_stu_uids = select(User.id).where(User.role == "STUDENT")
        await session.execute(update(AuditLog).where(AuditLog.user_id.in_(subq_stu_uids)).values(user_id=None))
        del_stu_notifs = await session.execute(delete(Notification).where(Notification.user_id.in_(subq_stu_uids)))

        print("\n[3/5] Purging student profiles, student user accounts & classes in SQL...")
        del_students = await session.execute(delete(Student))
        del_users = await session.execute(delete(User).where(User.role == "STUDENT"))
        del_classes = await session.execute(delete(ClassRoom))

        # Record audit log entry
        audit = AuditLog(
            user_id=1,
            action="PURGE_ACADEMIC_COHORTS",
            target_entity="STUDENTS_CLASSES_ATTENDANCE",
            target_id=0,
            old_values={
                "deleted_classes": cls_cnt,
                "deleted_students": std_cnt,
                "deleted_student_users": stu_usr_cnt,
                "deleted_attendance_records": att_cnt,
            },
            new_values={
                "scope": "ALL_STUDENTS_AND_CLASSES",
                "status": "PURGED_FOR_FRESH_ONBOARDING",
                "performed_by": "CLI_ADMIN_RESET",
            }
        )
        session.add(audit)
        await session.commit()
        print("  ✓ Database deletion committed successfully.")

    # Remove any stray legacy SQLite database file
    sqlite_path = os.path.join(backend_dir, "attendtrax.db")
    if os.path.exists(sqlite_path):
        os.remove(sqlite_path)
        print("  ✓ Legacy SQLite attendtrax.db purged.")

    print("\n[5/5] Verifying post-reset institutional integrity...")
    async with session_factory() as session:
        post_dept = (await session.execute(select(func.count(Department.id)))).scalar() or 0
        post_fac = (await session.execute(select(func.count(Faculty.id)))).scalar() or 0
        post_cls = (await session.execute(select(func.count(ClassRoom.id)))).scalar() or 0
        post_std = (await session.execute(select(func.count(Student.id)))).scalar() or 0
        post_stu_usr = (await session.execute(select(func.count(User.id)).where(User.role == "STUDENT"))).scalar() or 0
        post_att = (await session.execute(select(func.count(AttendanceRecord.id)))).scalar() or 0
        post_hod = (await session.execute(select(func.count(User.id)).where(User.role == "DEPT_ADMIN"))).scalar() or 0
        post_exec = (await session.execute(select(func.count(User.id)).where(User.role == "SUPER_ADMIN"))).scalar() or 0

        print(f"  Post-Reset Database Counts:")
        print(f"    - Active Departments: {post_dept} (Expected: 10)")
        print(f"    - Preserved Faculty: {post_fac} (Expected: 31)")
        print(f"    - Preserved HOD Accounts: {post_hod} (Expected: >= 10)")
        print(f"    - Preserved Super Admins: {post_exec} (Expected: 3)")
        print(f"    - Remaining Classes: {post_cls} (Expected: 0)")
        print(f"    - Remaining Students: {post_std} (Expected: 0)")
        print(f"    - Remaining Student Logins: {post_stu_usr} (Expected: 0)")
        print(f"    - Remaining Attendance Records: {post_att} (Expected: 0)")

        assert post_cls == 0, f"Expected 0 classes, got {post_cls}"
        assert post_std == 0, f"Expected 0 students, got {post_std}"
        assert post_stu_usr == 0, f"Expected 0 student user logins, got {post_stu_usr}"
        assert post_att == 0, f"Expected 0 attendance records, got {post_att}"
        assert post_dept >= 10, f"Departments corrupted! Got {post_dept}"
        assert post_fac >= 20, f"Faculty corrupted! Got {post_fac}"

    print("\n" + "=" * 65)
    print("SUCCESS: Institutional reset complete! System is 100% clean and ready.")
    print("=" * 65)


if __name__ == "__main__":
    asyncio.run(reset_cohorts())
