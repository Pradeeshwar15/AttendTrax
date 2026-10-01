# =============================================================================
# sheets.py  –  Google Sheets helper layer with High-Performance Caching
# All direct gspread / Google API calls live here.
# =============================================================================
import json, os, re, time, threading
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound

from config import get_settings

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
# In-Memory Cache & Client Handles
# ─────────────────────────────────────────────────────────────────────────────
_client: Optional[gspread.Client] = None
_client_lock = threading.Lock()

_spreadsheet_cache: Dict[str, gspread.Spreadsheet] = {}
_worksheet_cache: Dict[Tuple[str, str], gspread.Worksheet] = {}
_cache_lock = threading.Lock()

# Data Cache: key -> (timestamp, data)
_data_cache: Dict[str, Tuple[float, Any]] = {}
DEFAULT_CACHE_TTL = 60.0  # seconds


def _get_client() -> gspread.Client:
    global _client
    if _client is not None:
        return _client
    with _client_lock:
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
    if not sheet_id:
        raise ValueError("Spreadsheet ID is empty.")
    with _cache_lock:
        if sheet_id in _spreadsheet_cache:
            return _spreadsheet_cache[sheet_id]
    
    ss = _get_client().open_by_key(sheet_id)
    with _cache_lock:
        _spreadsheet_cache[sheet_id] = ss
    return ss


def _get_worksheet(sheet_id: str, title: str) -> gspread.Worksheet:
    cache_key = (sheet_id, title)
    with _cache_lock:
        if cache_key in _worksheet_cache:
            return _worksheet_cache[cache_key]
    
    ss = _open_by_id(sheet_id)
    ws = ss.worksheet(title)
    with _cache_lock:
        _worksheet_cache[cache_key] = ws
    return ws


def get_cached(key: str, fetcher, ttl: float = DEFAULT_CACHE_TTL) -> Any:
    now = time.time()
    with _cache_lock:
        if key in _data_cache:
            ts, val = _data_cache[key]
            if now - ts < ttl:
                return val
    # Fetch outside lock to allow concurrency
    fresh_val = fetcher()
    with _cache_lock:
        _data_cache[key] = (time.time(), fresh_val)
    return fresh_val


def invalidate_cache(*keys: str) -> None:
    with _cache_lock:
        if not keys:
            _data_cache.clear()
        else:
            for k in keys:
                _data_cache.pop(k, None)


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
# Formula / CSV Injection Sanitizer
# ─────────────────────────────────────────────────────────────────────────────
def sanitize_sheet_cell(val: Any) -> Any:
    """
    Neutralizes CSV / Formula Injection attacks when writing to Google Sheets.
    If a string starts with =, +, -, @, \\t, or \\r, prefix with a single quote (')
    unless it represents a valid numeric value.
    """
    if isinstance(val, str):
        s = val.strip()
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
            try:
                float(s)
                return val
            except ValueError:
                return "'" + val
    return val


def sanitize_sheet_row(row: List[Any]) -> List[Any]:
    return [sanitize_sheet_cell(c) for c in row]


# ─────────────────────────────────────────────────────────────────────────────
# USERS
# ─────────────────────────────────────────────────────────────────────────────
def get_all_users() -> List[Dict]:
    """Return all rows from the Users sheet (cached)."""
    def _fetch():
        ws = _get_worksheet(get_settings().USERS_SHEET_ID, "Users")
        return ws.get_all_records()
    return get_cached("users", _fetch, ttl=60.0)


def get_user_by_username(username: str) -> Optional[Dict]:
    users = get_all_users()
    uname = username.strip().lower()
    for u in users:
        if str(u.get("Username", "")).strip().lower() == uname:
            return u
        if str(u.get("UserID", "")).strip().lower() == uname:
            return u
    return None


def create_user(user_data: Dict) -> None:
    ws = _get_worksheet(get_settings().USERS_SHEET_ID, "Users")
    ws.append_row(sanitize_sheet_row([
        user_data["user_id"],
        user_data["name"],
        user_data["username"],
        user_data["password_hash"],
        user_data["role"],
        user_data.get("class_id", ""),
    ]))
    invalidate_cache("users")


