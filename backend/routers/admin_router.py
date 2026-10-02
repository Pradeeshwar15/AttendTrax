# =============================================================================
# routers/admin_router.py  –  Admin-only endpoints with Bulk Ingestion & Batch APIs
# =============================================================================
import io
import uuid
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from pydantic import BaseModel

import sheets
from auth import hash_password
from dependencies import require_role

router = APIRouter(prefix="/admin", tags=["Admin"])

_admin_dep = Depends(require_role("ADMIN"))


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
# CLASSES
# ─────────────────────────────────────────────────────────────────────────────
class AddClassRequest(BaseModel):
    class_id: str
    class_name: str
    year: Optional[str] = ""
    section: Optional[str] = ""
    semester: Optional[str] = ""


@router.get("/classes")
async def list_all_classes(_=_admin_dep):
    return sheets.get_all_classes()


@router.post("/classes")
async def add_class(body: AddClassRequest, _=_admin_dep):
    sheets.add_class(body.model_dump())
    return {"message": f"Class '{body.class_name}' added."}


class RenameClassRequest(BaseModel):
    new_name: str


@router.patch("/classes/{class_id}/rename")
async def rename_class(class_id: str, body: RenameClassRequest, _=_admin_dep):
    sheets.update_class_name(class_id, body.new_name)
    return {"message": "Class renamed."}


@router.delete("/classes/{class_id}")
async def deactivate_class(class_id: str, _=_admin_dep):
    sheets.deactivate_class(class_id)
    return {"message": "Class deactivated."}


# ─────────────────────────────────────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────────────────────────────────────
class AddSubjectRequest(BaseModel):
    subject_id: str
    class_id: str
    subject_name: str
    faculty_id: Optional[str] = ""


@router.get("/subjects")
async def list_all_subjects(class_id: Optional[str] = None, _=_admin_dep):
    if class_id:
        return sheets.get_subjects_for_class(class_id)
    return sheets.get_all_subjects()


@router.get("/classes/{class_id}/subjects")
async def list_subjects_for_class(class_id: str, _=_admin_dep):
    return sheets.get_subjects_for_class(class_id)


@router.post("/subjects")
async def add_subject(body: AddSubjectRequest, _=_admin_dep):
    sheets.add_subject(body.model_dump())
    return {"message": f"Subject '{body.subject_name}' added."}


@router.delete("/subjects/{subject_id}")
async def delete_subject(subject_id: str, _=_admin_dep):
    sheets.delete_subject(subject_id)
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
async def list_all_students(class_id: Optional[str] = None, _=_admin_dep):
    if class_id:
        return sheets.get_students_by_class(class_id)
    return sheets.get_all_students()


@router.get("/classes/{class_id}/students")
async def list_students(class_id: str, _=_admin_dep):
    return sheets.get_students_by_class(class_id)


@router.post("/students")
async def add_student(body: AddStudentRequest, _=_admin_dep):
    cls = sheets.get_class_by_id(body.class_id)
    class_name = body.class_name or (cls["ClassName"] if cls else body.class_id)

    sheets.add_student({
        "reg_no": body.reg_no,
        "name": body.name,
        "class_id": body.class_id,
        "class_name": class_name,
    })

    username = body.username or body.name
    password = body.password or body.reg_no
    sheets.create_user({
        "user_id": body.reg_no,
        "name": body.name,
        "username": username,
        "password_hash": hash_password(password),
        "role": "STUDENT",
        "class_id": body.class_id,
    })
    return {"message": f"Student '{body.name}' added with login '{username}'."}


@router.delete("/students/{reg_no}")
async def deactivate_student(reg_no: str, _=_admin_dep):
    sheets.deactivate_student(reg_no)
    return {"message": "Student deactivated."}


# ─────────────────────────────────────────────────────────────────────────────
# FACULTY ACCOUNTS
# ─────────────────────────────────────────────────────────────────────────────
class AddFacultyRequest(BaseModel):
    faculty_id: str
    name: str
    username: str
    password: str


