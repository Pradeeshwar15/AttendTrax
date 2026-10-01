# =============================================================================
# routers/faculty_router.py  –  Faculty endpoints
# =============================================================================
from datetime import date
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

import sheets
from dependencies import require_role
from sheets import ALL_HOURS, HOUR_LABELS

router = APIRouter(prefix="/faculty", tags=["Faculty"])

_faculty_dep = Depends(require_role("FACULTY", "ADMIN"))


# ── GET helpers ───────────────────────────────────────────────────────────────
@router.get("/classes")
async def list_classes(current_user: dict = _faculty_dep):
    """Return all active classes (faculty needs to select one)."""
    return sheets.get_all_classes()


@router.get("/classes/{class_id}/subjects")
async def list_subjects(class_id: str, current_user: dict = _faculty_dep):
    """Return subjects assigned to a class."""
    return sheets.get_subjects_for_class(class_id)


@router.get("/hours")
async def list_hours(_=_faculty_dep):
    """Return hour labels."""
    return [{"value": k, "label": v} for k, v in HOUR_LABELS.items()]


@router.get("/classes/{class_id}/students")
async def list_students(class_id: str, _=_faculty_dep):
    """Return students for attendance marking."""
    return sheets.get_students_for_attendance(class_id)


# ── Attendance submission ─────────────────────────────────────────────────────
class AttendanceEntry(BaseModel):
    reg_no: str
    status: str   # "P", "A", or "-"


class SubmitAttendanceRequest(BaseModel):
    class_id: str
    subject_id: str
    hour: str
    attendance: List[AttendanceEntry]


@router.post("/attendance")
async def submit_attendance(
    body: SubmitAttendanceRequest,
    current_user: dict = _faculty_dep,
):
    # Validate hour
    if body.hour.upper() not in ALL_HOURS:
        raise HTTPException(status_code=400, detail=f"Invalid hour. Must be one of {ALL_HOURS}.")

    # Validate status values
    for entry in body.attendance:
        if entry.status not in ("P", "A", "-"):
            raise HTTPException(status_code=400, detail=f"Invalid status '{entry.status}'. Use P, A, or -.")

    # Auto fetch today's date
    today_str = date.today().strftime("%d-%m-%Y")

    # ── Immutability check (backend-enforced) ────────────────────────────
    if sheets.check_attendance_exists(body.class_id, today_str, body.hour.upper(), body.subject_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Attendance for {body.class_id} / {body.hour} / {body.subject_id} "
                f"on {today_str} has already been submitted and cannot be modified."
            ),
        )

    faculty_id = str(current_user.get("UserID", ""))
    attendance_map: Dict[str, str] = {e.reg_no: e.status for e in body.attendance}

    sheets.save_attendance(
        class_id=body.class_id,
        date_str=today_str,
        hour=body.hour.upper(),
        subject_id=body.subject_id,
        faculty_id=faculty_id,
        attendance=attendance_map,
    )
    return {"message": "Attendance saved successfully.", "date": today_str}


# ── Check if slot already submitted ──────────────────────────────────────────
@router.get("/attendance/check")
async def check_slot(
    class_id: str,
    subject_id: str,
    hour: str,
    _=_faculty_dep,
):
    today_str = date.today().strftime("%d-%m-%Y")
    exists = sheets.check_attendance_exists(class_id, today_str, hour.upper(), subject_id)
    return {"already_submitted": exists, "date": today_str}