def create_users_batch(users_list: List[Dict]) -> int:
    if not users_list:
        return 0
    ws = _get_worksheet(get_settings().USERS_SHEET_ID, "Users")
    rows = [
        sanitize_sheet_row([
            u["user_id"],
            u["name"],
            u["username"],
            u["password_hash"],
            u["role"],
            u.get("class_id", ""),
        ])
        for u in users_list
    ]
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    invalidate_cache("users")
    return len(rows)


def get_all_faculty() -> List[Dict]:
    users = get_all_users()
    return [
        {
            "FacultyID": u.get("UserID", ""),
            "Name": u.get("Name", ""),
            "Username": u.get("Username", ""),
            "Role": u.get("Role", ""),
        }
        for u in users
        if str(u.get("Role", "")).upper() == "FACULTY"
    ]


def update_user_password(username: str, new_hash: str) -> None:
    ws = _get_worksheet(get_settings().USERS_SHEET_ID, "Users")
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):   # row 1 = header
        if str(row.get("Username", "")).strip().lower() == username.lower():
            # Standard order: UserID, Name, Username, PasswordHash, Role, ClassID -> col 4
            col = 4
            if "PasswordHash" in row:
                headers = list(records[0].keys()) if records else []
                if "PasswordHash" in headers:
                    col = headers.index("PasswordHash") + 1
            ws.update_cell(i, col, new_hash)
            invalidate_cache("users")
            return


def delete_user(username: str) -> None:
    ws = _get_worksheet(get_settings().USERS_SHEET_ID, "Users")
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get("Username", "")).strip().lower() == username.lower():
            ws.delete_rows(i)
            invalidate_cache("users")
            return


# ─────────────────────────────────────────────────────────────────────────────
# CLASSES
# ─────────────────────────────────────────────────────────────────────────────
def _get_raw_classes() -> List[Dict]:
    def _fetch():
        ws = _get_worksheet(get_settings().CLASSES_SHEET_ID, "Classes")
        return ws.get_all_records()
    return get_cached("classes_raw", _fetch, ttl=60.0)


def get_all_classes() -> List[Dict]:
    return [r for r in _get_raw_classes() if r.get("Status", "").upper() == "ACTIVE"]


def get_class_by_id(class_id: str) -> Optional[Dict]:
    cid = class_id.strip()
    for r in _get_raw_classes():
        if str(r.get("ClassID", "")).strip() == cid:
            return r
    return None


def add_class(data: Dict) -> None:
    ws = _get_worksheet(get_settings().CLASSES_SHEET_ID, "Classes")
    ws.append_row(sanitize_sheet_row([
        data["class_id"],
        data["class_name"],
        data.get("year", ""),
        data.get("section", ""),
        data.get("semester", ""),
        "ACTIVE",
    ]))
    invalidate_cache("classes_raw")


def update_class_name(class_id: str, new_name: str) -> None:
    ws = _get_worksheet(get_settings().CLASSES_SHEET_ID, "Classes")
    records = ws.get_all_records()
    name_col = 2  # ClassName is column 2
    for i, row in enumerate(records, start=2):
        if str(row.get("ClassID", "")).strip() == class_id.strip():
            ws.update_cell(i, name_col, sanitize_sheet_cell(new_name))
            invalidate_cache("classes_raw")
            return


def deactivate_class(class_id: str) -> None:
    ws = _get_worksheet(get_settings().CLASSES_SHEET_ID, "Classes")
    records = ws.get_all_records()
    status_col = 6  # Status is column 6
    for i, row in enumerate(records, start=2):
        if str(row.get("ClassID", "")).strip() == class_id.strip():
            ws.update_cell(i, status_col, "INACTIVE")
            invalidate_cache("classes_raw")
            return


# ─────────────────────────────────────────────────────────────────────────────
# SUBJECTS
# ─────────────────────────────────────────────────────────────────────────────
def _get_raw_subjects() -> List[Dict]:
    def _fetch():
        ws = _get_worksheet(get_settings().SUBJECTS_SHEET_ID, "Subjects")
        return ws.get_all_records()
    return get_cached("subjects_raw", _fetch, ttl=60.0)


