# =============================================================================
# AttendTrax Enterprise – Pure Supabase PostgreSQL Baseline Hydrator
# hydrate_db.py – Establishes 10 Academic Departments & 13 Admin Accounts
# Zero mock cohorts, zero SQLite dependencies
# =============================================================================
import asyncio
import os
import sys

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from sqlalchemy import select
from database import init_db, get_session_factory
from models import Department, User
from auth import hash_password

DEPARTMENTS_DATA = [
    {"code": "CSE",   "name": "Department of Computer Science & Engineering", "hod_name": "Dr. Antony Sudha K (HOD CSE)"},
    {"code": "IT",    "name": "Department of Information Technology", "hod_name": "Dr. S.Banu Priya (HOD IT)"},
    {"code": "AIDS",  "name": "Department of Artificial Intelligence & Data Science", "hod_name": "Dr. A.Tamilarasan(HOD AI&DS)"},
    {"code": "ECE",   "name": "Department of Electronics & Communication Engineering", "hod_name": "Dr. Dinesh Babu (HOD ECE)"},
    {"code": "MECH",  "name": "Department of Mechanical Engineering", "hod_name": "Dr. V. Anand (HOD MECH)"},
    {"code": "EEE",   "name": "Department of Electrical & Electronics Engineering", "hod_name": "Dr. Baskar (HOD EEE)"},
    {"code": "CYBER", "name": "Department of Cyber Security", "hod_name": "Dr. Fathima (HOD CYBER)"},
    {"code": "AIML",  "name": "Department of Artificial Intelligence & Machine Learning", "hod_name": "Dr. T. Suresh (HOD AI&ML)"},
    {"code": "SH",    "name": "Department of Science & Humanities", "hod_name": "Dr.Devi (HOD S&H)"},
    {"code": "PLACEMENT", "name": "Department of Training & Placement", "hod_name": "Mr. Krishnamoorthy (Head - Training & Placement)"},
]


async def ensure_hydrated():
    """
    Ensures pure institutional baseline in Supabase PostgreSQL:
    - 10 Academic & Placement Departments
    - 3 Super Admin accounts: admin, principal, viceprincipal
    - 10 Department HOD accounts: hod.cse, hod.it, ..., hod.placement
    Does NOT seed dummy classes, faculty, or students.
    """
    try:
        await init_db()
        session_factory = get_session_factory()
        async with session_factory() as session:
            # 1. Ensure 10 Departments
            dept_id_map = {}
            for d in DEPARTMENTS_DATA:
                code = d["code"]
                stmt_d = select(Department).where(Department.code == code)
                dept = (await session.execute(stmt_d)).scalar_one_or_none()
                if not dept:
                    dept = Department(code=code, name=d["name"], is_active=True)
                    session.add(dept)
                    await session.flush()
                else:
                    dept.is_active = True
                    dept.name = d["name"]
                dept_id_map[code] = dept.id

            # Deactivate retired legacy departments (CIVIL, CSBS)
            stmt_legacy = select(Department).where(Department.code.in_(["CIVIL", "CSBS"]))
            legacy_depts = (await session.execute(stmt_legacy)).scalars().all()
            for ld in legacy_depts:
                ld.is_active = False

            # 2. Institutional Super Admins
            admin_hashes = {
                "principal": hash_password("Principal@2026"),
                "vp": hash_password("VP@2026"),
                "admin": hash_password("AttendTrax@2026"),
                "hod": hash_password("Hod@2026"),
            }
            super_admins = [
                ("principal", "Dr. Devaraju (Principal)", admin_hashes["principal"]),
                ("viceprincipal", "Dr. Basker (Vice Principal)", admin_hashes["vp"]),
                ("admin", "Central System Administrator", admin_hashes["admin"]),
            ]
            for uname, fname, pwd_h in super_admins:
                stmt = select(User).where(User.username == uname)
                u = (await session.execute(stmt)).scalar_one_or_none()
                if not u:
                    session.add(User(username=uname, full_name=fname, password_hash=pwd_h, role="SUPER_ADMIN", status="ACTIVE"))
                else:
                    u.full_name = fname
                    u.role = "SUPER_ADMIN"
                    u.status = "ACTIVE"

            # 3. Department HODs
            for d in DEPARTMENTS_DATA:
                code = d["code"]
                dept_id = dept_id_map[code]
                hod_uname = f"hod.{code.lower()}"
                stmt_h = select(User).where(User.username == hod_uname)
                hod_u = (await session.execute(stmt_h)).scalar_one_or_none()
                if not hod_u:
                    hod_u = User(
                        username=hod_uname,
                        full_name=d["hod_name"],
                        password_hash=admin_hashes["hod"],
                        role="DEPT_ADMIN",
                        department_id=dept_id,
                        status="ACTIVE"
                    )
                    session.add(hod_u)
                    await session.flush()
                else:
                    hod_u.department_id = dept_id
                    hod_u.role = "DEPT_ADMIN"
                    hod_u.status = "ACTIVE"

                d_obj = await session.get(Department, dept_id)
                if d_obj:
                    d_obj.hod_user_id = hod_u.id

            await session.commit()
            print("[AUTO-HYDRATION] Institutional baseline verified: 10 Departments & 13 Admin accounts ready.")
    except Exception as e:
        print(f"[AUTO-HYDRATION ERROR] Failed: {e}")
        raise e


async def hydrate():
    """Alias for backwards compatibility."""
    await ensure_hydrated()


if __name__ == "__main__":
    asyncio.run(ensure_hydrated())
