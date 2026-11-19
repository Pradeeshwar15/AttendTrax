# =============================================================================
# routers/student_router.py  –  Student (read-only) Pure SQL endpoints
# =============================================================================
from datetime import date, datetime
from typing import Dict, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, and_, or_, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_role
from models import Student, ClassRoom, Department, User, AttendanceRecord, AttendanceSession, Subject

router = APIRouter(prefix="/student", tags=["Student"])

_student_dep = Depends(require_role("STUDENT", "ADMIN"))

ALL_HOURS = ["DAY", "PERIOD_1", "PERIOD_2", "PERIOD_3", "PERIOD_4", "PERIOD_5", "PERIOD_6", "PERIOD_7", "PERIOD_8", "PLACEMENT"]


@router.get("/profile")
async def get_profile(
    current_user: dict = _student_dep,
    db: AsyncSession = Depends(get_db),
):
    """Return the student's own profile from pure SQL."""
    username = str(current_user.get("Username") or current_user.get("sub") or "").strip()
    uid = current_user.get("user_id") or current_user.get("UserID")
    reg_hint = str(current_user.get("reg_no") or current_user.get("RegNo") or "").strip()

    stmt = (
        select(Student, ClassRoom, Department)
        .outerjoin(ClassRoom, Student.class_id == ClassRoom.id)
        .outerjoin(Department, Student.department_id == Department.id)
    )
    if reg_hint:
        stmt = stmt.where(Student.reg_no == reg_hint)
    elif uid and str(uid).isdigit():
        stmt = stmt.where(or_(Student.user_id == int(uid), Student.reg_no == username))
    else:
        stmt = stmt.where(Student.reg_no == username)

    res = await db.execute(stmt)
    row = res.first()
    if not row:
        raise HTTPException(status_code=404, detail="Student record not found.")

    st, cls, dept = row
    return {
        "RegNo": st.reg_no,
        "reg_no": st.reg_no,
        "Name": st.name,
        "name": st.name,
        "ClassID": cls.class_code if cls else "",
        "class_id": cls.class_code if cls else "",
        "ClassName": cls.class_name if cls else "",
        "Department": dept.name if dept else "",
        "DepartmentCode": dept.code if dept else "",
        "ResidenceType": st.residence_type,
        "Status": st.status,
    }


@router.get("/attendance")
async def get_attendance(
    current_user: dict = _student_dep,
    db: AsyncSession = Depends(get_db),
):
    """Return full attendance summary for the logged-in student via pure SQL."""
    username = str(current_user.get("Username") or current_user.get("sub") or "").strip()
    uid = current_user.get("user_id") or current_user.get("UserID")
    reg_hint = str(current_user.get("reg_no") or current_user.get("RegNo") or "").strip()

    stmt_st = select(Student.id).where(
        or_(
            Student.reg_no == reg_hint,
            Student.reg_no == username,
            Student.user_id == (int(uid) if uid and str(uid).isdigit() else -1)
        )
    )
    st_id = (await db.execute(stmt_st)).scalar_one_or_none()
    if not st_id:
        return {
            "total_hours": 0,
            "attended_hours": 0,
            "od_hours": 0,
            "percentage": 0.0,
            "subject_summary": [],
            "datewise": [],
        }

    # Fetch all attendance records with session details
    stmt_rec = (
        select(
            AttendanceRecord.status,
            AttendanceSession.session_date,
            AttendanceSession.slot_hour,
            Subject.subject_code,
            Subject.subject_name
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
        subject_summary.append({
            **s_info,
            "percentage": s_pct,
        })

    effective_attended = attended + od
    overall_pct = round((effective_attended / total) * 100, 1) if total else 0.0

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