def get_all_subjects() -> List[Dict]:
    return [
        r for r in _get_raw_subjects()
        if r.get("Status", "").upper() == "ACTIVE"
    ]


def get_subjects_for_class(class_id: str) -> List[Dict]:
    cid = class_id.strip()
    return [
        r for r in _get_raw_subjects()
        if str(r.get("ClassID", "")).strip() == cid
        and r.get("Status", "").upper() == "ACTIVE"
    ]


def add_subject(data: Dict) -> None:
    ws = _get_worksheet(get_settings().SUBJECTS_SHEET_ID, "Subjects")
    ws.append_row(sanitize_sheet_row([
        data["subject_id"],
        data["class_id"],
        data["subject_name"],
        data.get("faculty_id", ""),
        "ACTIVE",
    ]))
    invalidate_cache("subjects_raw")


def add_subjects_batch(subjects_list: List[Dict]) -> int:
    if not subjects_list:
        return 0
    ws = _get_worksheet(get_settings().SUBJECTS_SHEET_ID, "Subjects")
    rows = [
        sanitize_sheet_row([
            s["subject_id"],
            s["class_id"],
            s["subject_name"],
            s.get("faculty_id", ""),
            "ACTIVE",
        ])
        for s in subjects_list
    ]
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    invalidate_cache("subjects_raw")
    return len(rows)


def delete_subject(subject_id: str) -> None:
    ws = _get_worksheet(get_settings().SUBJECTS_SHEET_ID, "Subjects")
    records = ws.get_all_records()
    status_col = 5  # Status is column 5
    for i, row in enumerate(records, start=2):
        if str(row.get("SubjectID", "")).strip() == subject_id.strip():
            ws.update_cell(i, status_col, "INACTIVE")
            invalidate_cache("subjects_raw")
            return


# ─────────────────────────────────────────────────────────────────────────────
# STUDENTS
# ─────────────────────────────────────────────────────────────────────────────
def _get_raw_students() -> List[Dict]:
    def _fetch():
        ws = _get_worksheet(get_settings().STUDENTS_SHEET_ID, "Students")
        return ws.get_all_records()
    return get_cached("students_raw", _fetch, ttl=60.0)


def get_students_by_class(class_id: str) -> List[Dict]:
    cid = class_id.strip()
    return [
        r for r in _get_raw_students()
        if str(r.get("ClassID", "")).strip() == cid
        and r.get("Status", "").upper() == "ACTIVE"
    ]


def get_all_students() -> List[Dict]:
    return _get_raw_students()


def get_student_by_regnum(reg_num: str) -> Optional[Dict]:
    rnum = reg_num.strip().lower()
    for r in _get_raw_students():
        if str(r.get("RegNo", "")).strip().lower() == rnum:
            return r
    return None


def add_student(data: Dict) -> None:
    ws = _get_worksheet(get_settings().STUDENTS_SHEET_ID, "Students")
    ws.append_row(sanitize_sheet_row([
        data["reg_no"],
        data["name"],
        data["class_id"],
        data.get("class_name", ""),
        "ACTIVE",
    ]))
    invalidate_cache("students_raw")
    # Also add to class attendance sheet
    _ensure_student_in_class_sheet(data["class_id"], data["reg_no"], data["name"])


def add_students_batch(students_list: List[Dict]) -> int:
    if not students_list:
        return 0
    ws = _get_worksheet(get_settings().STUDENTS_SHEET_ID, "Students")
    rows = [
        sanitize_sheet_row([
            s["reg_no"],
            s["name"],
            s["class_id"],
            s.get("class_name", ""),
            "ACTIVE",
        ])
        for s in students_list
    ]
    ws.append_rows(rows, value_input_option="USER_ENTERED")
    invalidate_cache("students_raw")
    # Also update class sheets
    for s in students_list:
        try:
            _ensure_student_in_class_sheet(s["class_id"], s["reg_no"], s["name"])
        except Exception:
            pass
    return len(rows)