@router.get("/faculty")
async def list_all_faculty(_=_admin_dep):
    return sheets.get_all_faculty()


@router.post("/faculty")
async def add_faculty(body: AddFacultyRequest, _=_admin_dep):
    sheets.create_user({
        "user_id": body.faculty_id,
        "name": body.name,
        "username": body.username,
        "password_hash": hash_password(body.password),
        "role": "FACULTY",
        "class_id": "",
    })
    return {"message": f"Faculty '{body.name}' added."}


@router.delete("/users/{username}")
async def delete_user(username: str, _=_admin_dep):
    sheets.delete_user(username)
    return {"message": f"User '{username}' deleted."}


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS & DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/analytics")
def get_analytics(_=_admin_dep):
    return sheets.get_admin_analytics()


# ─────────────────────────────────────────────────────────────────────────────
# REPORTS
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/reports/class/{class_id}")
def class_report(class_id: str, _=_admin_dep):
    return sheets.get_class_attendance_report(class_id)


@router.get("/reports/student/{reg_no}")
def student_report(reg_no: str, _=_admin_dep):
    return sheets.get_student_attendance_summary(reg_no)


# ─────────────────────────────────────────────────────────────────────────────
# DAILY ATTENDANCE MANAGEMENT & MODIFICATION
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


@router.get("/attendance/daily")
def get_daily_attendance(
    class_id: str,
    date: str,
    hour: str = "DAY",
    subject_id: str = "",
    _=_admin_dep,
):
    """Retrieve students and their existing attendance status for viewing/modifying."""
    return sheets.get_daily_attendance_for_edit(class_id, date, hour, subject_id)


