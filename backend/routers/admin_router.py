import calendar
import csv
import io
import re
import time
import uuid
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select, and_, or_, desc, case, func, insert
from sqlalchemy.ext.asyncio import AsyncSession

from auth import hash_password, hash_passwords_bulk
from database import get_db
from dependencies import require_role
from models import User, Faculty, Department, ClassRoom, Student, AttendanceSession, AttendanceRecord, Subject
from services.sql_analytics import (
    compute_sql_admin_analytics,
    get_sql_class_attendance_report,
    get_sql_class_matrix,
    get_sql_daily_attendance_for_edit,
    update_sql_daily_attendance,
    get_sql_date_attendance_overview,
    get_ist_today_str,
    parse_date_str,
    ALL_HOURS,
)

def _classes_match(a: str, b: str) -> bool:
    return str(a or "").upper().replace(" ", "").replace("-", "").replace("_", "") == str(b or "").upper().replace(" ", "").replace("-", "").replace("_", "")

router = APIRouter(prefix="/admin", tags=["Admin"])

_admin_dep = Depends(require_role("ADMIN", "SUPER_ADMIN", "DEPT_ADMIN"))
_super_admin_dep = Depends(require_role("ADMIN", "SUPER_ADMIN"))


# ── Helpers for Excel column resolution ───────────────────────────────────────
def _find_col(candidates: List[str], raw_headers: List[str]) -> int:
    """Case-insensitive, punctuation/space/underscore-agnostic column finder."""
    norm = lambda s: str(s or "").lower().replace(" ", "").replace("_", "").replace(".", "").replace("-", "").replace("(", "").replace(")", "")
    norm_raw = [norm(h) for h in raw_headers]
    for c in candidates:
        norm_c = norm(c)
        if norm_c in norm_raw:
            return norm_raw.index(norm_c)
    return -1


def _parse_date_cell(val) -> str:
    """Normalize various date formats into DD-MM-YYYY."""
    if isinstance(val, (datetime, date)):
        return val.strftime("%d-%m-%Y")
    val_str = str(val).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%b-%Y"):
        try:
            return datetime.strptime(val_str, fmt).strftime("%d-%m-%Y")
        except ValueError:
            pass
    return val_str


# ─────────────────────────────────────────────────────────────────────────────
# DEPARTMENT NORMALIZATION & RBAC SCOPING
# ─────────────────────────────────────────────────────────────────────────────
DEPT_ALIAS_MAP = {
    "AI & DS": "AIDS",
    "AI&DS": "AIDS",
    "AIDS": "AIDS",
    "CYBER SECURITY": "CYBER",
    "CYBERSECURITY": "CYBER",
    "CYBER": "CYBER",
    "AI & ML": "AIML",
    "AI&ML": "AIML",
    "AIML": "AIML",
    "S & H": "SH",
    "S&H": "SH",
    "SH": "SH",
    "CSE": "CSE",
    "IT": "IT",
    "ECE": "ECE",
    "EEE": "EEE",
    "MECH": "MECH",
    "MECHANICAL": "MECH",
    "PLACEMENT": "PLACEMENT",
    "TRAINING & PLACEMENT": "PLACEMENT",
    "T&P": "PLACEMENT",
}

def _normalize_dept_code(code: str) -> str:
    clean = str(code or "").strip().upper()
    return DEPT_ALIAS_MAP.get(clean, clean.replace(" ", "").replace("&", ""))


def _resolve_hod_dept_code(current_user: dict) -> str:
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    username = (current_user.get("Username") or current_user.get("sub") or "").lower()
    if user_role == "DEPT_ADMIN":
        if username.startswith("hod."):
            dept_part = username.replace("hod.", "").upper()
            return _normalize_dept_code(dept_part)
        dept_id = current_user.get("department_id")
        dept_map = {
            1: "CSE", 2: "ECE", 3: "EEE", 4: "MECH", 6: "IT", 7: "AIDS",
            10: "PLACEMENT", 12: "CYBER", 13: "AIML", 14: "SH"
        }
        if dept_id and str(dept_id).isdigit():
            return dept_map.get(int(dept_id), "CSE")
        if isinstance(dept_id, str):
            return _normalize_dept_code(dept_id)
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# CLASSES
# ─────────────────────────────────────────────────────────────────────────────
class AddClassRequest(BaseModel):
    class_id: str
    class_name: str
    department_code: Optional[str] = None
    year: Optional[str] = "1"
    section: Optional[str] = "A"
    semester: Optional[str] = "1"
    academic_year: Optional[str] = "2026-2027"


@router.get("/classes")
async def list_all_classes(
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    stmt = (
        select(ClassRoom, Department)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.status == "ACTIVE")
    )
    if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
        stmt = stmt.where(Department.code == hod_dept)

    res = await db.execute(stmt)
    rows = res.all()

    sql_classes = [
        {
            "ClassID": cls_obj.class_code,
            "ClassName": cls_obj.class_name,
            "Year": str(cls_obj.year),
            "Section": cls_obj.section,
            "Semester": str(cls_obj.semester),
            "Department": dept_obj.code,
            "Status": cls_obj.status
        }
        for cls_obj, dept_obj in rows
    ]
    return sorted(sql_classes, key=lambda c: str(c.get("ClassID", "")))


@router.post("/classes")
async def add_class(
    body: AddClassRequest,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    # 1. Determine target department
    target_dept_code = ""
    if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
        target_dept_code = hod_dept
    else:
        if body.department_code and body.department_code.strip():
            target_dept_code = _normalize_dept_code(body.department_code)
        else:
            cid_up = body.class_id.strip().upper()
            for d in ["CSE", "ECE", "EEE", "MECH", "IT", "AIDS", "CYBER", "AIML", "SH", "PLACEMENT"]:
                if cid_up.startswith(d):
                    target_dept_code = d
                    break
            if not target_dept_code:
                target_dept_code = hod_dept or "CSE"

    clean_cid = body.class_id.strip().upper()

    # Sandboxing validation: Academic HOD cannot create a class for another department
    if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
        for other_dept in ["CSE", "ECE", "EEE", "MECH", "IT", "AIDS", "CYBER", "AIML", "SH"]:
            if other_dept != hod_dept and clean_cid.startswith(other_dept):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: HOD of {hod_dept} cannot create classes for {other_dept}."
                )
        if not clean_cid.startswith(hod_dept):
            clean_cid = f"{hod_dept}{clean_cid}"

    # 2. Lookup Department in SQL
    stmt_dept = select(Department).where(Department.code == target_dept_code)
    dept_obj = (await db.execute(stmt_dept)).scalar_one_or_none()
    if not dept_obj:
        stmt_any = select(Department).where(Department.is_active == True)
        dept_obj = (await db.execute(stmt_any)).scalars().first()
        if not dept_obj:
            raise HTTPException(status_code=400, detail=f"Department '{target_dept_code}' not found.")

    # 3. Check if class_code already exists
    stmt_chk = select(ClassRoom).where(ClassRoom.class_code == clean_cid)
    existing_cls = (await db.execute(stmt_chk)).scalar_one_or_none()
    yr = int(body.year) if str(body.year).isdigit() else 1
    sem = int(body.semester) if str(body.semester).isdigit() else 1
    sec = str(body.section or "A").strip().upper()

    if existing_cls:
        if existing_cls.status == "ACTIVE":
            raise HTTPException(status_code=400, detail=f"Class with ID '{clean_cid}' already exists.")
        else:
            existing_cls.status = "ACTIVE"
            existing_cls.class_name = body.class_name
            existing_cls.department_id = dept_obj.id
            existing_cls.year = yr
            existing_cls.section = sec
            existing_cls.semester = sem
            await db.commit()
    else:
        new_cls = ClassRoom(
            department_id=dept_obj.id,
            class_code=clean_cid,
            class_name=body.class_name,
            year=yr,
            section=sec,
            semester=sem,
            academic_year=body.academic_year or "2026-2027",
            status="ACTIVE"
        )
        db.add(new_cls)
        await db.commit()

    _ADMIN_ANALYTICS_CACHE.clear()

    return {
        "status": "success",
        "message": f"Class '{body.class_name}' ({clean_cid}) successfully created for {target_dept_code} department.",
        "class_id": clean_cid,
        "department": target_dept_code
    }


class RenameClassRequest(BaseModel):
    new_name: str


@router.patch("/classes/{class_id}/rename")
async def rename_class(
    class_id: str,
    body: RenameClassRequest,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)
    clean_cid = class_id.strip().upper()

    stmt = (
        select(ClassRoom, Department)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.class_code == clean_cid)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row:
        cls_obj, dept_obj = row
        if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
            if dept_obj.code != hod_dept:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: HOD of {hod_dept} cannot rename classes belonging to {dept_obj.code}."
                )
        cls_obj.class_name = body.new_name
        await db.commit()

    _ADMIN_ANALYTICS_CACHE.clear()
    return {"status": "success", "message": f"Class '{clean_cid}' renamed to '{body.new_name}'."}


@router.delete("/classes/{class_id}")
async def deactivate_class(
    class_id: str,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)
    clean_cid = class_id.strip().upper()

    stmt = (
        select(ClassRoom, Department)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.class_code == clean_cid)
    )
    res = await db.execute(stmt)
    row = res.first()
    if row:
        cls_obj, dept_obj = row
        if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
            if dept_obj.code != hod_dept:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: HOD of {hod_dept} cannot delete classes belonging to {dept_obj.code}."
                )
        cls_obj.status = "INACTIVE"
        await db.commit()
    elif user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
        if not clean_cid.startswith(hod_dept):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: HOD of {hod_dept} cannot delete classes belonging to other departments."
            )

    _ADMIN_ANALYTICS_CACHE.clear()
    return {"status": "success", "message": f"Class '{clean_cid}' deactivated."}


