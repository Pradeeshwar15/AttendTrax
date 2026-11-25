# =============================================================================
# AttendTrax Enterprise – Automated Institutional Data Engine
# generate_auto_data.py – Generates Classes, Rosters, Subjects & Attendance
# Supports Anna University Institutional Standards & Placement Segregation
# =============================================================================
import asyncio
import os
import sys
import random
from datetime import datetime, date, timedelta

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy import select, func, and_
from database import init_db, get_session_factory
from hydrate_db import ensure_hydrated
from models import (
    Department, User, ClassRoom, Student, Faculty, Subject,
    FacultyAllocation, AttendanceSession, AttendanceRecord, PlacementAttendance
)
from auth import hash_password

STUDENT_FIRST_NAMES = [
    "Aarav", "Abhinav", "Aditi", "Ananya", "Arjun", "Ashwin", "Bhavna", "Deepak",
    "Divya", "Ganesh", "Gayathri", "Harish", "Hariharan", "Janani", "Karthik",
    "Kavya", "Keerthana", "Manoj", "Meenakshi", "Naveen", "Nithya", "Pooja",
    "Pradeep", "Praveen", "Priya", "Rahul", "Ramya", "Rithvik", "Sai", "Sanjay",
    "Saravanan", "Shalini", "Sneha", "Subhash", "Surya", "Swetha", "Vignesh",
    "Vijay", "Vikram", "Yuvraj"
]

STUDENT_LAST_NAMES = [
    "Kumar", "Rajan", "Sundaram", "Krishnan", "Murugan", "Subramanian", "Balaji",
    "Natarajan", "Chandran", "Iyer", "Moorthy", "Venkatesh", "Reddy", "Sharma",
    "Pillai", "Chettiar", "Mani", "Prasad", "Srinivasan", "Varadhan"
]

SAMPLE_CLASSES = [
    {"code": "CSE28A", "name": "III CSE A (Batch 2028)", "dept": "CSE", "year": 3, "sec": "A", "sem": 5, "dept_num": "104", "start": 1,  "count": 25},
    {"code": "CSE28B", "name": "III CSE B (Batch 2028)", "dept": "CSE", "year": 3, "sec": "B", "sem": 5, "dept_num": "104", "start": 26, "count": 25},
    {"code": "CSE29A", "name": "II CSE A (Batch 2029)", "dept": "CSE", "year": 2, "sec": "A", "sem": 3, "dept_num": "104", "start": 1,  "count": 20},
    {"code": "IT28A",  "name": "III IT A (Batch 2028)",  "dept": "IT",  "year": 3, "sec": "A", "sem": 5, "dept_num": "205", "start": 1,  "count": 20},
    {"code": "AIDS28A","name": "III AI&DS A (Batch 2028)","dept": "AIDS","year": 3, "sec": "A", "sem": 5, "dept_num": "243", "start": 1,  "count": 20},
]

SAMPLE_SUBJECTS = [
    {"code": "CS8501", "name": "Theory of Computation", "dept": "CSE", "sem": 5, "type": "THEORY"},
    {"code": "CS8591", "name": "Computer Networks", "dept": "CSE", "sem": 5, "type": "THEORY"},
    {"code": "CS8592", "name": "Object Oriented Analysis & Design", "dept": "CSE", "sem": 5, "type": "THEORY"},
    {"code": "CS8581", "name": "Networks Laboratory", "dept": "CSE", "sem": 5, "type": "LAB"},
    {"code": "IT8501", "name": "Web Technology Architecture", "dept": "IT", "sem": 5, "type": "THEORY"},
    {"code": "AD8501", "name": "Machine Learning Foundations", "dept": "AIDS", "sem": 5, "type": "THEORY"},
    # Placement Subjects
    {"code": "PLC_APT101", "name": "Quantitative Aptitude & Logical Reasoning", "dept": "PLACEMENT", "sem": 5, "type": "THEORY"},
    {"code": "PLC_COD201", "name": "Data Structures & Competitive Coding", "dept": "PLACEMENT", "sem": 5, "type": "THEORY"},
    {"code": "PLC_TECH301", "name": "Full-Stack Cloud & DevOps Engineering", "dept": "PLACEMENT", "sem": 5, "type": "THEORY"},
    {"code": "PLC_MOCK401", "name": "Mock Technical & HR Interview Practice", "dept": "PLACEMENT", "sem": 5, "type": "THEORY"},
]