def deactivate_student(reg_no: str) -> None:
    ws = _get_worksheet(get_settings().STUDENTS_SHEET_ID, "Students")
    records = ws.get_all_records()
    status_col = 5  # Status is column 5
    for i, row in enumerate(records, start=2):
        if str(row.get("RegNo", "")).strip() == reg_no.strip():
            ws.update_cell(i, status_col, "INACTIVE")
            invalidate_cache("students_raw")
            return


# ─────────────────────────────────────────────────────────────────────────────
# CLASS ATTENDANCE SHEETS
# ─────────────────────────────────────────────────────────────────────────────
def _get_class_spreadsheet(class_id: str) -> gspread.Spreadsheet:
    """Return the Spreadsheet for the given class via SpreadsheetID in Classes sheet or setup_sheets."""
    records = _get_raw_classes()
    cid = str(class_id).strip()
    for row in records:
        if str(row.get("ClassID", "")).strip() == cid:
            sid = str(row.get("SpreadsheetID", "")).strip()
            if sid:
                return _open_by_id(sid)
    # Fallback lookup in setup_sheets.SHEET_IDS
    try:
        from setup_sheets import SHEET_IDS
        if cid in SHEET_IDS and SHEET_IDS[cid].strip():
            return _open_by_id(SHEET_IDS[cid].strip())
    except Exception:
        pass
    raise ValueError(f"No SpreadsheetID configured for class '{class_id}' in Classes sheet or setup_sheets.py.")


def _get_class_id_for_spreadsheet(spreadsheet_id: str) -> Optional[str]:
    """Reverse lookup: given a spreadsheet ID, return its ClassID."""
    try:
        for row in _get_raw_classes():
            if str(row.get("SpreadsheetID", "")).strip() == spreadsheet_id.strip():
                return str(row.get("ClassID", "")).strip()
    except Exception:
        pass
    return None


STUDENT_DATA_START_ROW = 3   # fixed row 3 for student attendance


def _get_or_create_month_worksheet(spreadsheet: gspread.Spreadsheet, month_label: str) -> gspread.Worksheet:
    """Return (or create) a worksheet named e.g. 'Sep-2026'."""
    try:
        return spreadsheet.worksheet(month_label)
    except WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=month_label, rows=300, cols=300)
        ws.update("A1:B2", [["Reg No", "Student Name"], ["", ""]])
        ws.format("A1:B1", {"textFormat": {"bold": True}})

        class_id = _get_class_id_for_spreadsheet(spreadsheet.id)
        if class_id:
            all_students = _get_raw_students()
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


def _find_or_create_date_hour_col(ws: gspread.Worksheet, date_str: str, hour: str = "DAY") -> int:
    """Finds or creates the date column in the daily attendance register."""
    row2 = ws.row_values(2)
    row1 = ws.row_values(1)

    # 1. Check if date_str is already in row 2 (daily format)
    target_d = date_str.strip()
    # Normalize variants like "1-10-2026" vs "01-10-2026"
    for idx, val in enumerate(row2):
        if idx < 2:
            continue
        v = val.strip()
        if v == target_d:
            return idx + 1
        try:
            if datetime.strptime(v, "%d-%m-%Y") == datetime.strptime(target_d, "%d-%m-%Y"):
                return idx + 1
        except Exception:
            pass

    # 2. Check in row 1 (fallback)
    for idx, val in enumerate(row1):
        if idx < 2:
            continue
        if val.strip() == target_d:
            return idx + 1

    # 3. If not found, place before summary columns if present, or at the end
    insert_idx = len(row2)
    for idx, val in enumerate(row2):
        if "total present" in val.strip().lower() or "total" in val.strip().lower():
            insert_idx = idx
            break

    ws.update_cell(2, insert_idx + 1, target_d)
    cl = _col_letter(insert_idx + 1)
    ws.format(f"{cl}2", {
        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
        "backgroundColor": {"red": 0.231, "green": 0.510, "blue": 0.965},
        "horizontalAlignment": "CENTER",
    })
    return insert_idx + 1



