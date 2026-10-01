# =============================================================================
# sheets.py  –  Google Sheets helper layer
# All direct gspread / Google API calls live here.
# =============================================================================
import json, os, re, time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound

from config import get_settings


# ─────────────────────────────────────────────────────────────────────────────
# Simple TTL in-memory cache  (avoids hammering Sheets API / hitting 429)
# ─────────────────────────────────────────────────────────────────────────────
_CACHE: Dict[str, tuple] = {}   # key -> (value, expires_at)


def _cache_get(key: str):
    """Return cached value if still valid, else None."""
    entry = _CACHE.get(key)
    if entry and time.monotonic() < entry[1]:
        return entry[0]
    return None


def _cache_set(key: str, value, ttl: float = 60.0):
    """Store value with a TTL (seconds)."""
    _CACHE[key] = (value, time.monotonic() + ttl)


def _cache_invalidate(*keys: str):
    """Delete one or more cache entries (call after any write)."""
    for k in keys:
        _CACHE.pop(k, None)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# ── Hour labels & schedule ──────────────────────────────────────────────────
HOUR_LABELS = {
    "H1": "H1 (9:00–9:45)",
    "H2": "H2 (9:45–10:30)",
    "H3": "H3 (10:40–11:25)",
    "H4": "H4 (11:25–12:10)",
    "H5": "H5 (12:50–1:35)",
    "H6": "H6 (1:35–2:20)",
    "H7": "H7 (2:30–3:15)",
    "H8": "H8 (3:15–4:00)",
}
ALL_HOURS = list(HOUR_LABELS.keys())   # ['H1', 'H2', ..., 'H8']


# ─────────────────────────────────────────────────────────────────────────────
# Auth / client
# ─────────────────────────────────────────────────────────────────────────────
_client: Optional[gspread.Client] = None