async def generate_auto_data(dry_run: bool = False, days_of_attendance: int = 5):
    print("=" * 75)
    print("⚡ ATTENDTRAX ENTERPRISE – AUTOMATED INSTITUTIONAL DATA ENGINE")
    print("=" * 75)

    await init_db()
    # Step 1: Ensure baseline departments and admin roles
    print("\n[Step 1/5] Verifying baseline institutional departments & admin accounts...")
    await ensure_hydrated()

    session_factory = get_session_factory()
    random.seed(42)  # Consistent realistic data distribution

    async with session_factory() as session:
        # Load department map
        stmt_d = select(Department)
        departments = (await session.execute(stmt_d)).scalars().all()
        dept_map = {d.code: d.id for d in departments}

        # Step 2: Ensure Classes exist
        print("\n[Step 2/5] Creating / Verifying Academic Classes...")
        class_obj_map = {}
        for cinfo in SAMPLE_CLASSES:
            dept_id = dept_map.get(cinfo["dept"])
            if not dept_id:
                continue
            stmt_c = select(ClassRoom).where(ClassRoom.class_code == cinfo["code"])
            cls = (await session.execute(stmt_c)).scalar_one_or_none()
            if not cls:
                cls = ClassRoom(
                    department_id=dept_id,
                    class_code=cinfo["code"],
                    class_name=cinfo["name"],
                    year=cinfo["year"],
                    section=cinfo["sec"],
                    semester=cinfo["sem"],
                    academic_year="2026-2027",
                    status="ACTIVE"
                )
                session.add(cls)
                await session.flush()
                print(f"  ✓ Created Class: {cls.class_code} ({cls.class_name})")
            else:
                print(f"  • Found Class: {cls.class_code} ({cls.class_name})")
            class_obj_map[cinfo["code"]] = cls

        # Step 3: Ensure Subjects exist
        print("\n[Step 3/5] Creating / Verifying Department Subjects...")
        subject_obj_map = {}
        for sinfo in SAMPLE_SUBJECTS:
            dept_id = dept_map.get(sinfo["dept"])
            if not dept_id:
                continue
            stmt_s = select(Subject).where(Subject.subject_code == sinfo["code"])
            subj = (await session.execute(stmt_s)).scalar_one_or_none()
            if not subj:
                subj = Subject(
                    subject_code=sinfo["code"],
                    subject_name=sinfo["name"],
                    department_id=dept_id,
                    semester=sinfo["sem"],
                    subject_type=sinfo["type"],
                    is_active=True
                )
                session.add(subj)
                await session.flush()
                print(f"  ✓ Created Subject: {subj.subject_code} - {subj.subject_name} [{sinfo['dept']}]")
            else:
                print(f"  • Found Subject: {subj.subject_code} - {subj.subject_name} [{sinfo['dept']}]")
            subject_obj_map[sinfo["code"]] = subj

        # Step 4: Ensure Faculty accounts exist
        print("\n[Step 4/5] Creating / Verifying Faculty Accounts...")
        sample_faculty = [
            ("fathima.cse", "Dr. Fathima K", "CSE", "FAC_CSE01", "Professor & HOD"),
            ("suresh.cse", "Dr. T. Suresh", "CSE", "FAC_CSE02", "Associate Professor"),
            ("anitha.cse", "Ms. Anitha R", "CSE", "FAC_CSE03", "Assistant Professor"),
            ("banu.it", "Dr. S. Banu Priya", "IT", "FAC_IT01", "Professor & HOD"),
            ("placement.staff", "Mr. Krishnamoorthy", "PLACEMENT", "FAC_PLC01", "Head - Training & Placement"),
        ]
        faculty_user_map = {}
        default_pwd = hash_password("Faculty@2026")
        for uname, fname, dept_code, fac_code, desig in sample_faculty:
            dept_id = dept_map.get(dept_code)
            stmt_u = select(User).where(User.username == uname)
            u = (await session.execute(stmt_u)).scalar_one_or_none()
            if not u:
                u = User(
                    username=uname,
                    full_name=fname,
                    password_hash=default_pwd,
                    role="FACULTY",
                    department_id=dept_id,
                    status="ACTIVE"
                )
                session.add(u)
                await session.flush()
            faculty_user_map[uname] = u

            stmt_f = select(Faculty).where(Faculty.faculty_code == fac_code)
            fac = (await session.execute(stmt_f)).scalar_one_or_none()
            if not fac:
                fac = Faculty(
                    faculty_code=fac_code,
                    user_id=u.id,
                    department_id=dept_id,
                    designation=desig
                )
                session.add(fac)
                await session.flush()

        # Step 5: Populate Students per Class and Generate Attendance
        print("\n[Step 5/5] Generating Student Rosters & Multi-Day Attendance...")
        total_students_created = 0
        total_sessions_created = 0
        total_records_created = 0
        total_placement_created = 0

        std_pwd = hash_password("Student@2026")

        for cinfo in SAMPLE_CLASSES:
            cls = class_obj_map[cinfo["code"]]
            dept_id = dept_map[cinfo["dept"]]
            target_count = cinfo["count"]
            dept_num = cinfo["dept_num"]
            start_idx = cinfo["start"]
            base_year = "22" if cls.year == 3 else "23"

            # Check existing students in class
            stmt_st = select(Student).where(Student.class_id == cls.id)
            existing_students = (await session.execute(stmt_st)).scalars().all()
            existing_regnos = {s.reg_no for s in existing_students}

            class_students = list(existing_students)

            for i in range(start_idx, start_idx + target_count):
                reg_no = f"4101{base_year}{dept_num}{i:03d}"
                roll_no = f"{base_year}{cinfo['dept']}{i:03d}"

                if reg_no in existing_regnos:
                    continue

                # Check if student exists globally
                stmt_find = select(Student).where(Student.reg_no == reg_no)
                found_st = (await session.execute(stmt_find)).scalar_one_or_none()
                if found_st:
                    class_students.append(found_st)
                    existing_regnos.add(reg_no)
                    continue

                first = random.choice(STUDENT_FIRST_NAMES)
                last = random.choice(STUDENT_LAST_NAMES)
                full_name = f"{first} {last}"

                # Mark ~10% students inactive for placement willingness to test segregation
                willingness = "inactive" if (i % 8 == 0) else "active"

                # Create student user login if missing
                stmt_su = select(User).where(User.username == reg_no)
                stu_user = (await session.execute(stmt_su)).scalar_one_or_none()
                if not stu_user:
                    stu_user = User(
                        username=reg_no,
                        full_name=full_name,
                        password_hash=std_pwd,
                        role="STUDENT",
                        department_id=dept_id,
                        status="ACTIVE"
                    )
                    session.add(stu_user)
                    await session.flush()

                student = Student(
                    reg_no=reg_no,
                    roll_no=roll_no,
                    name=full_name,
                    user_id=stu_user.id,
                    class_id=cls.id,
                    department_id=dept_id,
                    residence_type="HOSTELLER" if (i % 3 == 0) else "DAY_SCHOLAR",
                    placement_willingness=willingness,
                    status="ACTIVE"
                )
                session.add(student)
                await session.flush()
                class_students.append(student)
                existing_regnos.add(reg_no)
                total_students_created += 1

            print(f"  ✓ {cls.class_code}: {len(class_students)} students enrolled.")

            # Generate Attendance for past N weekdays
            dept_subjects = [s for s in SAMPLE_SUBJECTS if s["dept"] == cinfo["dept"]]
            cse_fac_user = faculty_user_map["suresh.cse"]
            plc_fac_user = faculty_user_map["placement.staff"]

            today = date.today()
            recorded_dates = []
            cur_d = today
            while len(recorded_dates) < days_of_attendance:
                if cur_d.weekday() < 5:
                    recorded_dates.append(cur_d)
                cur_d -= timedelta(days=1)
            recorded_dates.reverse()

            for d in recorded_dates:
                # 1. Academic Daily Session
                subj = subject_obj_map.get(dept_subjects[0]["code"]) if dept_subjects else None
                subj_id = subj.id if subj else None

                stmt_ses = select(AttendanceSession).where(
                    and_(
                        AttendanceSession.class_id == cls.id,
                        AttendanceSession.session_date == d,
                        AttendanceSession.slot_hour == "DAY"
                    )
                )
                session_obj = (await session.execute(stmt_ses)).scalar_one_or_none()

                if not session_obj:
                    session_obj = AttendanceSession(
                        class_id=cls.id,
                        subject_id=subj_id,
                        faculty_id=cse_fac_user.id,
                        session_date=d,
                        slot_hour="DAY",
                        session_type="DAILY",
                        lock_status="LOCKED"
                    )
                    session.add(session_obj)
                    await session.flush()
                    total_sessions_created += 1

                    for idx, st in enumerate(class_students):
                        if idx in (1, 2):  # Defaulter profiles (< 75% attendance)
                            stat = random.choices(["A", "P", "OD"], weights=[70, 20, 10])[0]
                        else:  # Normal class distribution (~90% attendance)
                            stat = random.choices(["P", "A", "OD"], weights=[88, 8, 4])[0]

                        rec = AttendanceRecord(
                            session_id=session_obj.id,
                            student_id=st.id,
                            status=stat,
                            remarks="Auto-Generated Attendance"
                        )
                        session.add(rec)
                        total_records_created += 1

                # 2. Placement Multi-Slot Attendance (Only for Placement Willing Students!)
                if cls.year in (3, 4):
                    slots_pool = ["training_classes", "technical_assessment", "leetcode_hackerrank", "mock_interview"]
                    selected_slot = slots_pool[d.day % len(slots_pool)]
                    topic_name = f"Placement {selected_slot.replace('_', ' ').title()}"

                    stmt_pl_chk = select(func.count(PlacementAttendance.id)).where(
                        and_(
                            PlacementAttendance.class_id == cls.id,
                            PlacementAttendance.attendance_date == d,
                            PlacementAttendance.slot_type == selected_slot
                        )
                    )
                    pl_exists = (await session.execute(stmt_pl_chk)).scalar() or 0

                    if pl_exists == 0:
                        for st in class_students:
                            if st.placement_willingness == "active":
                                stat = random.choices(["P", "A", "OD"], weights=[92, 6, 2])[0]
                                pl_rec = PlacementAttendance(
                                    student_id=st.id,
                                    class_id=cls.id,
                                    faculty_id=plc_fac_user.id,
                                    attendance_date=d,
                                    slot_type=selected_slot,
                                    training_topic=topic_name,
                                    status=stat,
                                    remarks="Placement Auto Data"
                                )
                                session.add(pl_rec)
                                total_placement_created += 1

        if not dry_run:
            await session.commit()
            print("\n" + "=" * 75)
            print("🎉 AUTO DATA INGESTION COMPLETE & COMMITTED TO SUPABASE POSTGRESQL!")
            print(f"  ✓ Students Created:           {total_students_created}")
            print(f"  ✓ Academic Sessions Created:   {total_sessions_created}")
            print(f"  ✓ Attendance Records Created:  {total_records_created}")
            print(f"  ✓ Placement Records Created:   {total_placement_created}")
            print("=" * 75)
        else:
            await session.rollback()
            print("\n[DRY RUN] Simulation complete. Changes discarded.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AttendTrax Automated Institutional Data Generator")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without committing to database")
    parser.add_argument("--days", type=int, default=5, help="Number of weekdays of attendance to generate")
    args = parser.parse_args()

    asyncio.run(generate_auto_data(dry_run=args.dry_run, days_of_attendance=args.days))