# ─────────────────────────────────────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────────────────────────────────────
class AddSubjectRequest(BaseModel):
    subject_id: str
    class_id: str
    subject_name: str
    faculty_id: Optional[str] = ""


@router.get("/subjects")
async def list_all_subjects(
    class_id: Optional[str] = None,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Subject).where(Subject.status == "ACTIVE").order_by(Subject.subject_code)
    subjs = (await db.execute(stmt)).scalars().all()
    return [{"SubjectID": s.subject_code, "SubjectName": s.name} for s in subjs]


@router.get("/classes/{class_id}/subjects")
async def list_subjects_for_class(
    class_id: str,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Subject).where(Subject.status == "ACTIVE").order_by(Subject.subject_code)
    subjs = (await db.execute(stmt)).scalars().all()
    return [{"SubjectID": s.subject_code, "SubjectName": s.name} for s in subjs]


@router.post("/subjects")
async def add_subject(
    body: AddSubjectRequest,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db),
):
    clean_code = body.subject_id.strip().upper()
    stmt = select(Subject).where(Subject.subject_code == clean_code)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.name = body.subject_name.strip()
        existing.status = "ACTIVE"
    else:
        new_sub = Subject(
            subject_code=clean_code,
            name=body.subject_name.strip(),
            department_id=1,
            status="ACTIVE"
        )
        db.add(new_sub)
    await db.commit()
    return {"message": f"Subject '{body.subject_name}' added."}


@router.delete("/subjects/{subject_id}")
async def delete_subject(
    subject_id: str,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db),
):
    clean_code = subject_id.strip().upper()
    stmt = select(Subject).where(Subject.subject_code == clean_code)
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing:
        existing.status = "INACTIVE"
        await db.commit()
    return {"message": "Subject deactivated."}


# ─────────────────────────────────────────────────────────────────────────────
# STUDENTS
# ─────────────────────────────────────────────────────────────────────────────
class AddStudentRequest(BaseModel):
    reg_no: str
    name: str
    class_id: str
    class_name: Optional[str] = ""
    # Student login credentials
    username: Optional[str] = None   # defaults to name or reg_no
    password: Optional[str] = None   # defaults to reg_no


@router.get("/students")
async def list_all_students(
    class_id: Optional[str] = None,
    department_code: Optional[str] = None,
    year: Optional[str] = None,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db),
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    stmt = (
        select(Student, ClassRoom, Department)
        .join(ClassRoom, Student.class_id == ClassRoom.id)
        .join(Department, Student.department_id == Department.id)
        .where(Student.status == "ACTIVE")
        .order_by(ClassRoom.class_code, Student.reg_no)
    )

    if class_id and class_id.strip().upper() != "ALL":
        clean_cid = class_id.strip().upper()
        stmt = stmt.where(ClassRoom.class_code == clean_cid)

    if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
        stmt = stmt.where(Department.code == hod_dept)
    elif department_code and department_code.strip().upper() != "ALL":
        clean_dept = _normalize_dept_code(department_code)
        stmt = stmt.where(Department.code == clean_dept)

    if year and str(year).strip():
        yr_val = int(year) if str(year).isdigit() else 1
        stmt = stmt.where(ClassRoom.year == yr_val)

    rows = (await db.execute(stmt)).all()
    return [
        {
            "RegNo": s.reg_no,
            "reg_no": s.reg_no,
            "Name": s.name,
            "name": s.name,
            "ClassID": c.class_code,
            "class_id": c.class_code,
            "ClassName": c.class_name,
            "Department": d.code,
            "Year": str(c.year),
            "Section": c.section,
            "Semester": str(c.semester),
            "Status": s.status,
        }
        for s, c, d in rows
    ]


@router.get("/classes/{class_id}/students")
async def list_students(
    class_id: str,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db)
):
    clean_cid = class_id.strip().upper()
    stmt = (
        select(Student)
        .join(ClassRoom, Student.class_id == ClassRoom.id)
        .where(and_(ClassRoom.class_code == clean_cid, Student.status == "ACTIVE"))
        .order_by(Student.reg_no)
    )
    students = (await db.execute(stmt)).scalars().all()
    return [{"RegNo": s.reg_no, "reg_no": s.reg_no, "Name": s.name, "name": s.name, "ClassID": clean_cid} for s in students]


@router.post("/students")
async def add_student(
    body: AddStudentRequest,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)
    clean_cid = body.class_id.strip().upper()

    # Sandboxing: HOD cannot add student to a class of another department
    if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
        if not clean_cid.startswith(hod_dept):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: HOD of {hod_dept} cannot add students to class {clean_cid}."
            )

    # 1. Lookup class in SQL
    stmt_cls = (
        select(ClassRoom, Department)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.class_code == clean_cid)
    )
    res = await db.execute(stmt_cls)
    cls_row = res.first()

    if not cls_row:
        # If class not in SQL, resolve department and create it
        target_dept_code = hod_dept or "CSE"
        for d in ["CSE", "ECE", "EEE", "MECH", "IT", "AIDS", "CYBER", "AIML", "SH"]:
            if clean_cid.startswith(d):
                target_dept_code = d
                break
        stmt_d = select(Department).where(Department.code == target_dept_code)
        dept_obj = (await db.execute(stmt_d)).scalar_one_or_none()
        if not dept_obj:
            dept_obj = (await db.execute(select(Department))).scalars().first()
        new_c = ClassRoom(
            department_id=dept_obj.id,
            class_code=clean_cid,
            class_name=body.class_name or clean_cid,
            year=1,
            section="A",
            semester=1,
            status="ACTIVE"
        )
        db.add(new_c)
        await db.commit()
        await db.refresh(new_c)
        cls_id_fk = new_c.id
        dept_id_fk = dept_obj.id
    else:
        cls_obj, dept_obj = cls_row
        cls_id_fk = cls_obj.id
        dept_id_fk = dept_obj.id

    clean_regno = body.reg_no.strip()
    username = (body.username or clean_regno).strip()
    pwd = (body.password or f"{clean_regno}@2026").strip()
    pwd_hash = hash_password(pwd)

    # 2. Check and insert User in SQL
    stmt_u = select(User).where(User.username == username)
    u_obj = (await db.execute(stmt_u)).scalar_one_or_none()
    if not u_obj:
        u_obj = User(
            username=username,
            full_name=body.name.strip(),
            password_hash=pwd_hash,
            role="STUDENT",
            department_id=dept_id_fk,
            status="ACTIVE"
        )
        db.add(u_obj)
        await db.flush()
    else:
        u_obj.password_hash = pwd_hash
        u_obj.status = "ACTIVE"
        u_obj.department_id = dept_id_fk

    # 3. Check and insert Student in SQL
    stmt_s = select(Student).where(Student.reg_no == clean_regno)
    st_obj = (await db.execute(stmt_s)).scalar_one_or_none()
    if not st_obj:
        st_obj = Student(
            reg_no=clean_regno,
            user_id=u_obj.id,
            class_id=cls_id_fk,
            department_id=dept_id_fk,
            name=body.name.strip(),
            residence_type="DAY_SCHOLAR",
            status="ACTIVE"
        )
        db.add(st_obj)
    else:
        st_obj.class_id = cls_id_fk
        st_obj.department_id = dept_id_fk
        st_obj.name = body.name.strip()
        st_obj.status = "ACTIVE"

    await db.commit()
    _ADMIN_ANALYTICS_CACHE.clear()
    return {"message": f"Student '{body.name}' ({clean_regno}) added with login '{username}'."}


@router.delete("/students/{reg_no}")
async def deactivate_student(
    reg_no: str,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db)
):
    clean_rn = reg_no.strip()
    stmt = select(Student).where(Student.reg_no == clean_rn)
    s_obj = (await db.execute(stmt)).scalar_one_or_none()
    if s_obj:
        s_obj.status = "INACTIVE"
        await db.commit()
    return {"message": "Student deactivated."}


# ─────────────────────────────────────────────────────────────────────────────
# FACULTY ACCOUNTS (SANDBOXED BY DEPARTMENT)
# ─────────────────────────────────────────────────────────────────────────────
class AddFacultyRequest(BaseModel):
    faculty_id: str
    name: str
    username: str
    password: str
    department: Optional[str] = None
    designation: Optional[str] = "Assistant Professor"


@router.get("/faculty")
async def list_all_faculty(
    department_code: Optional[str] = None,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db),
):
    """
    Department-scoped faculty directory:
    - DEPT_ADMIN (HOD): Strictly confined to their own department (e.g. CSE).
    - SUPER_ADMIN / ADMIN: Institutional overall view with optional branch filtering.
    """
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    if department_code and _normalize_dept_code(department_code) in ("CIVIL", "CSBS"):
        return []

    stmt = (
        select(Faculty, User, Department)
        .join(User, Faculty.user_id == User.id)
        .join(Department, Faculty.department_id == Department.id)
        .where(User.status == "ACTIVE")
        .where(Department.is_active == True)
        .order_by(Department.code, User.full_name)
    )

    if user_role == "DEPT_ADMIN" and hod_dept:
        # Strict Sandbox: HOD cannot see other departments
        stmt = stmt.where(Department.code == hod_dept)
    elif department_code and department_code.strip().upper() != "ALL":
        target_code = _normalize_dept_code(department_code)
        stmt = stmt.where(Department.code == target_code)

    res = await db.execute(stmt)
    rows = res.all()

    faculty_list = []
    seen_usernames = set()
    for f, u, d in rows:
        seen_usernames.add(u.username.lower())
        faculty_list.append({
            "FacultyID": f.faculty_code,
            "Name": u.full_name,
            "Username": u.username,
            "Role": u.role,
            "Department": d.code,
            "DepartmentName": d.name,
            "Designation": f.designation or "Assistant Professor",
            "Status": u.status,
        })

    return faculty_list


