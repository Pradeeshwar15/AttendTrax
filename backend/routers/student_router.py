# =============================================================================
# routers/student_router.py  –  Student (read-only) endpoints
# =============================================================================
from fastapi import APIRouter, Depends, HTTPException, status

import sheets
from dependencies import require_role

router = APIRouter(prefix="/student", tags=["Student"])

_student_dep = Depends(require_role("STUDENT", "ADMIN"))


@router.get("/profile")
async def get_profile(current_user: dict = _student_dep):
    """Return the student's own profile."""
    reg_no = str(current_user.get("ClassID", ""))   # For students, ClassID stores their reg_no mapping
    # Actually we store reg_no via UserID == RegNo for students
    reg_no = str(current_user.get("UserID", ""))
    student = sheets.get_student_by_regnum(reg_no)
    if not student:
        raise HTTPException(status_code=404, detail="Student record not found.")
    return student


@router.get("/attendance")
async def get_attendance(current_user: dict = _student_dep):
    """Return full attendance summary for the logged-in student."""
    reg_no = str(current_user.get("UserID", ""))
    return sheets.get_student_attendance_summary(reg_no)