@router.post("/attendance/modify")
def modify_daily_attendance(
    body: AdminModifyAttendanceRequest,
    current_user: dict = _admin_dep,
):
    """Admin endpoint to modify and resubmit attendance for any date/class/subject."""
    admin_id = str(current_user.get("UserID", "admin"))
    att_map = {e.reg_no.strip(): e.status.upper() for e in body.attendance}
    return sheets.admin_update_attendance(
        class_id=body.class_id,
        date_str=body.date,
        hour=body.hour,
        subject_id=body.subject_id,
        admin_id=admin_id,
        attendance=att_map,
    )


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – ATTENDANCE (Excel upload)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/attendance")
async def import_attendance(file: UploadFile = File(...), _=Depends(require_role("ADMIN"))):
    """
    Upload an .xlsx file with columns:
    Date | ClassID | Hour | SubjectID | RegNo | Status | FacultyID(opt)
    """
    import openpyxl

    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Only .xlsx files are supported.")

    contents = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents), data_only=True)
    ws_xl = wb.active

    raw_headers = [str(c.value).strip() if c.value is not None else "" for c in next(ws_xl.iter_rows(max_row=1))]

    date_col    = _find_col(["date", "datedd-mm-yyyy", "attendancedate", "sessiondate"], raw_headers)
    class_col   = _find_col(["classid", "class", "section", "classcode"], raw_headers)
    hour_col    = _find_col(["hour", "period", "session", "slot", "h"], raw_headers)
    sub_col     = _find_col(["subjectid", "subject", "subid", "courseid", "coursecode"], raw_headers)
    reg_col     = _find_col(["regno", "reg_no", "registerno", "rollno", "rollnumber", "regnum"], raw_headers)
    status_col  = _find_col(["status", "attendance", "attendancestatus", "mark", "state"], raw_headers)
    fac_col     = _find_col(["facultyid", "faculty_id", "staffid", "facid"], raw_headers)

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
            detail=f"Missing required columns: {', '.join(missing)}. "
                   f"Found headers: {', '.join(h for h in raw_headers if h)}",
        )

    rows = []
    errors = []

    for row_num, row in enumerate(ws_xl.iter_rows(min_row=2, values_only=True), start=2):
        raw_d  = row[date_col] if date_col < len(row) else ""
        raw_c  = str(row[class_col]).strip() if class_col < len(row) and row[class_col] is not None else ""
        raw_h  = str(row[hour_col]).strip().upper() if hour_col < len(row) and row[hour_col] is not None else ""
        raw_s  = str(row[sub_col]).strip() if sub_col < len(row) and row[sub_col] is not None else ""
        raw_rn = str(row[reg_col]).strip() if reg_col < len(row) and row[reg_col] is not None else ""
        raw_st = str(row[status_col]).strip().upper() if status_col < len(row) and row[status_col] is not None else ""
        raw_fac = str(row[fac_col]).strip() if fac_col != -1 and fac_col < len(row) and row[fac_col] is not None else "IMPORT"

        if not raw_d and not raw_c and not raw_rn:
            continue  # empty row

        # Normalize Hour (e.g. "1" -> "H1", "h1" -> "H1")
        if raw_h.isdigit():
            raw_h = f"H{raw_h}"
        elif raw_h.startswith("H") and len(raw_h) > 2:
            raw_h = raw_h[:2]

        # Normalize Status (e.g. "PRESENT" -> "P", "ABSENT" -> "A")
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
        if raw_h not in sheets.ALL_HOURS:
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

    inserted = sheets.import_past_attendance_rows(rows)
    return {
        "message": f"Import complete. {inserted} rows inserted into database (duplicates skipped).",
        "total_rows": len(rows),
        "inserted": inserted,
        "skipped": len(rows) - inserted,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – STUDENTS (Excel upload for All Classes at Once)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/students")
async def import_students(
    file: UploadFile = File(...),
    class_id: Optional[str] = Form(None),
    _=Depends(require_role("ADMIN")),
):
    """
    Upload an .xlsx file to bulk-add students.
    Columns: RegNo | Name | ClassID (opt if selected via form) | ClassName (opt) | Username (opt) | Password (opt)
    """
    import openpyxl

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

    # Class name lookup map
    all_classes = sheets.get_all_classes()
    class_name_map = {str(c["ClassID"]).strip(): str(c["ClassName"]).strip() for c in all_classes}

    # Existing reg nos and usernames
    existing_regnos = {
        str(s.get("RegNo", "")).strip().lower()
        for s in sheets.get_all_students()
    }
    existing_users = sheets.get_all_users()
    existing_usernames = {
        str(u.get("Username", "")).strip().lower()
        for u in existing_users
    }

    students_to_add = []
    users_to_add = []
    skipped = 0
    errors = []

    for row_num, row in enumerate(ws_xl.iter_rows(min_row=2, values_only=True), start=2):
        reg_no = str(row[reg_col]).strip() if reg_col < len(row) and row[reg_col] is not None else ""
        name   = str(row[name_col]).strip() if name_col < len(row) and row[name_col] is not None else ""
        
        # Class resolution: from Excel column or from Form fallback
        row_class = str(row[class_col]).strip() if class_col != -1 and class_col < len(row) and row[class_col] is not None else ""
        target_class_id = row_class or (class_id.strip() if class_id else "")

        if not reg_no and not name and not target_class_id:
            continue  # empty row

        if not reg_no:
            errors.append(f"Row {row_num}: Register number is required.")
            continue
        if not name:
            errors.append(f"Row {row_num}: Student name is required (reg: {reg_no}).")
            continue
        if not target_class_id:
            errors.append(f"Row {row_num} ({reg_no}): ClassID is missing. Specify in Excel or select a class.")
            continue

        if reg_no.lower() in existing_regnos:
            skipped += 1
            continue

        # Optional ClassName
        row_classname = str(row[classname_col]).strip() if classname_col != -1 and classname_col < len(row) and row[classname_col] is not None else ""
        target_class_name = row_classname or class_name_map.get(target_class_id, target_class_id)

        # Username / Password
        row_username = str(row[username_col]).strip() if username_col != -1 and username_col < len(row) and row[username_col] is not None else ""
        row_password = str(row[password_col]).strip() if password_col != -1 and password_col < len(row) and row[password_col] is not None else ""
        
        final_username = row_username or name
        final_password = row_password or reg_no

        students_to_add.append({
            "reg_no": reg_no,
            "name": name,
            "class_id": target_class_id,
            "class_name": target_class_name,
        })
        existing_regnos.add(reg_no.lower())

        # If username collides, suffix with reg_no to guarantee unique login
        if final_username.lower() in existing_usernames:
            final_username = f"{final_username} ({reg_no})"
        existing_usernames.add(final_username.lower())

        users_to_add.append({
            "user_id": reg_no,
            "name": name,
            "username": final_username,
            "password_hash": hash_password(final_password),
            "role": "STUDENT",
            "class_id": target_class_id,
        })

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": f"Errors encountered in upload:", "errors": errors[:20]},
        )

    # Batch insert all at once for speed
    inserted_students = sheets.add_students_batch(students_to_add)
    sheets.create_users_batch(users_to_add)

    return {
        "message": f"Import complete. {inserted_students} student(s) added successfully, {skipped} skipped (already existed).",
        "inserted": inserted_students,
        "skipped": skipped,
        "total": len(students_to_add) + skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – FACULTY (Excel upload)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/faculty")
async def import_faculty(file: UploadFile = File(...), _=Depends(require_role("ADMIN"))):
    """
    Upload an .xlsx file to bulk-add faculty accounts.
    Required columns: FacultyID | Name | Username | Password
    """
    import openpyxl

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

    existing_users = sheets.get_all_users()
    existing_usernames = {str(u.get("Username", "")).strip().lower() for u in existing_users}

    users_to_add = []
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

        if username.lower() in existing_usernames:
            skipped += 1
            continue

        users_to_add.append({
            "user_id": faculty_id,
            "name": name,
            "username": username,
            "password_hash": hash_password(password),
            "role": "FACULTY",
            "class_id": "",
        })
        existing_usernames.add(username.lower())

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": f"Errors found in faculty file:", "errors": errors[:20]},
        )

    inserted = sheets.create_users_batch(users_to_add)
    return {
        "message": f"Faculty import complete. {inserted} account(s) created, {skipped} skipped (username already exists).",
        "inserted": inserted,
        "skipped": skipped,
        "total": inserted + skipped,
    }