@router.post("/faculty")
async def add_faculty(
    body: AddFacultyRequest,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db),
):
    """
    Atomic sandboxed faculty creation:
    - For HOD (DEPT_ADMIN): Automatically assigns and locks to the HOD's own department.
    - For Super Admin: Assigns to the selected department from the 9 official departments.
    - Persists User & Faculty records in PostgreSQL with entered name & credentials.
    """
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    # 1. Enforce Department Sandboxing
    if user_role == "DEPT_ADMIN" and hod_dept:
        target_dept_code = hod_dept
    else:
        raw_dept = body.department or "CSE"
        target_dept_code = _normalize_dept_code(raw_dept)

    # 2. Look up Department in DB
    d_stmt = select(Department).where(Department.code == target_dept_code)
    dept_obj = (await db.execute(d_stmt)).scalar_one_or_none()
    if not dept_obj:
        d_cse = select(Department).where(Department.code == "CSE")
        dept_obj = (await db.execute(d_cse)).scalar_one_or_none()

    dept_id = dept_obj.id if dept_obj else 1
    dept_code = dept_obj.code if dept_obj else target_dept_code

    uname = body.username.strip().lower()
    full_name = body.name.strip()
    fac_code = body.faculty_id.strip()
    desig = (body.designation or "Assistant Professor").strip()
    pwd_hash = hash_password(body.password.strip())

    # 3. Insert or Update User in PostgreSQL
    u_stmt = select(User).where(User.username == uname)
    u_obj = (await db.execute(u_stmt)).scalar_one_or_none()
    if not u_obj:
        u_obj = User(
            username=uname,
            full_name=full_name,
            password_hash=pwd_hash,
            role="FACULTY",
            department_id=dept_id,
            status="ACTIVE",
        )
        db.add(u_obj)
        await db.flush()
    else:
        u_obj.full_name = full_name
        u_obj.password_hash = pwd_hash
        u_obj.department_id = dept_id
        u_obj.role = "FACULTY"
        u_obj.status = "ACTIVE"
        await db.flush()

    # 4. Insert or Update Faculty Profile in PostgreSQL
    f_stmt = select(Faculty).where(or_(Faculty.faculty_code == fac_code, Faculty.user_id == u_obj.id))
    f_obj = (await db.execute(f_stmt)).scalar_one_or_none()
    if not f_obj:
        f_obj = Faculty(
            faculty_code=fac_code,
            user_id=u_obj.id,
            department_id=dept_id,
            designation=desig,
        )
        db.add(f_obj)
    else:
        f_obj.faculty_code = fac_code
        f_obj.department_id = dept_id
        f_obj.designation = desig

    await db.commit()

    return {
        "message": f"Faculty '{full_name}' ({fac_code}) added successfully in {dept_code} Department.",
        "faculty_id": fac_code,
        "department": dept_code,
        "name": full_name,
        "user_id": u_obj.id,
    }


@router.delete("/users/{username}")
async def delete_user(
    username: str,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db),
):
    """
    Sandboxed user deletion:
    - DEPT_ADMIN (HOD): Only allowed to delete faculty belonging to their own department.
    - SUPER_ADMIN: Can delete any user.
    """
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)
    target_uname = username.strip().lower()

    u_stmt = select(User, Department.code.label("dept_code")).outerjoin(
        Department, User.department_id == Department.id
    ).where(User.username == target_uname)
    u_res = await db.execute(u_stmt)
    row = u_res.first()

    if user_role == "DEPT_ADMIN" and hod_dept:
        if row and row.dept_code and row.dept_code != hod_dept:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. HOD {hod_dept} cannot delete faculty belonging to {row.dept_code} department."
            )

    if row and row.User:
        u_obj = row.User
        u_obj.status = "INACTIVE"
        await db.commit()

    return {"message": f"User '{username}' deactivated successfully."}


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS & DASHBOARD (Pure Supabase SQL)
# ─────────────────────────────────────────────────────────────────────────────
_ADMIN_ANALYTICS_CACHE = {}
_ADMIN_ANALYTICS_CACHE_TTL = 20.0


async def _get_cached_analytics(db: AsyncSession, bypass: bool = False):
    now = time.time()
    if not bypass and "data" in _ADMIN_ANALYTICS_CACHE:
        cached_ts, cached_val = _ADMIN_ANALYTICS_CACHE["data"]
        if now - cached_ts < _ADMIN_ANALYTICS_CACHE_TTL:
            return cached_val
    data = await compute_sql_admin_analytics(db)
    _ADMIN_ANALYTICS_CACHE["data"] = (now, data)
    return data


def _matches_dept(class_id: str, dept_code: str) -> bool:
    dept = _normalize_dept_code(dept_code)
    if not dept or dept in ("ALL", "PLACEMENT"):
        return True
    cid = str(class_id or "").upper().replace(" ", "").replace("_", "").replace("-", "")
    return cid.startswith(dept) or dept in cid


async def _get_dept_analytics_metrics(dept_code: str, db: Optional[AsyncSession] = None) -> tuple[list, dict]:
    """
    Computes isolated 14-day Daily Attendance Rate Trend and Overall Status Distribution
    specifically for the given department code.
    If no records exist, returns ([], {}).
    """
    dept = _normalize_dept_code(dept_code)
    if not dept or dept in ("ALL", "PLACEMENT"):
        return None, None

    trend = []
    status_dist = {}

    if db is not None:
        try:
            stmt = (
                select(
                    AttendanceSession.session_date,
                    func.count(AttendanceRecord.id).label("total"),
                    func.sum(case((AttendanceRecord.status.in_(["P", "OD"]), 1), else_=0)).label("attended"),
                    func.sum(case((AttendanceRecord.status == "P", 1), else_=0)).label("present"),
                    func.sum(case((AttendanceRecord.status == "A", 1), else_=0)).label("absent"),
                    func.sum(case((AttendanceRecord.status == "OD", 1), else_=0)).label("on_duty"),
                )
                .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
                .join(ClassRoom, AttendanceSession.class_id == ClassRoom.id)
                .join(Department, ClassRoom.department_id == Department.id)
                .where(
                    or_(
                        Department.code == dept,
                        Department.name.ilike(f"%{dept}%"),
                        ClassRoom.class_code.ilike(f"{dept}%")
                    )
                )
                .group_by(AttendanceSession.session_date)
                .order_by(AttendanceSession.session_date.asc())
            )
            res = await db.execute(stmt)
            rows = res.all()

            if rows:
                tot_pres = 0
                tot_abs = 0
                tot_od = 0
                for r in rows:
                    tot_pres += (r.present or 0)
                    tot_abs += (r.absent or 0)
                    tot_od += (r.on_duty or 0)
                    d_str = r.session_date.strftime("%d-%m-%Y") if isinstance(r.session_date, (date, datetime)) else str(r.session_date)
                    pct = round(((r.attended or 0) / r.total) * 100, 1) if r.total else 0.0
                    trend.append({
                        "date": d_str,
                        "total": r.total,
                        "attended": r.attended or 0,
                        "percentage": pct
                    })
                trend = trend[-14:]
                if tot_pres + tot_abs + tot_od > 0:
                    status_dist = {
                        "present": tot_pres,
                        "absent": tot_abs,
                        "on_duty": tot_od
                    }
                return trend, status_dist
        except Exception as exc:
            print(f"[Analytics Dept Query Warning] {exc}")

    return trend, status_dist