def _ensure_student_in_class_sheet(class_id: str, reg_no: str, name: str) -> None:
    try:
        ss = _get_class_spreadsheet(class_id)
    except ValueError:
        return
    for ws in ss.worksheets():
        col_a_full = ws.col_values(1)
        student_reg_nums = col_a_full[STUDENT_DATA_START_ROW - 1:]
        if reg_no not in student_reg_nums:
            next_row = max(STUDENT_DATA_START_ROW, len(col_a_full) + 1)
            ws.update(f"A{next_row}:B{next_row}", [[reg_no, name]])


def get_students_for_attendance(class_id: str) -> List[Dict]:
    return [
        {"reg_no": r["RegNo"], "name": r["Name"]}
        for r in get_students_by_class(class_id)
    ]


# ─────────────────────────────────────────────────────────────────────────────
# ATTENDANCE LOG (Cached for Instant Immuntability & Reporting)
# ─────────────────────────────────────────────────────────────────────────────
def _get_raw_attendance_log() -> List[Dict]:
    def _fetch():
        ws = _get_worksheet(get_settings().ATTENDANCE_LOG_SHEET_ID, "Attendance_Log")
        return ws.get_all_records()
    return get_cached("attendance_log_raw", _fetch, ttl=30.0)


def check_attendance_exists(class_id: str, date_str: str, hour: str, subject_id: str = "") -> bool:
    records = _get_raw_attendance_log()
    cid = class_id.strip()
    dstr = date_str.strip()
    hr = hour.strip().upper()
    sid = subject_id.strip()
    for r in records:
        r_cid = str(r.get("ClassID", "")).strip()
        r_date = str(r.get("Date", "")).strip()
        r_hr = str(r.get("Hour", "")).strip().upper()
        r_sid = str(r.get("SubjectID", "")).strip()
        if r_cid == cid and r_date == dstr and (not hr or r_hr == hr or hr == "DAY"):
            if not sid or r_sid == sid:
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
    # ── 1. Visual class sheet ──────────────────────────────────────────────
    try:
        ss = _get_class_spreadsheet(class_id)
        month_label = datetime.strptime(date_str, "%d-%m-%Y").strftime("%b-%Y")
        ws = _get_or_create_month_worksheet(ss, month_label)

        col_idx = _find_or_create_date_hour_col(ws, date_str, hour)

        col_a_full = ws.col_values(1)
        reg_to_row: Dict[str, int] = {}
        for i, val in enumerate(col_a_full):
            if i >= STUDENT_DATA_START_ROW - 1 and val.strip():
                reg_to_row[val.strip()] = i + 1

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
    except Exception as ex:
        # Visual sheet error logged but doesn't crash log storage
        print(f"[Warning] Failed to update visual sheet for {class_id}: {ex}")

    # ── 2. Attendance_Log ─────────────────────────────────────────────────
    log_ws = _get_worksheet(get_settings().ATTENDANCE_LOG_SHEET_ID, "Attendance_Log")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for reg_no, status in attendance.items():
        rows.append(sanitize_sheet_row([
            "",
            date_str,
            class_id,
            hour,
            subject_id,
            reg_no,
            status,
            faculty_id,
            now_str,
        ]))
    if rows:
        log_ws.append_rows(rows, value_input_option="USER_ENTERED")
    
    invalidate_cache("attendance_log_raw")


# ─────────────────────────────────────────────────────────────────────────────
# STUDENT ATTENDANCE SUMMARY
# ─────────────────────────────────────────────────────────────────────────────
def get_student_attendance_summary(reg_no: str) -> Dict:
    records = _get_raw_attendance_log()
    rn = reg_no.strip()
    student_rows = [r for r in records if str(r.get("RegNo", "")).strip() == rn]

    total = len([r for r in student_rows if r.get("Status", "") != "-"])
    attended = len([r for r in student_rows if r.get("Status", "") == "P"])

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

    sub_records = _get_raw_subjects()
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
        "datewise": datewise[-60:],
    }