def _get_client() -> gspread.Client:
    global _client
    if _client is not None:
        return _client
    cfg = get_settings()
    if not cfg.GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var is not set.")
    creds_dict = json.loads(cfg.GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    _client = gspread.authorize(creds)
    return _client


def _open_by_id(sheet_id: str) -> gspread.Spreadsheet:
    return _get_client().open_by_key(sheet_id)


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────
def _date_col_header(d: date) -> str:
    """Returns 'DD-MM-YYYY' string used as the date super-header in class sheets."""
    return d.strftime("%d-%m-%Y")


def _col_letter(n: int) -> str:
    """Convert 1-based column index to A1-notation letter(s)."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result


# ─────────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────────
def get_all_users() -> List[Dict]:
    """Return all rows from the Users sheet (cached 60 s)."""
    cached = _cache_get("all_users")
    if cached is not None:
        return cached
    ws = _open_by_id(get_settings().USERS_SHEET_ID).worksheet("Users")
    data = ws.get_all_records()
    _cache_set("all_users", data, ttl=60)
    return data


def get_user_by_username(username: str) -> Optional[Dict]:
    users = get_all_users()
    for u in users:
        if str(u.get("Username", "")).strip().lower() == username.strip().lower():
            return u
    return None


def create_user(user_data: Dict) -> None:
    ws = _open_by_id(get_settings().USERS_SHEET_ID).worksheet("Users")
    # Expected headers: UserID, Name, Username, PasswordHash, Role, ClassID
    ws.append_row([
        user_data["user_id"],
        user_data["name"],
        user_data["username"],
        user_data["password_hash"],
        user_data["role"],
        user_data.get("class_id", ""),
    ])
    _cache_invalidate("all_users")


def update_user_password(username: str, new_hash: str) -> None:
    ws = _open_by_id(get_settings().USERS_SHEET_ID).worksheet("Users")
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):   # row 1 = header
        if str(row.get("Username", "")).strip().lower() == username.lower():
            headers = ws.row_values(1)
            col = headers.index("PasswordHash") + 1
            ws.update_cell(i, col, new_hash)
            _cache_invalidate("all_users")
            return


def delete_user(username: str) -> None:
    ws = _open_by_id(get_settings().USERS_SHEET_ID).worksheet("Users")
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get("Username", "")).strip().lower() == username.lower():
            ws.delete_rows(i)
            _cache_invalidate("all_users")
            return


# ─────────────────────────────────────────────────────────────────────────────
# CLASSES
# ─────────────────────────────────────────────────────────────────────────────
def _get_all_classes_raw() -> List[Dict]:
    """Fetch ALL class rows (active + inactive) from Sheets, cached 60 s."""
    cached = _cache_get("all_classes_raw")
    if cached is not None:
        return cached
    ws = _open_by_id(get_settings().CLASSES_SHEET_ID).worksheet("Classes")
    data = ws.get_all_records()
    _cache_set("all_classes_raw", data, ttl=60)
    return data


def get_all_classes() -> List[Dict]:
    """Return active classes only (served from cache)."""
    return [r for r in _get_all_classes_raw() if r.get("Status", "").upper() != "INACTIVE"]


def get_class_by_id(class_id: str) -> Optional[Dict]:
    """Lookup a class by ID (served from cache)."""
    for r in _get_all_classes_raw():
        if str(r.get("ClassID", "")).strip() == class_id.strip():
            return r
    return None


def add_class(data: Dict) -> None:
    ws = _open_by_id(get_settings().CLASSES_SHEET_ID).worksheet("Classes")
    ws.append_row([
        data["class_id"],
        data["class_name"],
        data.get("year", ""),
        data.get("section", ""),
        data.get("semester", ""),
        "ACTIVE",
    ])
    _cache_invalidate("all_classes_raw")


def update_class_name(class_id: str, new_name: str) -> None:
    ws = _open_by_id(get_settings().CLASSES_SHEET_ID).worksheet("Classes")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    name_col = headers.index("ClassName") + 1
    for i, row in enumerate(records, start=2):
        if str(row.get("ClassID", "")).strip() == class_id.strip():
            ws.update_cell(i, name_col, new_name)
            _cache_invalidate("all_classes_raw")
            return


def deactivate_class(class_id: str) -> None:
    ws = _open_by_id(get_settings().CLASSES_SHEET_ID).worksheet("Classes")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    status_col = headers.index("Status") + 1
    for i, row in enumerate(records, start=2):
        if str(row.get("ClassID", "")).strip() == class_id.strip():
            ws.update_cell(i, status_col, "INACTIVE")
            _cache_invalidate("all_classes_raw")
            return


# ─────────────────────────────────────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────────────────────────────────────
def _get_all_subjects_raw() -> List[Dict]:
    """Fetch ALL subject rows, cached 60 s."""
    cached = _cache_get("all_subjects_raw")
    if cached is not None:
        return cached
    ws = _open_by_id(get_settings().SUBJECTS_SHEET_ID).worksheet("Subjects")
    data = ws.get_all_records()
    _cache_set("all_subjects_raw", data, ttl=60)
    return data


def get_subjects_for_class(class_id: str) -> List[Dict]:
    """Return active subjects for a class (served from cache)."""
    return [
        r for r in _get_all_subjects_raw()
        if str(r.get("ClassID", "")).strip() == class_id.strip()
        and r.get("Status", "").upper() != "INACTIVE"
    ]


def add_subject(data: Dict) -> None:
    ws = _open_by_id(get_settings().SUBJECTS_SHEET_ID).worksheet("Subjects")
    ws.append_row([
        data["subject_id"],
        data["class_id"],
        data["subject_name"],
        data.get("faculty_id", ""),
        "ACTIVE",
    ])
    _cache_invalidate("all_subjects_raw")


def delete_subject(subject_id: str) -> None:
    ws = _open_by_id(get_settings().SUBJECTS_SHEET_ID).worksheet("Subjects")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    status_col = headers.index("Status") + 1
    for i, row in enumerate(records, start=2):
        if str(row.get("SubjectID", "")).strip() == subject_id.strip():
            ws.update_cell(i, status_col, "INACTIVE")
            _cache_invalidate("all_subjects_raw")
            return


# ─────────────────────────────────────────────────────────────────────────────
# STUDENTS
# ─────────────────────────────────────────────────────────────────────────────
def _get_all_students_raw() -> List[Dict]:
    """Fetch ALL student rows (active + inactive), cached 60 s."""
    cached = _cache_get("all_students_raw")
    if cached is not None:
        return cached
    ws = _open_by_id(get_settings().STUDENTS_SHEET_ID).worksheet("Students")
    data = ws.get_all_records()
    _cache_set("all_students_raw", data, ttl=60)
    return data


def get_students_by_class(class_id: str) -> List[Dict]:
    """Return active students for a class (served from cache)."""
    return [
        r for r in _get_all_students_raw()
        if str(r.get("ClassID", "")).strip() == class_id.strip()
        and r.get("Status", "").upper() != "INACTIVE"
    ]


def get_all_students() -> List[Dict]:
    """Return all rows from the Students sheet (cached)."""
    return _get_all_students_raw()


def get_student_by_regnum(reg_num: str) -> Optional[Dict]:
    """Lookup a student by Reg No (served from cache)."""
    for r in _get_all_students_raw():
        if str(r.get("RegNo", "")).strip() == reg_num.strip():
            return r
    return None


def add_student(data: Dict) -> None:
    ws = _open_by_id(get_settings().STUDENTS_SHEET_ID).worksheet("Students")
    ws.append_row([
        data["reg_no"],
        data["name"],
        data["class_id"],
        data.get("class_name", ""),
        "ACTIVE",
    ])
    _cache_invalidate("all_students_raw")
    # Also add to class attendance sheet
    _ensure_student_in_class_sheet(data["class_id"], data["reg_no"], data["name"])


def deactivate_student(reg_no: str) -> None:
    ws = _open_by_id(get_settings().STUDENTS_SHEET_ID).worksheet("Students")
    records = ws.get_all_records()
    headers = ws.row_values(1)
    status_col = headers.index("Status") + 1
    for i, row in enumerate(records, start=2):
        if str(row.get("RegNo", "")).strip() == reg_no.strip():
            ws.update_cell(i, status_col, "INACTIVE")
            _cache_invalidate("all_students_raw")
            return


# ─────────────────────────────────────────────────────────────────────────────
# CLASS ATTENDANCE SHEETS
# ─────────────────────────────────────────────────────────────────────────────
def _get_class_spreadsheet(class_id: str) -> gspread.Spreadsheet:
    """Return the Spreadsheet for the given class via SpreadsheetID in Classes sheet."""
    client = _get_client()
    cfg = get_settings()
    cls_ws = _open_by_id(cfg.CLASSES_SHEET_ID).worksheet("Classes")
    records = cls_ws.get_all_records()
    for row in records:
        if str(row.get("ClassID", "")).strip() == class_id.strip():
            sid = str(row.get("SpreadsheetID", "")).strip()
            if sid:
                return client.open_by_key(sid)
    raise ValueError(f"No SpreadsheetID configured for class '{class_id}' in Classes sheet.")


def _get_class_id_for_spreadsheet(spreadsheet_id: str) -> Optional[str]:
    """Reverse lookup: given a spreadsheet ID, return its ClassID."""
    try:
        cls_ws = _open_by_id(get_settings().CLASSES_SHEET_ID).worksheet("Classes")
        for row in cls_ws.get_all_records():
            if str(row.get("SpreadsheetID", "")).strip() == spreadsheet_id.strip():
                return str(row.get("ClassID", "")).strip()
    except Exception:
        pass
    return None


# Row layout for every monthly class sheet:
#   Row 1 : "Reg No" | "Student Name" | <date1> | (empty x7) | <date2> | ...
#   Row 2 : (empty)  | (empty)        | H1 | H2 | .. | H8   | H1 | ...
#   Row 3+: student reg numbers and names, attendance values per cell
STUDENT_DATA_START_ROW = 3   # never change — used throughout this module


def _get_or_create_month_worksheet(spreadsheet: gspread.Spreadsheet, month_label: str) -> gspread.Worksheet:
    """Return (or create) a worksheet named e.g. 'Sep-2026'."""
    try:
        return spreadsheet.worksheet(month_label)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=month_label, rows=300, cols=300)
        # ── Two fixed header rows ─────────────────────────────────────────
        # Row 1 col A/B: column labels
        ws.update("A1:B2", [["Reg No", "Student Name"], ["", ""]])
        ws.format("A1:B1", {"textFormat": {"bold": True}})

        # ── Populate student rows starting at row 3 ───────────────────────
        # Get class_id stored in the spreadsheet's 'Info' sheet or look up via ClassID
        # We use the custom property stored when the sheet was created (see _get_class_spreadsheet)
        # Fallback: look up by matching SpreadsheetID in Classes sheet
        class_id = _get_class_id_for_spreadsheet(spreadsheet.id)
        if class_id:
            students_ws = _open_by_id(get_settings().STUDENTS_SHEET_ID).worksheet("Students")
            all_students = students_ws.get_all_records()
            rows = [
                [s["RegNo"], s["Name"]]
                for s in all_students
                if str(s.get("ClassID", "")).strip() == class_id
                and s.get("Status", "").upper() == "ACTIVE"
            ]
            if rows:
                ws.update(
                    f"A{STUDENT_DATA_START_ROW}:B{STUDENT_DATA_START_ROW - 1 + len(rows)}",
                    rows
                )
        return ws


def _find_or_create_date_hour_col(ws: gspread.Worksheet, date_str: str, hour: str) -> int:
    """
    Find column index for (date_str, hour) pair.
    Sheet layout (3-row header structure):
      Row 1 : "Reg No" | "Student Name" | <date1 merged 8 cols> | <date2> | ...
      Row 2 : ""       | ""             | H1 | H2 | H3 | H4 | H5 | H6 | H7 | H8 | repeat
      Row 3+: student data
    Returns 1-based column index.
    """
    row1 = ws.row_values(1)   # "Reg No", "Student Name", date1, "", ..., date2, ...
    row2 = ws.row_values(2)   # "",       "",             "H1", "H2", ...

    # Try to find existing date+hour combo (search from col C = index 2 onward)
    for i, val in enumerate(row1):
        if i < 2:
            continue   # skip "Reg No" and "Student Name" columns
        if val.strip() == date_str:
            # Found date block – search within next 8 cols for the hour
            for j in range(i, min(i + 8, len(row2))):
                if row2[j].strip().upper() == hour.upper():
                    return j + 1   # 1-based
            # Date exists but this hour slot not yet written – find first empty in block
            for j in range(i, i + 8):
                col_val = row2[j] if j < len(row2) else ""
                if not col_val:
                    ws.update_cell(1, j + 1, date_str)
                    ws.update_cell(2, j + 1, hour)
                    return j + 1

    # Date not found – calculate next 8-col block start (aligned to multiples of 8 from col C)
    filled_date_cols = sum(1 for v in row1[2:] if v.strip())  # how many C+ cells have a date
    used_blocks = filled_date_cols // 8
    new_block_0idx = 2 + used_blocks * 8   # 0-indexed column index

    col_idx = new_block_0idx
    ws.update_cell(1, col_idx + 1, date_str)
    ws.update_cell(2, col_idx + 1, hour)

    # Apply formatting to the new date and hour cells
    cl = _col_letter(col_idx + 1)
    ws.format(f"{cl}1", {
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.216, "green": 0.400, "blue": 0.698},
        "horizontalAlignment": "CENTER",
    })
    ws.format(f"{cl}2", {
        "textFormat": {"bold": True},
        "backgroundColor": {"red": 0.827, "green": 0.863, "blue": 0.949},
        "horizontalAlignment": "CENTER",
    })

    return col_idx + 1   # 1-based


def _ensure_student_in_class_sheet(class_id: str, reg_no: str, name: str) -> None:
    """Add student row to all existing month worksheets if not already present."""
    try:
        ss = _get_class_spreadsheet(class_id)
    except ValueError:
        return
    for ws in ss.worksheets():
        # col_a from row 3 onward (skip the 2 header rows)
        col_a_full = ws.col_values(1)   # 0-indexed list
        student_reg_nums = col_a_full[STUDENT_DATA_START_ROW - 1:]  # slice from row 3
        if reg_no not in student_reg_nums:
            # Next available row after existing students (never before STUDENT_DATA_START_ROW)
            next_row = max(STUDENT_DATA_START_ROW, len(col_a_full) + 1)
            ws.update(f"A{next_row}:B{next_row}", [[reg_no, name]])


def get_students_for_attendance(class_id: str) -> List[Dict]:
    """Return list of {reg_no, name} for a class (from master Students sheet)."""
    return [
        {"reg_no": r["RegNo"], "name": r["Name"]}
        for r in get_students_by_class(class_id)
    ]


def check_attendance_exists(class_id: str, date_str: str, hour: str, subject_id: str) -> bool:
    """Check Attendance_Log to see if this slot was already marked."""
    ws = _open_by_id(get_settings().ATTENDANCE_LOG_SHEET_ID).worksheet("Attendance_Log")
    records = ws.get_all_records()
    for r in records:
        if (
            str(r.get("ClassID", "")).strip() == class_id
            and str(r.get("Date", "")).strip() == date_str
            and str(r.get("Hour", "")).strip().upper() == hour.upper()
            and str(r.get("SubjectID", "")).strip() == subject_id
        ):
            return True
    return False


def save_attendance(
    class_id: str,
    date_str: str,
    hour: str,
    subject_id: str,
    faculty_id: str,
    attendance: Dict[str, str],   # {reg_no: "P"/"A"/"-"}
) -> None:
    """
    1. Write to class attendance sheet (visual register).
    2. Append rows to Attendance_Log.
    """
    # ── 1. Visual class sheet ──────────────────────────────────────────────
    ss = _get_class_spreadsheet(class_id)
    month_label = datetime.strptime(date_str, "%d-%m-%Y").strftime("%b-%Y")
    ws = _get_or_create_month_worksheet(ss, month_label)

    col_idx = _find_or_create_date_hour_col(ws, date_str, hour)

    # Get student rows — column A, skip the 2 header rows
    col_a_full = ws.col_values(1)   # 1-based values as 0-indexed list
    # Build a lookup: reg_no -> 1-based row number (only from row 3 onward)
    reg_to_row: Dict[str, int] = {}
    for i, val in enumerate(col_a_full):
        if i >= STUDENT_DATA_START_ROW - 1 and val.strip():  # skip rows 1 and 2
            reg_to_row[val.strip()] = i + 1  # 1-based

    updates = []
    for reg_no, status in attendance.items():
        row_idx = reg_to_row.get(reg_no.strip())
        if row_idx is None:
            continue
        updates.append({
            "range": f"{_col_letter(col_idx)}{row_idx}",
            "values": [[status]],
        })
    if updates:
        ws.batch_update(updates)

    # ── 2. Attendance_Log ─────────────────────────────────────────────────
    log_ws = _open_by_id(get_settings().ATTENDANCE_LOG_SHEET_ID).worksheet("Attendance_Log")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for reg_no, status in attendance.items():
        rows.append([
            "",           # ID – auto by sheet row number
            date_str,
            class_id,
            hour,
            subject_id,
            reg_no,
            status,
            faculty_id,
            now_str,
        ])
    if rows:
        log_ws.append_rows(rows, value_input_option="USER_ENTERED")


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT ATTENDANCE SUMMARY (read from Log)
# ─────────────────────────────────────────────────────────────────────────────
def get_student_attendance_summary(reg_no: str) -> Dict:
    """Compute attendance stats for a single student from Attendance_Log."""
    log_ws = _open_by_id(get_settings().ATTENDANCE_LOG_SHEET_ID).worksheet("Attendance_Log")
    records = log_ws.get_all_records()

    student_rows = [r for r in records if str(r.get("RegNo", "")).strip() == reg_no]

    # Overall
    total = len([r for r in student_rows if r.get("Status", "") != "-"])
    attended = len([r for r in student_rows if r.get("Status", "") == "P"])

    # Subject-wise
    subject_stats: Dict[str, Dict[str, int]] = {}
    for r in student_rows:
        if r.get("Status", "") == "-":
            continue
        sid = str(r.get("SubjectID", ""))
        if sid not in subject_stats:
            subject_stats[sid] = {"total": 0, "attended": 0}
        subject_stats[sid]["total"] += 1
        if r.get("Status", "") == "P":
            subject_stats[sid]["attended"] += 1

    # Get subject names
    sub_ws = _open_by_id(get_settings().SUBJECTS_SHEET_ID).worksheet("Subjects")
    sub_records = sub_ws.get_all_records()
    sub_name_map = {str(r["SubjectID"]): r["SubjectName"] for r in sub_records}

    subject_summary = []
    for sid, stats in subject_stats.items():
        pct = round(stats["attended"] / stats["total"] * 100, 2) if stats["total"] else 0
        subject_summary.append({
            "subject_id": sid,
            "subject_name": sub_name_map.get(sid, sid),
            "total": stats["total"],
            "attended": stats["attended"],
            "percentage": pct,
        })

    overall_pct = round(attended / total * 100, 2) if total else 0

    # Date-wise (last 30 days)
    date_hour_map: Dict[str, Dict[str, str]] = {}
    for r in student_rows:
        d = str(r.get("Date", ""))
        h = str(r.get("Hour", ""))
        if d not in date_hour_map:
            date_hour_map[d] = {}
        date_hour_map[d][h] = r.get("Status", "-")

    datewise = []
    for d in sorted(date_hour_map.keys()):
        row_dict = {"date": d}
        for h in ALL_HOURS:
            row_dict[h] = date_hour_map[d].get(h, "-")
        datewise.append(row_dict)

    return {
        "total_hours": total,
        "attended_hours": attended,
        "percentage": overall_pct,
        "subject_summary": subject_summary,
        "datewise": datewise[-60:],   # last 60 date entries
    }


# ─────────────────────────────────────────────────────────────────────────────
# PAST ATTENDANCE IMPORT
# ─────────────────────────────────────────────────────────────────────────────
def import_past_attendance_rows(rows: List[Dict]) -> int:
    """
    Bulk-insert past attendance into Attendance_Log (skip duplicates).
    Each row dict: date, class_id, hour, subject_id, reg_no, status, faculty_id
    Returns count of rows inserted.
    """
    log_ws = _open_by_id(get_settings().ATTENDANCE_LOG_SHEET_ID).worksheet("Attendance_Log")
    existing = log_ws.get_all_records()
    existing_keys = {
        (str(r["Date"]), str(r["ClassID"]), str(r["Hour"]), str(r["SubjectID"]), str(r["RegNo"]))
        for r in existing
    }

    new_rows = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for row in rows:
        key = (row["date"], row["class_id"], row["hour"], row["subject_id"], row["reg_no"])
        if key not in existing_keys:
            new_rows.append([
                "",
                row["date"],
                row["class_id"],
                row["hour"],
                row["subject_id"],
                row["reg_no"],
                row["status"],
                row.get("faculty_id", "IMPORT"),
                now_str,
            ])
            existing_keys.add(key)

    if new_rows:
        log_ws.append_rows(new_rows, value_input_option="USER_ENTERED")

    return len(new_rows)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN – Reports
# ─────────────────────────────────────────────────────────────────────────────
def get_class_attendance_report(class_id: str) -> List[Dict]:
    """Return per-student summary for all students in a class."""
    students = get_students_by_class(class_id)
    log_ws = _open_by_id(get_settings().ATTENDANCE_LOG_SHEET_ID).worksheet("Attendance_Log")
    records = log_ws.get_all_records()
    class_rows = [r for r in records if str(r.get("ClassID", "")).strip() == class_id]

    result = []
    for s in students:
        rn = str(s["RegNo"])
        student_rows = [r for r in class_rows if str(r.get("RegNo", "")).strip() == rn]
        total = len([r for r in student_rows if r.get("Status", "") != "-"])
        attended = len([r for r in student_rows if r.get("Status", "") == "P"])
        pct = round(attended / total * 100, 2) if total else 0
        result.append({
            "reg_no": rn,
            "name": s["Name"],
            "total": total,
            "attended": attended,
            "percentage": pct,
        })
    return result