async def _filter_analytics_by_dept(raw_data: dict, dept_code: str, db: AsyncSession) -> dict:
    dept = _normalize_dept_code(dept_code)
    if dept == "ALL" or not dept:
        return raw_data

    filtered_classes = [c for c in raw_data.get("class_stats", []) if _matches_dept(c.get("class_id") or c.get("ClassID", ""), dept)]
    filtered_defaulters = [d for d in raw_data.get("defaulters", []) if _matches_dept(d.get("class_id") or d.get("ClassID", ""), dept)]
    filtered_section_summaries = [s for s in raw_data.get("section_summaries", []) if _matches_dept(s.get("class_id") or s.get("SectionID") or s.get("ClassID", ""), dept)]

    total_students = sum(c.get("student_count", 0) or c.get("Enrolled", 0) for c in filtered_classes)
    total_attended = sum(c.get("attended", 0) or (c.get("Present", 0) + c.get("OD", 0)) for c in filtered_classes)
    total_sessions = sum(c.get("total", 0) or (c.get("Present", 0) + c.get("Absent", 0) + c.get("OD", 0)) for c in filtered_classes)
    overall_pct = round((total_attended / total_sessions * 100), 1) if total_sessions > 0 else 0.0

    today_pres = sum(c.get("today_present", 0) for c in filtered_classes)
    today_abs = sum(c.get("today_absent", 0) for c in filtered_classes)
    today_od = sum(c.get("today_od", 0) for c in filtered_classes)
    today_tot = sum(c.get("today_total", 0) for c in filtered_classes)
    today_pct = round(((today_pres + today_od) / today_tot * 100), 1) if today_tot > 0 else 0.0
    today_dict = {
        "present": today_pres,
        "absent": today_abs,
        "on_duty": today_od,
        "total": today_tot,
        "percentage": today_pct,
    }

    # Isolated Department Daily Attendance Rate Trend and Status Distribution
    dept_trend, dept_status_dist = await _get_dept_analytics_metrics(dept, db=db)
    if dept_trend is None:
        dept_trend = []
    if dept_status_dist is None:
        c_pres = sum(c.get("attended", 0) or c.get("Present", 0) for c in filtered_classes)
        c_abs = sum(c.get("absent", 0) or c.get("Absent", 0) for c in filtered_classes)
        c_od = sum(c.get("on_duty", 0) or c.get("OD", 0) for c in filtered_classes)
        dept_status_dist = {"present": c_pres, "absent": c_abs, "on_duty": c_od} if (c_pres + c_abs + c_od > 0) else {}

    return {
        **raw_data,
        "department_filter": dept,
        "total_students": total_students,
        "total_classes": len(filtered_classes),
        "overall_percentage": overall_pct,
        "today": today_dict,
        "class_stats": filtered_classes,
        "defaulters": filtered_defaulters,
        "defaulters_count": len(filtered_defaulters),
        "section_summaries": filtered_section_summaries,
        "trend": dept_trend,
        "status_distribution": dept_status_dist,
        "recent_activity": [],
    }


@router.get("/analytics")
async def get_analytics(
    bypass: bool = False,
    department_code: Optional[str] = None,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db),
):
    raw_data = await _get_cached_analytics(db, bypass=bypass)
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()

    target_dept = department_code
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept == "PLACEMENT":
            target_dept = department_code or "ALL"
        else:
            target_dept = hod_dept

    if target_dept and target_dept.upper() != "ALL":
        return await _filter_analytics_by_dept(raw_data, target_dept, db=db)

    return raw_data


# ─────────────────────────────────────────────────────────────────────────────
# REPORTS (Pure Supabase SQL)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/reports/class/{class_id}")
async def class_report(
    class_id: str,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept != "PLACEMENT" and not _matches_dept(class_id, hod_dept):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: HOD of {hod_dept} cannot view class report for {class_id} (outside your department)."
            )
    return await get_sql_class_attendance_report(db, class_id)


@router.get("/reports/class/{class_id}/matrix")
async def class_matrix_report(
    class_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """Generates Day 1 to Day 31 detailed attendance matrix register for class and month."""
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept != "PLACEMENT" and not _matches_dept(class_id, hod_dept):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: HOD of {hod_dept} cannot view matrix report for {class_id}."
            )
    return await get_sql_class_matrix(db, class_id, month, year)