# ─────────────────────────────────────────────────────────────────────────────
# PAST ATTENDANCE IMPORT
# ─────────────────────────────────────────────────────────────────────────────
def import_past_attendance_rows(rows: List[Dict]) -> int:
    log_ws = _get_worksheet(get_settings().ATTENDANCE_LOG_SHEET_ID, "Attendance_Log")
    existing = _get_raw_attendance_log()
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
        invalidate_cache("attendance_log_raw")

    return len(new_rows)


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN – Reports
# ─────────────────────────────────────────────────────────────────────────────
def get_class_attendance_report(class_id: str) -> List[Dict]:
    students = get_students_by_class(class_id)
    records = _get_raw_attendance_log()
    cid = class_id.strip()
    class_rows = [r for r in records if str(r.get("ClassID", "")).strip() == cid]

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


# ─────────────────────────────────────────────────────────────────────────────
# ADMIN – Comprehensive Dashboard Analytics
# ─────────────────────────────────────────────────────────────────────────────
def get_admin_analytics() -> Dict[str, Any]:
    active_classes = get_all_classes()
    class_map = {str(c["ClassID"]).strip(): str(c.get("ClassName", c["ClassID"])).strip() for c in active_classes}
    active_students = [s for s in _get_raw_students() if s.get("Status", "").upper() == "ACTIVE"]
    student_map = {str(s["RegNo"]).strip(): s for s in active_students}
    active_subjects = [s for s in _get_raw_subjects() if s.get("Status", "").upper() == "ACTIVE"]
    faculty_users = [u for u in get_all_users() if str(u.get("Role", "")).upper() == "FACULTY"]
    
    logs = _get_raw_attendance_log()
    today_str = date.today().strftime("%d-%m-%Y")
    
    total_records = len(logs)
    valid_logs = [r for r in logs if r.get("Status", "") in ("P", "A")]
    total_hours = len(valid_logs)
    attended_hours = len([r for r in valid_logs if r.get("Status", "") == "P"])
    overall_percentage = round((attended_hours / total_hours) * 100, 1) if total_hours else 0.0

    today_logs = [r for r in logs if str(r.get("Date", "")).strip() == today_str and r.get("Status", "") in ("P", "A")]
    today_total = len(today_logs)
    today_attended = len([r for r in today_logs if r.get("Status", "") == "P"])
    today_absent = today_total - today_attended
    today_percentage = round((today_attended / today_total) * 100, 1) if today_total else 0.0

    status_distribution = {
        "present": attended_hours,
        "absent": total_hours - attended_hours,
        "on_duty": len([r for r in logs if r.get("Status", "") == "-"]),
    }

    class_info_map = {str(c["ClassID"]).strip(): c for c in active_classes}
    subject_map = {str(s.get("SubjectID", "")).strip(): s.get("SubjectName", s.get("SubjectID", "")) for s in active_subjects}

    # Pre-calculate defaulters per student
    student_att_map = {}
    for r in valid_logs:
        rn = str(r.get("RegNo", "")).strip()
        if not rn:
            continue
        if rn not in student_att_map:
            student_att_map[rn] = {"total": 0, "attended": 0}
        student_att_map[rn]["total"] += 1
        if r.get("Status", "") == "P":
            student_att_map[rn]["attended"] += 1

    defaulters = []
    class_defaulter_count = {cid: 0 for cid in class_map.keys()}
    for rn, s in student_map.items():
        st = student_att_map.get(rn, {"total": 0, "attended": 0})
        pct = round((st["attended"] / st["total"]) * 100, 1) if st["total"] else 0.0
        cid = str(s.get("ClassID", "")).strip()
        if st["total"] > 0 and pct < 75.0:
            if cid in class_defaulter_count:
                class_defaulter_count[cid] += 1
            defaulters.append({
                "reg_no": rn,
                "name": s.get("Name", rn),
                "class_id": cid,
                "class_name": class_map.get(cid, cid),
                "total": st["total"],
                "attended": st["attended"],
                "absent": st["total"] - st["attended"],
                "percentage": pct,
            })
    defaulters.sort(key=lambda x: x["percentage"])

    # Class & Section wise aggregation
    class_stat_map = {
        cid: {
            "total": 0, "attended": 0, "absent": 0, "on_duty": 0,
            "today_total": 0, "today_attended": 0,
            "subjects": {}
        }
        for cid in class_map.keys()
    }

    for r in logs:
        cid = str(r.get("ClassID", "")).strip()
        if cid not in class_stat_map:
            continue
        st_code = str(r.get("Status", "")).strip().upper()
        d_str = str(r.get("Date", "")).strip()
        sub_id = str(r.get("SubjectID", "")).strip()

        if st_code in ("P", "A"):
            class_stat_map[cid]["total"] += 1
            if st_code == "P":
                class_stat_map[cid]["attended"] += 1
            else:
                class_stat_map[cid]["absent"] += 1

            if d_str == today_str:
                class_stat_map[cid]["today_total"] += 1
                if st_code == "P":
                    class_stat_map[cid]["today_attended"] += 1

            if sub_id:
                if sub_id not in class_stat_map[cid]["subjects"]:
                    class_stat_map[cid]["subjects"][sub_id] = {"total": 0, "attended": 0}
                class_stat_map[cid]["subjects"][sub_id]["total"] += 1
                if st_code == "P":
                    class_stat_map[cid]["subjects"][sub_id]["attended"] += 1
        elif st_code == "-":
            class_stat_map[cid]["on_duty"] += 1

    class_stats = []
    for cid, c_info in class_info_map.items():
        st = class_stat_map.get(cid, {"total": 0, "attended": 0, "absent": 0, "on_duty": 0, "today_total": 0, "today_attended": 0, "subjects": {}})
        pct = round((st["attended"] / st["total"]) * 100, 1) if st["total"] else 0.0
        today_pct = round((st["today_attended"] / st["today_total"]) * 100, 1) if st["today_total"] else 0.0
        students_count = len([s for s in active_students if str(s.get("ClassID", "")).strip() == cid])

        # Subject breakdown for this class/section
        sub_list = []
        for s_id, s_data in st["subjects"].items():
            s_pct = round((s_data["attended"] / s_data["total"]) * 100, 1) if s_data["total"] else 0.0
            sub_list.append({
                "subject_id": s_id,
                "subject_name": subject_map.get(s_id, s_id),
                "total": s_data["total"],
                "attended": s_data["attended"],
                "percentage": s_pct,
            })
        sub_list.sort(key=lambda x: x["percentage"], reverse=True)

        class_stats.append({
            "class_id": cid,
            "class_name": c_info.get("ClassName", cid),
            "year": str(c_info.get("Year", "")).strip(),
            "section": str(c_info.get("Section", "")).strip().upper(),
            "semester": str(c_info.get("Semester", "")).strip(),
            "student_count": students_count,
            "total": st["total"],
            "attended": st["attended"],
            "absent": st["absent"],
            "on_duty": st["on_duty"],
            "percentage": pct,
            "today_total": st["today_total"],
            "today_attended": st["today_attended"],
            "today_percentage": today_pct,
            "defaulters_count": class_defaulter_count.get(cid, 0),
            "subject_breakdown": sub_list,
        })
    class_stats.sort(key=lambda x: x["percentage"], reverse=True)

    # Section-wise & Year-wise grouped performance summary
    sec_grouped = {}
    year_grouped = {}
    for cs in class_stats:
        sec = cs["section"] or "N/A"
        yr = cs["year"] or "N/A"

        if sec not in sec_grouped:
            sec_grouped[sec] = {"section": sec, "total": 0, "attended": 0, "student_count": 0, "defaulters_count": 0}
        sec_grouped[sec]["total"] += cs["total"]
        sec_grouped[sec]["attended"] += cs["attended"]
        sec_grouped[sec]["student_count"] += cs["student_count"]
        sec_grouped[sec]["defaulters_count"] += cs["defaulters_count"]

        if yr not in year_grouped:
            year_grouped[yr] = {"year": yr, "total": 0, "attended": 0, "student_count": 0, "defaulters_count": 0}
        year_grouped[yr]["total"] += cs["total"]
        year_grouped[yr]["attended"] += cs["attended"]
        year_grouped[yr]["student_count"] += cs["student_count"]
        year_grouped[yr]["defaulters_count"] += cs["defaulters_count"]

    section_summaries = []
    for sec, val in sec_grouped.items():
        pct = round((val["attended"] / val["total"]) * 100, 1) if val["total"] else 0.0
        section_summaries.append({**val, "percentage": pct})
    section_summaries.sort(key=lambda x: x["section"])

    year_summaries = []
    for yr, val in year_grouped.items():
        pct = round((val["attended"] / val["total"]) * 100, 1) if val["total"] else 0.0
        year_summaries.append({**val, "percentage": pct})
    year_summaries.sort(key=lambda x: x["year"])

    hour_stats = []
    for h in ALL_HOURS:
        h_logs = [r for r in valid_logs if str(r.get("Hour", "")).strip().upper() == h]
        h_tot = len(h_logs)
        h_att = len([r for r in h_logs if r.get("Status", "") == "P"])
        h_pct = round((h_att / h_tot) * 100, 1) if h_tot else 0.0
        hour_stats.append({
            "hour": h,
            "label": HOUR_LABELS.get(h, h),
            "total": h_tot,
            "attended": h_att,
            "percentage": h_pct,
        })

    date_map = {}
    for r in valid_logs:
        d = str(r.get("Date", "")).strip()
        if not d:
            continue
        if d not in date_map:
            date_map[d] = {"total": 0, "attended": 0}
        date_map[d]["total"] += 1
        if r.get("Status", "") == "P":
            date_map[d]["attended"] += 1

    def _parse_sort_key(d_str):
        for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(d_str, fmt)
            except ValueError:
                pass
        return datetime.min

    sorted_dates = sorted(date_map.keys(), key=_parse_sort_key)
    trend = []
    for d in sorted_dates[-14:]:
        t_data = date_map[d]
        pct = round((t_data["attended"] / t_data["total"]) * 100, 1) if t_data["total"] else 0.0
        trend.append({
            "date": d,
            "total": t_data["total"],
            "attended": t_data["attended"],
            "percentage": pct,
        })

    session_groups = {}
    for r in reversed(logs):
        key = (
            str(r.get("Date", "")).strip(),
            str(r.get("ClassID", "")).strip(),
            str(r.get("Hour", "")).strip().upper(),
            str(r.get("SubjectID", "")).strip(),
            str(r.get("FacultyID", "")).strip(),
        )
        if key not in session_groups:
            session_groups[key] = {
                "date": key[0],
                "class_id": key[1],
                "class_name": class_map.get(key[1], key[1]),
                "hour": key[2],
                "subject_id": key[3],
                "faculty_id": key[4],
                "present": 0,
                "absent": 0,
                "timestamp": str(r.get("Timestamp", "")),
            }
        if r.get("Status", "") == "P":
            session_groups[key]["present"] += 1
        elif r.get("Status", "") == "A":
            session_groups[key]["absent"] += 1
        if len(session_groups) >= 8:
            break

    recent_activity = list(session_groups.values())

    return {
        "total_students": len(active_students),
        "total_classes": len(active_classes),
        "total_faculty": len(faculty_users),
        "total_subjects": len(active_subjects),
        "total_records": total_records,
        "overall_percentage": overall_percentage,
        "total_hours": total_hours,
        "attended_hours": attended_hours,
        "today": {
            "date": today_str,
            "total": today_total,
            "attended": today_attended,
            "absent": today_absent,
            "percentage": today_percentage,
        },
        "status_distribution": status_distribution,
        "class_stats": class_stats,
        "section_summaries": section_summaries,
        "year_summaries": year_summaries,
        "hour_stats": hour_stats,
        "trend": trend,
        "defaulters": defaulters,
        "defaulters_count": len(defaulters),
        "recent_activity": recent_activity,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Background Cache Pre-warming
# ─────────────────────────────────────────────────────────────────────────────
def warm_up_cache():
    """Fetch essential sheets in background so the first user request is instant."""
    try:
        get_all_users()
        get_all_classes()
        _get_raw_subjects()
        _get_raw_students()
        _get_raw_attendance_log()
        print("[Cache] AttendTrax sheets cache successfully pre-warmed!")
    except Exception as e:
        print(f"[Cache] Background cache warming warning: {e}")