# ─────────────────────────────────────────────────────────────────────────────
# BULK IMPORT – SUBJECTS (Excel upload)
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/import/subjects")
async def import_subjects(file: UploadFile = File(...), _=Depends(require_role("ADMIN"))):
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

    subjects_to_add = []
    errors = []

    for row_num, row in enumerate(ws_xl.iter_rows(min_row=2, values_only=True), start=2):
        subject_id   = str(row[sub_id_col]).strip() if sub_id_col < len(row) and row[sub_id_col] is not None else ""
        subject_name = str(row[name_col]).strip() if name_col < len(row) and row[name_col] is not None else ""
        class_id     = str(row[class_col]).strip() if class_col < len(row) and row[class_col] is not None else ""
        faculty_id   = str(row[fac_col]).strip() if fac_col != -1 and fac_col < len(row) and row[fac_col] is not None else ""

        if not subject_id and not subject_name and not class_id:
            continue

        if not subject_id or not subject_name or not class_id:
            errors.append(f"Row {row_num}: SubjectID, SubjectName, and ClassID are all required.")
            continue

        subjects_to_add.append({
            "subject_id": subject_id,
            "class_id": class_id,
            "subject_name": subject_name,
            "faculty_id": faculty_id,
        })

    if errors:
        raise HTTPException(
            status_code=422,
            detail={"message": f"Errors found in subjects file:", "errors": errors[:20]},
        )

    inserted = sheets.add_subjects_batch(subjects_to_add)
    return {
        "message": f"Subjects import complete. {inserted} subject(s) added successfully.",
        "inserted": inserted,
        "skipped": 0,
        "total": inserted,
    }