@router.get("/reports/student/{reg_no}")
async def student_report(
    reg_no: str,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    clean_rn = str(reg_no).strip()
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept != "PLACEMENT":
            stu_stmt = select(Student).join(Department, Student.department_id == Department.id).where(
                Student.reg_no == clean_rn
            ).where(Department.code == hod_dept)
            stu = (await db.execute(stu_stmt)).scalar_one_or_none()
            if not stu:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Access denied: HOD of {hod_dept} cannot view student report for {clean_rn} (outside your department)."
                )

    stmt_st = select(Student.id).where(Student.reg_no == clean_rn)
    st_id = (await db.execute(stmt_st)).scalar_one_or_none()
    if not st_id:
        return {"total_hours": 0, "attended_hours": 0, "od_hours": 0, "percentage": 0.0, "subject_summary": [], "datewise": []}

    stmt_rec = (
        select(
            AttendanceRecord.status,
            AttendanceSession.session_date,
            AttendanceSession.slot_hour,
            Subject.subject_code,
            Subject.name.label("subject_name")
        )
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .outerjoin(Subject, AttendanceSession.subject_id == Subject.id)
        .where(AttendanceRecord.student_id == st_id)
        .order_by(AttendanceSession.session_date.asc())
    )
    records = (await db.execute(stmt_rec)).all()

    total = len(records)
    attended = 0
    od = 0
    subject_map: Dict[str, Dict] = {}
    date_hour_map: Dict[str, Dict[str, str]] = {}

    for st_val, s_date, s_hour, sub_code, sub_name in records:
        st_clean = (st_val or "").strip().upper()
        if st_clean == "P":
            attended += 1
        elif st_clean in ("OD", "ONDUTY", "ON DUTY"):
            od += 1

        d_str = s_date.strftime("%d-%m-%Y") if isinstance(s_date, (date, datetime)) else str(s_date)
        h_str = (s_hour or "DAY").strip().upper()

        if d_str not in date_hour_map:
            date_hour_map[d_str] = {}
        date_hour_map[d_str][h_str] = st_clean

        if sub_code:
            if sub_code not in subject_map:
                subject_map[sub_code] = {
                    "subject_id": sub_code,
                    "subject_name": sub_name or sub_code,
                    "total": 0,
                    "attended": 0,
                    "od": 0,
                }
            subject_map[sub_code]["total"] += 1
            if st_clean == "P":
                subject_map[sub_code]["attended"] += 1
            elif st_clean in ("OD", "ONDUTY", "ON DUTY"):
                subject_map[sub_code]["od"] += 1

    subject_summary = []
    for s_code, s_info in subject_map.items():
        eff = s_info["attended"] + s_info["od"]
        s_pct = round((eff / s_info["total"]) * 100, 1) if s_info["total"] else 0.0
        subject_summary.append({**s_info, "percentage": s_pct})

    eff_att = attended + od
    overall_pct = round((eff_att / total) * 100, 1) if total else 0.0

    datewise = []
    for d_str in sorted(date_hour_map.keys(), reverse=True)[:60]:
        row_dict = {"date": d_str}
        for h in ALL_HOURS:
            row_dict[h] = date_hour_map[d_str].get(h, "-")
        datewise.append(row_dict)

    return {
        "total_hours": total,
        "attended_hours": attended,
        "od_hours": od,
        "percentage": overall_pct,
        "subject_summary": subject_summary,
        "datewise": datewise,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DAILY ATTENDANCE MANAGEMENT & MODIFICATION (Pure Supabase SQL)
# ─────────────────────────────────────────────────────────────────────────────
class AdminAttendanceEntry(BaseModel):
    reg_no: str
    status: str


class AdminModifyAttendanceRequest(BaseModel):
    class_id: str
    date: str
    hour: str = "DAY"
    subject_id: str = ""
    attendance: List[AdminAttendanceEntry]


@router.get("/attendance/overview")
async def get_attendance_overview(
    date: str,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve full institutional overview of submitted and pending attendances for a date, sandboxed for HOD."""
    overview = await get_sql_date_attendance_overview(db, date)
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept != "PLACEMENT":
            if isinstance(overview, dict):
                if "submitted" in overview:
                    overview["submitted"] = [s for s in overview["submitted"] if _matches_dept(s.get("class_id") or s.get("ClassID", ""), hod_dept)]
                if "pending" in overview:
                    overview["pending"] = [p for p in overview["pending"] if _matches_dept(p.get("class_id") or p.get("ClassID", ""), hod_dept)]
    return overview


@router.get("/attendance/daily")
@router.get("/attendance/daily-edit")
async def get_daily_attendance(
    class_id: str,
    date: str,
    hour: str = "DAY",
    subject_id: str = "",
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """Retrieve students and their existing attendance status for viewing/modifying."""
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept != "PLACEMENT" and not _matches_dept(class_id, hod_dept):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: HOD of {hod_dept} cannot view daily attendance for {class_id} (outside your department)."
            )
    return await get_sql_daily_attendance_for_edit(db, class_id, date, hour, subject_id)


@router.post("/attendance/modify")
async def modify_daily_attendance(
    body: AdminModifyAttendanceRequest,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """Admin endpoint to modify and resubmit attendance for any date/class/subject."""
    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    if user_role == "DEPT_ADMIN":
        hod_dept = _resolve_hod_dept_code(current_user)
        if hod_dept != "PLACEMENT" and not _matches_dept(body.class_id, hod_dept):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: HOD of {hod_dept} cannot modify attendance for {body.class_id} (outside your department)."
            )
    admin_id = str(current_user.get("UserID", "admin"))
    att_map = {e.reg_no.strip(): e.status.upper() for e in body.attendance}
    _ADMIN_ANALYTICS_CACHE.clear()
    return await update_sql_daily_attendance(
        db=db,
        class_id=body.class_id,
        date_str=body.date,
        hour=body.hour,
        subject_id=body.subject_id,
        admin_id=admin_id,
        attendance_map=att_map
    )


MONTH_NAMES = {m.upper(): i for i, m in enumerate(calendar.month_name) if m}
MONTH_ABBRS = {m.upper(): i for i, m in enumerate(calendar.month_abbr) if m}


async def _resolve_matrix_class_id(banner_text: str, sample_reg_nos: List[str] = None, db: AsyncSession = None) -> str:
    bt_upper = str(banner_text or "").upper().replace(" ", "").replace("-", "").replace("_", "")
    if "4A" in bt_upper or "IV" in bt_upper or "27" in bt_upper:
        return "CSE27A"
    elif "3A" in bt_upper or "IIIYEARA" in bt_upper or "28A" in bt_upper:
        return "CSE28A"
    elif "3B" in bt_upper or "IIIYEARB" in bt_upper or "28B" in bt_upper:
        return "CSE28B"
    elif "2A" in bt_upper or "IIYEARA" in bt_upper or "29A" in bt_upper:
        return "CSE29A"
    elif "2B" in bt_upper or "IIYEARB" in bt_upper or "29B" in bt_upper:
        return "CSE29B"

    # Query DB for sample student registration numbers
    if sample_reg_nos and db is not None:
        try:
            stmt = select(Student, ClassRoom).join(ClassRoom, Student.class_id == ClassRoom.id).where(Student.reg_no.in_(sample_reg_nos[:10]))
            res = (await db.execute(stmt)).all()
            for st, cr in res:
                if cr and cr.class_code:
                    return cr.class_code
        except Exception:
            pass

        # RegNo heuristic fallback for 2nd Year
        for rn in sample_reg_nos:
            rn_clean = str(rn).strip()
            if rn_clean.isdigit():
                val = int(rn_clean)
                if 410125104001 <= val <= 410125104060:
                    return "CSE29A"
                elif 410125104061 <= val <= 410125104305:
                    return "CSE29B"

    return "CSE29A"


async def _import_sql_attendance_rows(db: AsyncSession, rows: List[dict]) -> int:
    """
    High-performance batch ingestion of attendance entries directly into PostgreSQL.
    Creates or updates AttendanceSession and AttendanceRecord rows with zero Google Sheets overhead.
    """
    if not rows:
        return 0

    # 1. Cache classes
    stmt_classes = select(ClassRoom)
    classes = (await db.execute(stmt_classes)).scalars().all()
    class_map = {c.class_code.upper(): c.id for c in classes}
    for c in classes:
        class_map[str(c.id)] = c.id

    # 2. Cache subjects
    stmt_subs = select(Subject)
    subjects = (await db.execute(stmt_subs)).scalars().all()
    sub_map = {s.subject_code.upper(): s.id for s in subjects}
    for s in subjects:
        sub_map[str(s.id)] = s.id

    # 3. Cache students by reg_no
    stmt_students = select(Student)
    students = (await db.execute(stmt_students)).scalars().all()
    student_map = {s.reg_no.strip(): s.id for s in students}

    # Group rows by (class_id, date, slot_hour, subject_id)
    grouped_sessions = {}
    for r in rows:
        raw_cid = str(r.get("class_id", "")).strip().upper()
        raw_rn = str(r.get("reg_no", "")).strip()
        raw_status = str(r.get("status", "")).strip().upper()
        raw_hour = str(r.get("hour", "DAY")).strip().upper()
        raw_sub = str(r.get("subject_id", "")).strip().upper()
        raw_date = str(r.get("date", "")).strip()

        cid = class_map.get(raw_cid)
        if not cid:
            continue
        student_id = student_map.get(raw_rn)
        if not student_id:
            continue

        d_obj = parse_date_str(raw_date)
        if not d_obj:
            continue

        sub_id = sub_map.get(raw_sub)
        sess_key = (cid, d_obj, raw_hour, sub_id)
        if sess_key not in grouped_sessions:
            grouped_sessions[sess_key] = []
        grouped_sessions[sess_key].append((student_id, raw_status))

    if not grouped_sessions:
        return 0

    total_records = 0
    for (cid, d_obj, s_hour, sub_id), st_records in grouped_sessions.items():
        sess_stmt = select(AttendanceSession).where(
            and_(
                AttendanceSession.class_id == cid,
                AttendanceSession.session_date == d_obj,
                AttendanceSession.slot_hour == s_hour,
            )
        )
        if sub_id:
            sess_stmt = sess_stmt.where(AttendanceSession.subject_id == sub_id)

        session_res = (await db.execute(sess_stmt)).scalars().first()
        if not session_res:
            s_type = "TRAINING" if s_hour in ("PLACEMENT", "TRAINING") else ("DAILY" if s_hour in ("DAILY", "DAY") else "HOURLY")
            session_res = AttendanceSession(
                class_id=cid,
                session_date=d_obj,
                slot_hour=s_hour,
                subject_id=sub_id,
                session_type=s_type,
                lock_status="LOCKED"
            )
            db.add(session_res)
            await db.flush()

        s_id = session_res.id

        rec_stmt = select(AttendanceRecord).where(AttendanceRecord.session_id == s_id)
        existing_records = (await db.execute(rec_stmt)).scalars().all()
        rec_map = {rec.student_id: rec for rec in existing_records}

        new_recs = []
        for st_id, st_status in st_records:
            if st_id in rec_map:
                rec_map[st_id].status = st_status
            else:
                new_recs.append(AttendanceRecord(
                    session_id=s_id,
                    student_id=st_id,
                    status=st_status
                ))
            total_records += 1

        if new_recs:
            db.add_all(new_recs)

    await db.commit()
    _ADMIN_ANALYTICS_CACHE.clear()
    return total_records


def _resolve_matrix_month_year(banner_text: str, sample_date_strs: List[str] = None) -> tuple:
    clean = str(banner_text or "").upper().replace("|", " ").replace(",", " ").replace("-", " ")
    det_m = None
    det_y = 2026
    for tok in clean.split():
        tok = tok.strip()
        if tok in MONTH_NAMES:
            det_m = MONTH_NAMES[tok]
        elif tok in MONTH_ABBRS:
            det_m = MONTH_ABBRS[tok]
        elif tok.isdigit() and len(tok) == 4 and 2020 <= int(tok) <= 2040:
            det_y = int(tok)

    if not det_m and sample_date_strs:
        date_regex = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$")
        for ds in sample_date_strs:
            m = date_regex.match(str(ds).strip())
            if m:
                _, mo, yr = m.groups()
                det_m = int(mo)
                if len(yr) == 2:
                    yr = f"20{yr}"
                det_y = int(yr)
                break

    return (det_m or 10, det_y)


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – ATTENDANCE (Monthly Matrix Register & Columnar Ingestion)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/attendance")
async def import_attendance(
    file: UploadFile = File(...),
    _=Depends(require_role("ADMIN")),
    db: AsyncSession = Depends(get_db)
):
    """
    Versatile Attendance Importer:
    1. Institutional Monthly Daily Register Matrix (.xlsx / .csv):
       Row 1: Title banner with Class & Month/Year
       Row 2: Reg No | Student Name | 01-MM-YYYY ... 31-MM-YYYY | Summary columns
       Rows 3+: Student daily attendance (P, A, OD, Holiday)
    2. Classic Columnar Format (.xlsx / .csv):
       Date | ClassID | Hour | SubjectID | RegNo | Status | FacultyID
    """
    filename = (file.filename or "").lower()
    if not (filename.endswith(".xlsx") or filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are supported.")

    contents = await file.read()
    grid_rows = []

    if filename.endswith(".xlsx"):
        import openpyxl
        try:
            wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
            ws_xl = wb.active
            for row in ws_xl.iter_rows(values_only=True):
                grid_rows.append([c if c is not None else "" for c in row])
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to read .xlsx file: {e}")
    else:
        try:
            text = contents.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = contents.decode("latin-1")
        reader = csv.reader(io.StringIO(text))
        grid_rows = [list(r) for r in reader]

    if not grid_rows:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")

    # ── Check if Monthly Matrix Register Format ──────────────────────────────
    is_matrix = False
    banner_text = ""
    header_row_idx = -1

    for idx, row in enumerate(grid_rows[:5]):
        text_line = " ".join([str(c or "").strip() for c in row])
        if "DAILY ATTENDANCE REGISTER" in text_line.upper():
            banner_text = text_line
            is_matrix = True
        if any(str(c or "").strip().lower() in ("reg no", "regno", "roll no", "rollno", "reg_no") for c in row):
            header_row_idx = idx
            date_hits = [
                c for c in row
                if re.match(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$", str(c or "").strip())
            ]
            if len(date_hits) >= 2:
                is_matrix = True
            break

    if is_matrix:
        if header_row_idx == -1:
            raise HTTPException(status_code=400, detail="Could not locate table header row with 'Reg No' in monthly register.")

        headers = [str(c or "").strip() for c in grid_rows[header_row_idx]]
        reg_col = -1
        name_col = -1
        date_cols = []  # list of (col_idx, date_str)
        date_regex = re.compile(r"^(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$")

        for col_idx, h in enumerate(headers):
            hl = h.lower().replace(" ", "").replace("_", "")
            if hl in ("regno", "rollno", "rollnumber", "registerno"):
                reg_col = col_idx
            elif hl in ("studentname", "name"):
                name_col = col_idx
            else:
                m = date_regex.match(h.strip())
                if m:
                    d, mo, yr = m.groups()
                    if len(yr) == 2:
                        yr = f"20{yr}"
                    norm_d = f"{int(d):02d}-{int(mo):02d}-{yr}"
                    date_cols.append((col_idx, norm_d))

        if reg_col == -1:
            raise HTTPException(status_code=400, detail="Column 'Reg No' not found in monthly register.")
        if not date_cols:
            raise HTTPException(status_code=400, detail="No valid date columns (e.g. DD-MM-YYYY) found in monthly register.")

        # Sample student reg nos for accurate class resolution
        sample_rns = [
            str(r[reg_col]).strip()
            for r in grid_rows[header_row_idx + 1:header_row_idx + 10]
            if len(r) > reg_col and str(r[reg_col] or "").strip() and not any(skip in str(r[reg_col]).lower() for skip in ["total", "daily", "average", "summary"])
        ]
        sample_dates = [d_str for _, d_str in date_cols]

        extracted_cid = await _resolve_matrix_class_id(banner_text, sample_rns, db)
        month_num, year_num = _resolve_matrix_month_year(banner_text, sample_dates)
        month_name = calendar.month_name[month_num]
        month_label = f"{month_name} {year_num}"

        rows_to_insert = []
        students_processed = 0

        for row in grid_rows[header_row_idx + 1:]:
            if reg_col >= len(row):
                continue
            reg_val = str(row[reg_col] or "").strip()
            if not reg_val:
                continue
            if any(skip in reg_val.lower() for skip in ["total", "daily", "average", "summary"]):
                continue
            if name_col != -1 and name_col < len(row):
                n_val = str(row[name_col] or "").strip().lower()
                if any(skip in n_val for skip in ["total present", "total absent", "total od", "daily %"]):
                    continue

            students_processed += 1

            for col_idx, d_str in date_cols:
                if col_idx >= len(row):
                    continue
                raw_st = str(row[col_idx] or "").strip().upper()
                if not raw_st:
                    continue

                if raw_st.startswith("P") or raw_st == "1":
                    norm_status = "P"
                elif raw_st.startswith("A") or raw_st == "0":
                    norm_status = "A"
                elif raw_st in ("OD", "ONDUTY", "ON DUTY"):
                    norm_status = "OD"
                elif any(h in raw_st for h in ["HOLIDAY", "SUNDAY", "-", "LEAVE", "L"]):
                    continue
                else:
                    continue

                rows_to_insert.append({
                    "date": d_str,
                    "class_id": extracted_cid,
                    "hour": "DAILY",
                    "subject_id": "GENERAL",
                    "reg_no": reg_val,
                    "status": norm_status,
                    "faculty_id": "IMPORT",
                })

        inserted = await _import_sql_attendance_rows(db, rows_to_insert)

        return {
            "message": f"Successfully imported {inserted} attendance entries for {extracted_cid} ({month_label}).",
            "format": "monthly_register",
            "class_id": extracted_cid,
            "month": month_label,
            "total_students": students_processed,
            "total_dates": len(date_cols),
            "total_rows": len(rows_to_insert),
            "inserted": inserted,
            "skipped": len(rows_to_insert) - inserted,
            "sheet_synced": False,
        }

    # ── Classic Columnar Ingestion ───────────────────────────────────────────
    raw_headers = [str(c).strip() if c is not None else "" for c in grid_rows[0]]

    date_col   = _find_col(["date", "datedd-mm-yyyy", "attendancedate", "sessiondate"], raw_headers)
    class_col  = _find_col(["classid", "class", "section", "classcode"], raw_headers)
    hour_col   = _find_col(["hour", "period", "session", "slot", "h"], raw_headers)
    sub_col    = _find_col(["subjectid", "subject", "subid", "courseid", "coursecode"], raw_headers)
    reg_col    = _find_col(["regno", "reg_no", "registerno", "rollno", "rollnumber", "regnum"], raw_headers)
    status_col = _find_col(["status", "attendance", "attendancestatus", "mark", "state"], raw_headers)
    fac_col    = _find_col(["facultyid", "faculty_id", "staffid", "facid"], raw_headers)

    missing = []
    if date_col == -1: missing.append("Date")
    if class_col == -1: missing.append("ClassID")
    if hour_col == -1: missing.append("Hour")
    if sub_col == -1: missing.append("SubjectID")
    if reg_col == -1: missing.append("RegNo")
    if status_col == -1: missing.append("Status")

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Unrecognized format. Missing required columns: {', '.join(missing)}. "
                   f"Found headers: {', '.join(h for h in raw_headers if h)}",
        )

    rows = []
    errors = []

    for row_num, row in enumerate(grid_rows[1:], start=2):
        raw_d   = row[date_col] if date_col < len(row) else ""
        raw_c   = str(row[class_col]).strip() if class_col < len(row) and row[class_col] is not None else ""
        raw_h   = str(row[hour_col]).strip().upper() if hour_col < len(row) and row[hour_col] is not None else ""
        raw_s   = str(row[sub_col]).strip() if sub_col < len(row) and row[sub_col] is not None else ""
        raw_rn  = str(row[reg_col]).strip() if reg_col < len(row) and row[reg_col] is not None else ""
        raw_st  = str(row[status_col]).strip().upper() if status_col < len(row) and row[status_col] is not None else ""
        raw_fac = str(row[fac_col]).strip() if fac_col != -1 and fac_col < len(row) and row[fac_col] is not None else "IMPORT"

        if not raw_d and not raw_c and not raw_rn:
            continue

        if raw_h.isdigit():
            raw_h = f"H{raw_h}"
        elif raw_h.startswith("H") and len(raw_h) > 2:
            raw_h = raw_h[:2]

        if raw_st.startswith("P"):
            raw_st = "P"
        elif raw_st.startswith("A"):
            raw_st = "A"
        elif raw_st in ("-", "OD", "LEAVE", "L"):
            raw_st = "-"

        date_str = _parse_date_cell(raw_d)

        if raw_st not in ("P", "A", "-"):
            errors.append(f"Row {row_num}: Invalid status '{raw_st}'.")
            continue
        if raw_h not in ALL_HOURS:
            errors.append(f"Row {row_num}: Invalid hour '{raw_h}'. Must be H1-H8.")
            continue
        if not raw_c or not raw_s or not raw_rn:
            errors.append(f"Row {row_num}: ClassID, SubjectID, and RegNo cannot be blank.")
            continue

        rows.append({
            "date": date_str,
            "class_id": raw_c,
            "hour": raw_h,
            "subject_id": raw_s,
            "reg_no": raw_rn,
            "status": raw_st,
            "faculty_id": raw_fac or "IMPORT",
        })

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"validation_errors": errors[:20], "message": f"{len(errors)} validation error(s) found."},
        )

    inserted = await _import_sql_attendance_rows(db, rows)
    return {
        "message": f"Import complete. {inserted} rows processed into database.",
        "total_rows": len(rows),
        "inserted": inserted,
        "skipped": len(rows) - inserted,
    }


# ─────────────────────────────────────────────────────────────────────────────
# DOWNLOAD ATTENDANCE REGISTER TEMPLATE (.csv)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/template/attendance-register")
async def download_attendance_register_template(
    class_id: str = "CSE29A",
    month: int = 7,
    year: int = 2026,
    _=_admin_dep,
    db: AsyncSession = Depends(get_db)
):
    clean_cid = str(class_id or "").strip().upper()
    cls_stmt = select(ClassRoom).where(ClassRoom.class_code == clean_cid)
    cls_obj = (await db.execute(cls_stmt)).scalars().first()
    c_name = cls_obj.class_name if cls_obj else clean_cid

    month_name = calendar.month_name[month].upper()
    num_days = calendar.monthrange(year, month)[1]

    # Fetch active students for this class from SQL
    students = []
    if cls_obj:
        st_stmt = select(Student).where(
            and_(
                Student.class_id == cls_obj.id,
                Student.status == "ACTIVE"
            )
        ).order_by(Student.reg_no)
        students = (await db.execute(st_stmt)).scalars().all()

    date_cols = [f"{d:02d}-{month:02d}-{year}" for d in range(1, num_days + 1)]
    total_cols = 2 + len(date_cols) + 4

    row1 = [f"DAILY ATTENDANCE REGISTER  |  {c_name.upper()}  |  {month_name} {year}"] + [""] * (total_cols - 1)
    row2 = ["Reg No", "Student Name"] + date_cols + ["Total Present", "Total Absent", "Total OD", "Attendance %"]

    rows = [row1, row2]

    for s in students:
        rn = str(s.reg_no or "").strip()
        sname = str(s.name or "").strip()

        day_vals = []
        p_count = 0
        for d_str in date_cols:
            dt_obj = datetime.strptime(d_str, "%d-%m-%Y")
            if dt_obj.weekday() == 6:
                day_vals.append("Holiday")
            else:
                day_vals.append("P")
                p_count += 1

        pct_str = "100.0%" if p_count > 0 else "0.0%"
        rows.append([rn, sname] + day_vals + [str(p_count), "0", "0", pct_str])

    rows.append([""] * total_cols)
    r_pres = ["", "Total Present"] + [str(len(students)) if datetime.strptime(d_str, "%d-%m-%Y").weekday() != 6 else "0" for d_str in date_cols] + ["", "", "", ""]
    r_abs  = ["", "Total Absent"] + ["0" for _ in date_cols] + ["", "", "", ""]
    r_od   = ["", "Total OD"] + ["0" for _ in date_cols] + ["", "", "", ""]
    r_pct  = ["", "Daily %"] + ["100%" if datetime.strptime(d_str, "%d-%m-%Y").weekday() != 6 else "-" for d_str in date_cols] + ["", "", "", ""]
    rows.extend([r_pres, r_abs, r_od, r_pct])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    csv_bytes = output.getvalue().encode("utf-8")

    filename = f"Attendance_Register_{clean_cid}_{month_name}_{year}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT DETAILED 31-DAY ATTENDANCE REGISTER MATRIX (.csv)
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/reports/class/{class_id}/matrix/export")
async def export_class_attendance_matrix_csv(
    class_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """Generates and downloads the detailed Day 1 to Day 31 daily attendance matrix register CSV."""
    matrix_data = await get_sql_class_matrix(db, class_id, month, year)
    if "error" in matrix_data:
        raise HTTPException(status_code=404, detail=matrix_data["error"])

    c_name = matrix_data.get("class_name", class_id)
    c_code = matrix_data.get("class_id", class_id)
    m_name = matrix_data.get("month_name", "MONTH")
    yr = matrix_data.get("year", 2026)
    date_cols = matrix_data.get("date_cols", [])
    matrix_rows = matrix_data.get("matrix_rows", [])

    total_cols = 2 + len(date_cols) + 4
    row1 = [f"DAILY ATTENDANCE REGISTER  |  {c_name.upper()} ({c_code})  |  {m_name.upper()} {yr}"] + [""] * (total_cols - 1)
    row2 = ["Reg No", "Student Name"] + date_cols + ["Total Present", "Total Absent", "Total OD", "Attendance %"]

    rows = [row1, row2]
    daily_pres = {d: 0 for d in date_cols}
    daily_abs  = {d: 0 for d in date_cols}
    daily_od   = {d: 0 for d in date_cols}

    for r in matrix_rows:
        day_vals = []
        statuses = r.get("statuses", {})
        for d in date_cols:
            val = statuses.get(d, "-")
            day_vals.append(val)
            if val == "P":
                daily_pres[d] += 1
            elif val == "A":
                daily_abs[d] += 1
            elif val in ("OD", "ONDUTY", "ON DUTY"):
                daily_od[d] += 1

        rows.append([
            r["reg_no"],
            r["name"],
        ] + day_vals + [
            str(r.get("total_present", 0)),
            str(r.get("total_absent", 0)),
            str(r.get("total_od", 0)),
            f"{r.get('percentage', 0.0)}%"
        ])

    rows.append([""] * total_cols)
    tot_pres_row = ["", "Total Present"] + [str(daily_pres[d]) for d in date_cols] + ["", "", "", ""]
    tot_abs_row = ["", "Total Absent"] + [str(daily_abs[d]) for d in date_cols] + ["", "", "", ""]
    tot_od_row = ["", "Total OD"] + [str(daily_od[d]) for d in date_cols] + ["", "", "", ""]
    tot_pct_row = ["", "Daily %"] + [
        f"{round((daily_pres[d] / max(1, daily_pres[d] + daily_abs[d] + daily_od[d])) * 100, 1)}%"
        if (daily_pres[d] + daily_abs[d] + daily_od[d]) > 0 else "-"
        for d in date_cols
    ] + ["", "", "", ""]
    rows.extend([tot_pres_row, tot_abs_row, tot_od_row, tot_pct_row])

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    csv_bytes = output.getvalue().encode("utf-8")

    filename = f"Attendance_Matrix_{c_code}_{m_name}_{yr}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – STUDENTS (High-Speed Multi-Setup Excel Upload)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/students")
async def import_students(
    file: UploadFile = File(...),
    class_id: Optional[str] = Form(None),
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """
    High-Speed Bulk Student Onboarding:
    - Zero Google Sheets overhead.
    - Multithreaded password hashing (< 0.8s for 500-1,000 accounts). Default password: {RegNo}@2026.
    - Single-transaction atomic commit directly to Supabase PostgreSQL.
    """
    import openpyxl

    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    ws_xl = wb.active

    raw_headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws_xl.iter_rows(max_row=1))]

    reg_col       = _find_col(["regno", "reg_no", "registerno", "rollno", "rollnumber", "registernum", "regnum", "registrationno"], raw_headers)
    name_col      = _find_col(["name", "studentname", "fullname", "studentfullname", "sname"], raw_headers)
    class_col     = _find_col(["classid", "class", "section", "classcode"], raw_headers)
    classname_col = _find_col(["classname", "class_name", "department", "dept"], raw_headers)
    username_col  = _find_col(["username", "user", "uname", "loginname"], raw_headers)
    password_col  = _find_col(["password", "pass", "pwd"], raw_headers)

    if reg_col == -1:
        raise HTTPException(
            status_code=400,
            detail='Column "Register No" not found. (Accepted: RegNo, Register No, Roll No, RegNum).',
        )
    if name_col == -1:
        raise HTTPException(
            status_code=400,
            detail='Column "Student Name" not found. (Accepted: Name, Student Name, Full Name).',
        )

    raw_rows = []
    cand_regnos = set()
    cand_classes = set()
    errors = []

    for row_num, row in enumerate(ws_xl.iter_rows(min_row=2, values_only=True), start=2):
        reg_no = str(row[reg_col]).strip() if reg_col < len(row) and row[reg_col] is not None else ""
        name   = str(row[name_col]).strip() if name_col < len(row) and row[name_col] is not None else ""
        
        row_class = str(row[class_col]).strip() if class_col != -1 and class_col < len(row) and row[class_col] is not None else ""
        target_class_id = (row_class or (class_id.strip() if class_id else "")).strip().upper()

        if not reg_no and not name and not target_class_id:
            continue

        if not reg_no:
            errors.append(f"Row {row_num}: Register number is required.")
            continue
        if not name:
            errors.append(f"Row {row_num}: Student name is required (reg: {reg_no}).")
            continue
        if not target_class_id:
            errors.append(f"Row {row_num} ({reg_no}): ClassID is missing. Specify in Excel or select a class.")
            continue

        # Sandboxing check for Academic HODs
        if user_role == "DEPT_ADMIN" and hod_dept != "PLACEMENT":
            if not target_class_id.startswith(hod_dept):
                errors.append(f"Row {row_num} ({reg_no}): Class '{target_class_id}' does not belong to your department ({hod_dept}).")
                continue

        row_classname = str(row[classname_col]).strip() if classname_col != -1 and classname_col < len(row) and row[classname_col] is not None else ""
        row_username = str(row[username_col]).strip() if username_col != -1 and username_col < len(row) and row[username_col] is not None else ""
        row_password = str(row[password_col]).strip() if password_col != -1 and password_col < len(row) and row[password_col] is not None else ""

        raw_rows.append((row_num, reg_no, name, target_class_id, row_classname, row_username, row_password))
        cand_regnos.add(reg_no.lower())
        cand_classes.add(target_class_id)

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Errors encountered in upload:", "errors": errors[:25]},
        )

    if not raw_rows:
        return {
            "status": "success",
            "message": "No student records found in file.",
            "inserted": 0,
            "skipped": 0,
            "total": 0,
        }

    # 1. Targeted SQL lookups (only for items in this upload)
    stmt_existing_reg = select(Student.reg_no).where(func.lower(Student.reg_no).in_(list(cand_regnos)))
    existing_regnos = {
        str(r).strip().lower()
        for r in (await db.execute(stmt_existing_reg)).scalars().all()
    }

    stmt_classes = select(ClassRoom).where(ClassRoom.class_code.in_(list(cand_classes)))
    all_sql_classes = (await db.execute(stmt_classes)).scalars().all()
    class_map = {c.class_code.upper(): c for c in all_sql_classes}
    class_name_map = {c.class_code.upper(): c.class_name for c in all_sql_classes}

    stmt_depts = select(Department).where(Department.is_active == True)
    all_depts = (await db.execute(stmt_depts)).scalars().all()
    dept_map = {d.code.upper(): d for d in all_depts}
    default_dept = dept_map.get("CSE") or (all_depts[0] if all_depts else None)

    parsed_rows = []
    skipped = 0
    seen_usernames = set()

    for _, reg_no, name, target_class_id, row_classname, row_username, row_password in raw_rows:
        if reg_no.lower() in existing_regnos:
            skipped += 1
            continue

        target_class_name = row_classname or class_name_map.get(target_class_id, target_class_id)
        final_username = row_username or reg_no
        final_password = row_password or f"{reg_no}@2026"

        if final_username.lower() in seen_usernames:
            final_username = f"{final_username}_{reg_no}"
        seen_usernames.add(final_username.lower())
        existing_regnos.add(reg_no.lower())

        parsed_rows.append({
            "reg_no": reg_no,
            "name": name,
            "target_class_id": target_class_id,
            "target_class_name": target_class_name,
            "username": final_username,
            "password": final_password,
        })

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Errors encountered in upload:", "errors": errors[:25]},
        )

    if not parsed_rows:
        return {
            "status": "success",
            "message": f"Multi-setup complete: 0 new students added, {skipped} skipped (already existed).",
            "inserted": 0,
            "skipped": skipped,
            "total": skipped,
        }

    # 3. Batch create missing classes if any
    needed_classes = {p["target_class_id"]: p["target_class_name"] for p in parsed_rows if p["target_class_id"] not in class_map}
    if needed_classes:
        for cid_code, cname in needed_classes.items():
            c_dept_code = hod_dept or "CSE"
            for d in ["CSE", "ECE", "EEE", "MECH", "IT", "AIDS", "CYBER", "AIML", "SH"]:
                if cid_code.startswith(d):
                    c_dept_code = d
                    break
            c_dept_obj = dept_map.get(c_dept_code) or default_dept
            new_cls = ClassRoom(
                department_id=c_dept_obj.id,
                class_code=cid_code,
                class_name=cname,
                year=1,
                section="A",
                semester=1,
                status="ACTIVE"
            )
            db.add(new_cls)
            class_map[cid_code] = new_cls
            class_name_map[cid_code] = cname
        await db.flush()

    # 4. Multithreaded password hashing (< 0.8s for 500-1,000 accounts)
    passwords_list = [p["password"] for p in parsed_rows]
    hashes = hash_passwords_bulk(passwords_list, rounds=8)

    # 5. High-speed multi-row bulk SQL insertion (2 network round-trips total)
    user_dicts = []
    for item, pwd_hash in zip(parsed_rows, hashes):
        cls_obj = class_map[item["target_class_id"]]
        user_dicts.append({
            "username": item["username"],
            "full_name": item["name"],
            "password_hash": pwd_hash,
            "role": "STUDENT",
            "department_id": cls_obj.department_id,
            "status": "ACTIVE"
        })

    stmt_users = insert(User).values(user_dicts).returning(User.id, User.username)
    res_users = await db.execute(stmt_users)
    user_id_map = {row.username: row.id for row in res_users.all()}

    student_dicts = []
    for item in parsed_rows:
        cls_obj = class_map[item["target_class_id"]]
        student_dicts.append({
            "reg_no": item["reg_no"],
            "user_id": user_id_map[item["username"]],
            "class_id": cls_obj.id,
            "department_id": cls_obj.department_id,
            "name": item["name"],
            "residence_type": "DAY_SCHOLAR",
            "status": "ACTIVE"
        })

    stmt_students = insert(Student).values(student_dicts)
    await db.execute(stmt_students)
    await db.commit()
    _ADMIN_ANALYTICS_CACHE.clear()

    return {
        "status": "success",
        "message": f"Multi-setup import complete! {len(parsed_rows)} student(s) added successfully, {skipped} skipped (already existed).",
        "inserted": len(parsed_rows),
        "skipped": skipped,
        "total": len(parsed_rows) + skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – FACULTY (Excel upload)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/faculty")
async def import_faculty(
    file: UploadFile = File(...),
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """
    Upload an .xlsx file to bulk-add faculty accounts.
    Required columns: FacultyID | Name | Username | Password
    """
    import openpyxl

    user_role = (current_user.get("role") or current_user.get("Role") or "").upper()
    hod_dept = _resolve_hod_dept_code(current_user)

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    ws_xl = wb.active

    raw_headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws_xl.iter_rows(max_row=1))]

    fac_id_col   = _find_col(["facultyid", "faculty_id", "staffid", "staff_id", "facid", "id", "teacherid"], raw_headers)
    name_col     = _find_col(["name", "facultyname", "staffname", "fullname", "teachername"], raw_headers)
    username_col = _find_col(["username", "user", "uname", "login", "loginname"], raw_headers)
    password_col = _find_col(["password", "pass", "pwd"], raw_headers)

    missing = []
    if fac_id_col == -1: missing.append("FacultyID")
    if name_col == -1: missing.append("Name")
    if username_col == -1: missing.append("Username")
    if password_col == -1: missing.append("Password")

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing columns: {', '.join(missing)}. Required: FacultyID, Name, Username, Password",
        )

    stmt_users = select(User.username)
    existing_usernames = {str(u).strip().lower() for u in (await db.execute(stmt_users)).scalars().all()}

    stmt_fac = select(Faculty.faculty_code)
    existing_fac_codes = {str(fc).strip().lower() for fc in (await db.execute(stmt_fac)).scalars().all()}

    stmt_depts = select(Department).where(Department.is_active == True)
    all_depts = (await db.execute(stmt_depts)).scalars().all()
    dept_map = {d.code.upper(): d for d in all_depts}
    default_dept = dept_map.get(hod_dept if hod_dept != "PLACEMENT" else "CSE") or (all_depts[0] if all_depts else None)

    parsed_rows = []
    skipped = 0
    errors = []

    for row_num, row in enumerate(ws_xl.iter_rows(min_row=2, values_only=True), start=2):
        faculty_id = str(row[fac_id_col]).strip() if fac_id_col < len(row) and row[fac_id_col] is not None else ""
        name       = str(row[name_col]).strip() if name_col < len(row) and row[name_col] is not None else ""
        username   = str(row[username_col]).strip() if username_col < len(row) and row[username_col] is not None else ""
        password   = str(row[password_col]).strip() if password_col < len(row) and row[password_col] is not None else ""

        if not faculty_id and not name and not username:
            continue

        if not faculty_id or not name or not username or not password:
            errors.append(f"Row {row_num}: FacultyID, Name, Username, and Password are all required.")
            continue

        if username.lower() in existing_usernames or faculty_id.lower() in existing_fac_codes:
            skipped += 1
            continue

        existing_usernames.add(username.lower())
        existing_fac_codes.add(faculty_id.lower())

        parsed_rows.append({
            "faculty_id": faculty_id,
            "name": name,
            "username": username,
            "password": password,
        })

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Errors found in faculty file:", "errors": errors[:20]},
        )

    if not parsed_rows:
        return {
            "message": f"Faculty import complete. 0 account(s) created, {skipped} skipped (already exists).",
            "inserted": 0,
            "skipped": skipped,
            "total": skipped,
        }

    hashes = hash_passwords_bulk([p["password"] for p in parsed_rows], rounds=8)
    user_dicts = []
    for item, pwd_hash in zip(parsed_rows, hashes):
        user_dicts.append({
            "username": item["username"],
            "full_name": item["name"],
            "password_hash": pwd_hash,
            "role": "FACULTY",
            "department_id": default_dept.id if default_dept else None,
            "status": "ACTIVE"
        })

    stmt_u = insert(User).values(user_dicts).returning(User.id, User.username)
    res_u = await db.execute(stmt_u)
    u_map = {row.username: row.id for row in res_u.all()}

    fac_dicts = []
    for item in parsed_rows:
        fac_dicts.append({
            "user_id": u_map[item["username"]],
            "faculty_code": item["faculty_id"],
            "department_id": default_dept.id if default_dept else None,
            "name": item["name"],
            "designation": "Assistant Professor",
            "status": "ACTIVE"
        })

    stmt_f = insert(Faculty).values(fac_dicts)
    await db.execute(stmt_f)
    await db.commit()
    _ADMIN_ANALYTICS_CACHE.clear()

    return {
        "message": f"Faculty import complete. {len(parsed_rows)} account(s) created, {skipped} skipped (username already exists).",
        "inserted": len(parsed_rows),
        "skipped": skipped,
        "total": len(parsed_rows) + skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – SUBJECTS (Excel upload)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/subjects")
async def import_subjects(
    file: UploadFile = File(...),
    current_user: dict = _admin_dep,
    db: AsyncSession = Depends(get_db)
):
    """
    Upload an .xlsx file to bulk-add subjects.
    Required columns: SubjectID | SubjectName | ClassID
    Optional columns: FacultyID
    """
    import openpyxl

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    ws_xl = wb.active

    raw_headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws_xl.iter_rows(max_row=1))]

    sub_id_col   = _find_col(["subjectid", "subject_id", "subid", "courseid", "coursecode", "code"], raw_headers)
    name_col     = _find_col(["subjectname", "subject_name", "subname", "coursename", "name", "title"], raw_headers)
    class_col    = _find_col(["classid", "class_id", "class", "section"], raw_headers)
    fac_col      = _find_col(["facultyid", "faculty_id", "staffid", "facid", "teacherid"], raw_headers)

    missing = []
    if sub_id_col == -1: missing.append("SubjectID")
    if name_col == -1: missing.append("SubjectName")
    if class_col == -1: missing.append("ClassID")

    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Missing required columns: {', '.join(missing)}. Required: SubjectID, SubjectName, ClassID. Optional: FacultyID",
        )

    stmt_classes = select(ClassRoom)
    classes = (await db.execute(stmt_classes)).scalars().all()
    class_map = {c.class_code.upper(): c for c in classes}

    stmt_subs = select(Subject)
    existing_subs = {(s.subject_code.upper(), s.class_id) for s in (await db.execute(stmt_subs)).scalars().all()}

    subjects_to_add = []
    errors = []
    skipped = 0

    for row_num, row in enumerate(ws_xl.iter_rows(min_row=2, values_only=True), start=2):
        subject_id   = str(row[sub_id_col]).strip().upper() if sub_id_col < len(row) and row[sub_id_col] is not None else ""
        subject_name = str(row[name_col]).strip() if name_col < len(row) and row[name_col] is not None else ""
        class_code   = str(row[class_col]).strip().upper() if class_col < len(row) and row[class_col] is not None else ""
        faculty_id   = str(row[fac_col]).strip() if fac_col != -1 and fac_col < len(row) and row[fac_col] is not None else ""

        if not subject_id and not subject_name and not class_code:
            continue

        if not subject_id or not subject_name or not class_code:
            errors.append(f"Row {row_num}: SubjectID, SubjectName, and ClassID are all required.")
            continue

        cls_obj = class_map.get(class_code)
        if not cls_obj:
            errors.append(f"Row {row_num}: Class '{class_code}' does not exist.")
            continue

        if (subject_id, cls_obj.id) in existing_subs:
            skipped += 1
            continue

        existing_subs.add((subject_id, cls_obj.id))
        subjects_to_add.append(Subject(
            subject_code=subject_id,
            subject_name=subject_name,
            class_id=cls_obj.id,
            department_id=cls_obj.department_id,
            status="ACTIVE"
        ))

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": "Errors found in subjects file:", "errors": errors[:20]},
        )

    if subjects_to_add:
        db.add_all(subjects_to_add)
        await db.commit()
        _ADMIN_ANALYTICS_CACHE.clear()

    return {
        "message": f"Subjects import complete. {len(subjects_to_add)} subject(s) added successfully, {skipped} skipped.",
        "inserted": len(subjects_to_add),
        "skipped": skipped,
        "total": len(subjects_to_add) + skipped,
    }
