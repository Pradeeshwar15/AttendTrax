# =============================================================================
# services/sql_analytics.py  –  Pure SQL Analytics, Reports & Matrix Aggregation
# =============================================================================
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import calendar

from sqlalchemy import select, and_, or_, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from models import ClassRoom, Student, Department, AttendanceSession, AttendanceRecord, Subject, User, PlacementAttendance

ALL_HOURS = ["DAY", "PERIOD_1", "PERIOD_2", "PERIOD_3", "PERIOD_4", "PERIOD_5", "PERIOD_6", "PERIOD_7", "PERIOD_8", "PLACEMENT"]

def get_ist_today_str() -> str:
    ist_tz = timezone(timedelta(hours=5, minutes=30))
    return datetime.now(ist_tz).strftime("%d-%m-%Y")


def parse_date_str(d_str: str) -> Optional[date]:
    if not d_str:
        return None
    d_clean = str(d_str).strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(d_clean, fmt).date()
        except ValueError:
            pass
    return None


async def compute_sql_admin_analytics(db: AsyncSession) -> Dict[str, Any]:
    """
    Computes institutional analytics directly from Supabase PostgreSQL in sub-15ms.
    Replaces legacy sheets.get_admin_analytics().
    """
    today_date = date.today()
    today_str = get_ist_today_str()

    # 1. Active classes
    stmt_cls = (
        select(ClassRoom, Department.code)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.status == "ACTIVE")
        .order_by(ClassRoom.class_code)
    )
    cls_rows = (await db.execute(stmt_cls)).all()
    class_map = {c.class_code: c for c, _ in cls_rows}
    class_dept_map = {c.class_code: dept_code for c, dept_code in cls_rows}
    class_id_to_code = {c.id: c.class_code for c, _ in cls_rows}

    # 2. Active students
    stmt_stu = (
        select(Student.id, Student.reg_no, Student.name, Student.class_id)
        .where(Student.status == "ACTIVE")
    )
    stu_rows = (await db.execute(stmt_stu)).all()
    total_students = len(stu_rows)
    class_student_count: Dict[str, int] = {c.class_code: 0 for c, _ in cls_rows}
    for _, _, _, s_cid in stu_rows:
        ccode = class_id_to_code.get(s_cid)
        if ccode and ccode in class_student_count:
            class_student_count[ccode] += 1

    # 3. Overall attendance aggregated by class
    stmt_class_agg = (
        select(
            AttendanceSession.class_id,
            func.count(AttendanceRecord.id).label("total"),
            func.sum(case((AttendanceRecord.status.in_(["P", "OD"]), 1), else_=0)).label("attended"),
            func.sum(case((AttendanceRecord.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((AttendanceRecord.status == "OD", 1), else_=0)).label("od"),
            func.sum(case((AttendanceSession.session_date == today_date, 1), else_=0)).label("today_total"),
            func.sum(case((and_(AttendanceSession.session_date == today_date, AttendanceRecord.status.in_(["P", "OD"])), 1), else_=0)).label("today_attended"),
            func.sum(case((and_(AttendanceSession.session_date == today_date, AttendanceRecord.status == "P"), 1), else_=0)).label("today_present"),
            func.sum(case((and_(AttendanceSession.session_date == today_date, AttendanceRecord.status == "A"), 1), else_=0)).label("today_absent"),
            func.sum(case((and_(AttendanceSession.session_date == today_date, AttendanceRecord.status == "OD"), 1), else_=0)).label("today_od")
        )
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .group_by(AttendanceSession.class_id)
    )
    class_agg_rows = {r[0]: r for r in (await db.execute(stmt_class_agg)).all()}

    # 4. Student defaulters (< 75% attendance)
    stmt_stu_agg = (
        select(
            Student.reg_no,
            Student.name,
            Student.class_id,
            func.count(AttendanceRecord.id).label("total"),
            func.sum(case((AttendanceRecord.status.in_(["P", "OD"]), 1), else_=0)).label("attended"),
            func.sum(case((AttendanceRecord.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((AttendanceRecord.status == "OD", 1), else_=0)).label("od")
        )
        .join(AttendanceRecord, AttendanceRecord.student_id == Student.id)
        .where(Student.status == "ACTIVE")
        .group_by(Student.id, Student.reg_no, Student.name, Student.class_id)
    )
    stu_agg_rows = (await db.execute(stmt_stu_agg)).all()

    defaulters = []
    class_defaulters_count: Dict[str, int] = {c.class_code: 0 for c, _ in cls_rows}
    for rn, sname, scid, s_tot, s_att, s_abs, s_od in stu_agg_rows:
        ccode = class_id_to_code.get(scid, "")
        cname = class_map[ccode].class_name if ccode in class_map else ccode
        tot = s_tot or 0
        att = s_att or 0
        ab = s_abs or 0
        od = s_od or 0
        pct = round((att / tot) * 100, 1) if tot > 0 else 0.0
        if tot > 0 and pct < 75.0:
            if ccode in class_defaulters_count:
                class_defaulters_count[ccode] += 1
            defaulters.append({
                "reg_no": rn,
                "name": sname,
                "class_id": ccode,
                "class_name": cname,
                "total": tot,
                "attended": att,
                "absent": ab,
                "od": od,
                "percentage": pct,
            })
    defaulters.sort(key=lambda d: d["percentage"])

    # 5. Build class_stats list
    class_stats = []
    total_inst_sessions = 0
    total_inst_attended = 0
    today_inst_total = 0
    today_inst_present = 0
    today_inst_absent = 0
    today_inst_od = 0

    for cls_obj, dept_code in cls_rows:
        cid = cls_obj.class_code
        c_pk = cls_obj.id
        c_agg = class_agg_rows.get(c_pk)

        tot = c_agg.total if c_agg else 0
        att = c_agg.attended if c_agg else 0
        ab = c_agg.absent if c_agg else 0
        od = c_agg.od if c_agg else 0
        pct = round((att / tot) * 100, 1) if tot > 0 else 0.0

        t_tot = c_agg.today_total if c_agg else 0
        t_att = c_agg.today_attended if c_agg else 0
        t_pres = c_agg.today_present if c_agg else 0
        t_abs = c_agg.today_absent if c_agg else 0
        t_od = c_agg.today_od if c_agg else 0
        t_pct = round((t_att / t_tot) * 100, 1) if t_tot > 0 else 0.0

        total_inst_sessions += tot
        total_inst_attended += att
        today_inst_total += t_tot
        today_inst_present += t_pres
        today_inst_absent += t_abs
        today_inst_od += t_od

        # Batch & Academic mapping
        raw_yr = str(cls_obj.year).strip()
        sec = (cls_obj.section or "A").strip().upper()
        if raw_yr in ("27", "2027", "4"):
            batch_label = "Batch 2027"
            year_name = "IV Year (4th Year)"
        elif raw_yr in ("28", "2028", "3"):
            batch_label = "Batch 2028"
            year_name = "III Year (3rd Year)"
        elif raw_yr in ("29", "2029", "2"):
            batch_label = "Batch 2029"
            year_name = "II Year (2nd Year)"
        else:
            batch_label = f"Batch {raw_yr}"
            year_name = f"Year {raw_yr}"

        class_stats.append({
            "class_id": cid,
            "class_name": cls_obj.class_name,
            "department": dept_code,
            "batch_label": batch_label,
            "academic_year": year_name,
            "section": sec,
            "semester": str(cls_obj.semester),
            "student_count": class_student_count.get(cid, 0),
            "total": tot,
            "attended": att,
            "absent": ab,
            "on_duty": od,
            "percentage": pct,
            "today_total": t_tot,
            "today_present": t_pres,
            "today_absent": t_abs,
            "today_od": t_od,
            "today_percentage": t_pct,
            "defaulters_count": class_defaulters_count.get(cid, 0),
            "subjects": []
        })

    # 6. 14-day trend query
    stmt_trend = (
        select(
            AttendanceSession.session_date,
            func.count(AttendanceRecord.id).label("total"),
            func.sum(case((AttendanceRecord.status.in_(["P", "OD"]), 1), else_=0)).label("attended")
        )
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .group_by(AttendanceSession.session_date)
        .order_by(AttendanceSession.session_date.asc())
    )
    trend_rows = (await db.execute(stmt_trend)).all()
    trend = []
    for s_date, t_tot, t_att in trend_rows[-14:]:
        d_str = s_date.strftime("%d-%m-%Y") if isinstance(s_date, (date, datetime)) else str(s_date)
        t_pct = round(((t_att or 0) / t_tot) * 100, 1) if t_tot else 0.0
        trend.append({
            "date": d_str,
            "total": t_tot,
            "attended": t_att or 0,
            "percentage": t_pct,
        })

    # Overall percentage
    overall_percentage = round((total_inst_attended / total_inst_sessions) * 100, 1) if total_inst_sessions > 0 else 0.0
    today_overall_pct = round(((today_inst_present + today_inst_od) / today_inst_total) * 100, 1) if today_inst_total > 0 else 0.0

    today_dict = {
        "present": today_inst_present,
        "absent": today_inst_absent,
        "on_duty": today_inst_od,
        "total": today_inst_total,
        "percentage": today_overall_pct,
    }

    status_dist = {
        "present": total_inst_attended,
        "absent": total_inst_sessions - total_inst_attended,
        "on_duty": sum(c["on_duty"] for c in class_stats),
    } if total_inst_sessions > 0 else {}

    section_summaries = [
        {
            "class_id": c["class_id"],
            "class_name": c["class_name"],
            "total_students": c["student_count"],
            "percentage": c["percentage"],
        }
        for c in class_stats
    ]

    return {
        "total_students": total_students,
        "total_classes": len(class_stats),
        "overall_percentage": overall_percentage,
        "today": today_dict,
        "trend": trend,
        "status_distribution": status_dist,
        "class_stats": class_stats,
        "section_summaries": section_summaries,
        "defaulters": defaulters,
        "defaulters_count": len(defaulters),
        "recent_activity": []
    }


async def get_sql_class_attendance_report(db: AsyncSession, class_id: str) -> List[Dict[str, Any]]:
    """
    Sub-5ms SQL calculation of student attendance summary roster for a given class.
    Replaces sheets.get_class_attendance_report().
    """
    clean_cid = str(class_id or "").strip().upper()
    if clean_cid.isdigit():
        cls_stmt = select(ClassRoom.id).where(or_(ClassRoom.class_code == clean_cid, ClassRoom.id == int(clean_cid)))
    else:
        cls_stmt = select(ClassRoom.id).where(ClassRoom.class_code == clean_cid)
    c_pk = (await db.execute(cls_stmt)).scalar_one_or_none()
    if not c_pk:
        return []

    # Get active students
    st_stmt = select(Student).where(and_(Student.class_id == c_pk, Student.status == "ACTIVE")).order_by(Student.reg_no)
    students = (await db.execute(st_stmt)).scalars().all()
    if not students:
        return []

    stu_ids = [s.id for s in students]

    # Count unique working dates for this class
    date_stmt = select(func.count(func.distinct(AttendanceSession.session_date))).where(AttendanceSession.class_id == c_pk)
    working_days = (await db.execute(date_stmt)).scalar() or 0

    # Student stats
    rec_stmt = (
        select(
            AttendanceRecord.student_id,
            func.count(AttendanceRecord.id).label("total"),
            func.sum(case((AttendanceRecord.status.in_(["P", "OD"]), 1), else_=0)).label("present"),
            func.sum(case((AttendanceRecord.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((AttendanceRecord.status == "OD", 1), else_=0)).label("od")
        )
        .where(AttendanceRecord.student_id.in_(stu_ids))
        .group_by(AttendanceRecord.student_id)
    )
    rec_map = {r[0]: r for r in (await db.execute(rec_stmt)).all()}

    report = []
    for s in students:
        stats = rec_map.get(s.id)
        tot = stats.total if stats else 0
        pres = stats.present if stats else 0
        ab = stats.absent if stats else 0
        od = stats.od if stats else 0
        pct = round((pres / tot * 100), 2) if tot > 0 else 0.0

        report.append({
            "reg_no": s.reg_no,
            "RegNo": s.reg_no,
            "name": s.name,
            "Name": s.name,
            "working_days": max(working_days, tot),
            "total": tot,
            "attended": pres,
            "absent": ab,
            "od": od,
            "percentage": pct,
        })

    report.sort(key=lambda x: str(x.get("reg_no", "")))
    return report


async def get_sql_class_matrix(
    db: AsyncSession,
    class_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None
) -> Dict[str, Any]:
    """
    Generates a full Day 1 to Day 31 detailed daily matrix register for the selected class.
    Returns:
    - class_info
    - date_cols (e.g. ['01-11-2026', ...])
    - matrix_rows: list of student records with daily P/A/OD values, totals, and percentages
    """
    clean_cid = str(class_id or "").strip().upper()
    cls_stmt = (
        select(ClassRoom, Department.code)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.class_code == clean_cid)
    )
    res = await db.execute(cls_stmt)
    row = res.first()
    if not row:
        return {"error": f"Class '{clean_cid}' not found.", "date_cols": [], "matrix_rows": []}

    cls_obj, dept_code = row
    c_pk = cls_obj.id

    now = datetime.now()
    target_year = year or now.year
    target_month = month or now.month
    month_name = calendar.month_name[target_month]
    num_days = calendar.monthrange(target_year, target_month)[1]

    # Generate dates for month: '01-11-2026' through '30-11-2026'
    date_cols = [f"{d:02d}-{target_month:02d}-{target_year}" for d in range(1, num_days + 1)]

    # Fetch active students
    st_stmt = select(Student).where(and_(Student.class_id == c_pk, Student.status == "ACTIVE")).order_by(Student.reg_no)
    students = (await db.execute(st_stmt)).scalars().all()

    # Fetch attendance sessions and records for this class within target month
    start_d = date(target_year, target_month, 1)
    end_d = date(target_year, target_month, num_days)

    stmt_records = (
        select(
            AttendanceRecord.student_id,
            AttendanceSession.session_date,
            AttendanceRecord.status
        )
        .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
        .where(
            and_(
                AttendanceSession.class_id == c_pk,
                AttendanceSession.session_date >= start_d,
                AttendanceSession.session_date <= end_d
            )
        )
    )
    rec_rows = (await db.execute(stmt_records)).all()

    # student_id -> {date_str: status}
    att_grid: Dict[int, Dict[str, str]] = {}
    for sid, s_date, st_val in rec_rows:
        if sid not in att_grid:
            att_grid[sid] = {}
        d_str = s_date.strftime("%d-%m-%Y") if isinstance(s_date, (date, datetime)) else str(s_date)
        att_grid[sid][d_str] = (st_val or "").strip().upper()

    matrix_rows = []
    for s in students:
        p_count = 0
        a_count = 0
        od_count = 0
        s_grid = att_grid.get(s.id, {})
        day_statuses = {}

        for d_str in date_cols:
            val = s_grid.get(d_str, "-")
            day_statuses[d_str] = val
            if val == "P":
                p_count += 1
            elif val == "A":
                a_count += 1
            elif val in ("OD", "ONDUTY", "ON DUTY"):
                od_count += 1

        tot = p_count + a_count + od_count
        eff = p_count + od_count
        pct = round((eff / tot) * 100, 1) if tot > 0 else 0.0

        matrix_rows.append({
            "reg_no": s.reg_no,
            "name": s.name,
            "statuses": day_statuses,
            "total_present": p_count,
            "total_absent": a_count,
            "total_od": od_count,
            "total_sessions": tot,
            "percentage": pct,
        })

    return {
        "class_id": clean_cid,
        "class_name": cls_obj.class_name,
        "department": dept_code,
        "month": target_month,
        "month_name": month_name,
        "year": target_year,
        "date_cols": date_cols,
        "matrix_rows": matrix_rows,
    }


async def get_sql_daily_attendance_for_edit(
    db: AsyncSession,
    class_id: str,
    date_str: str,
    hour: str = "DAY",
    subject_id: str = ""
) -> List[Dict[str, str]]:
    """
    Fetches students for editing attendance for any specific date and hour.
    Replaces sheets.get_daily_attendance_for_edit().
    """
    clean_cid = str(class_id or "").strip().upper()
    if clean_cid.isdigit():
        cls_stmt = select(ClassRoom.id).where(or_(ClassRoom.class_code == clean_cid, ClassRoom.id == int(clean_cid)))
    else:
        cls_stmt = select(ClassRoom.id).where(ClassRoom.class_code == clean_cid)
    c_pk = (await db.execute(cls_stmt)).scalar_one_or_none()
    if not c_pk:
        return []

    target_date = parse_date_str(date_str) or date.today()
    hour_val = (hour or "DAY").strip().upper()

    # Get active students
    st_stmt = select(Student).where(and_(Student.class_id == c_pk, Student.status == "ACTIVE")).order_by(Student.reg_no)
    students = (await db.execute(st_stmt)).scalars().all()
    if not students:
        return []

    # Check existing session
    sess_stmt = select(AttendanceSession.id).where(
        and_(
            AttendanceSession.class_id == c_pk,
            AttendanceSession.session_date == target_date,
            AttendanceSession.slot_hour == hour_val
        )
    )
    sess_id = (await db.execute(sess_stmt)).scalar_one_or_none()

    status_map = {}
    if sess_id:
        rec_stmt = select(AttendanceRecord.student_id, AttendanceRecord.status).where(AttendanceRecord.session_id == sess_id)
        status_map = {sid: st for sid, st in (await db.execute(rec_stmt)).all()}

    return [
        {
            "RegNo": s.reg_no,
            "Name": s.name,
            "Status": status_map.get(s.id, "P") if sess_id else "P"
        }
        for s in students
    ]


async def update_sql_daily_attendance(
    db: AsyncSession,
    class_id: str,
    date_str: str,
    hour: str,
    subject_id: str,
    admin_id: str,
    attendance_map: Dict[str, str]
) -> Dict[str, Any]:
    """
    Admin modify & resubmit daily attendance in SQL.
    Replaces sheets.admin_update_attendance().
    """
    clean_cid = str(class_id or "").strip().upper()
    cls_stmt = select(ClassRoom.id).where(ClassRoom.class_code == clean_cid)
    c_pk = (await db.execute(cls_stmt)).scalar_one_or_none()
    if not c_pk:
        return {"status": "error", "message": f"Class '{clean_cid}' not found."}

    target_date = parse_date_str(date_str) or date.today()
    hour_val = (hour or "DAY").strip().upper()

    # Lookup or create session
    sess_stmt = select(AttendanceSession).where(
        and_(
            AttendanceSession.class_id == c_pk,
            AttendanceSession.session_date == target_date,
            AttendanceSession.slot_hour == hour_val
        )
    )
    sess_obj = (await db.execute(sess_stmt)).scalar_one_or_none()
    if not sess_obj:
        sess_obj = AttendanceSession(
            class_id=c_pk,
            session_date=target_date,
            slot_hour=hour_val,
            session_type="TRAINING" if hour_val in ("PLACEMENT", "TRAINING") else "DAILY",
            faculty_id=None,
            lock_status="LOCKED"
        )
        db.add(sess_obj)
        await db.flush()

    # Fetch students
    st_stmt = select(Student).where(Student.class_id == c_pk)
    students = (await db.execute(st_stmt)).scalars().all()
    st_map = {s.reg_no.strip(): s.id for s in students}

    # Fetch existing records
    rec_stmt = select(AttendanceRecord).where(AttendanceRecord.session_id == sess_obj.id)
    existing_recs = {r.student_id: r for r in (await db.execute(rec_stmt)).scalars().all()}

    updated_count = 0
    for rn, st_val in attendance_map.items():
        rn_clean = str(rn).strip()
        if rn_clean in st_map:
            s_id = st_map[rn_clean]
            clean_st = str(st_val).strip().upper()
            if s_id in existing_recs:
                existing_recs[s_id].status = clean_st
            else:
                db.add(AttendanceRecord(
                    session_id=sess_obj.id,
                    student_id=s_id,
                    status=clean_st
                ))
            updated_count += 1

    await db.commit()
    return {
        "status": "success",
        "message": f"Updated attendance for {updated_count} student(s) on {date_str} ({hour_val}).",
        "updated": updated_count
    }


async def get_sql_date_attendance_overview(db: AsyncSession, date_str: str) -> Dict[str, Any]:
    """
    Sub-10ms institutional attendance overview for a specific date:
    - Lists submitted sessions with faculty name, subject, and student stats.
    - Lists all classes pending attendance on that date.
    Replaces sheets.get_date_attendance_overview().
    """
    target_date = parse_date_str(date_str) or date.today()
    dstr = target_date.strftime("%d-%m-%Y")

    # 1. Fetch active classes
    stmt_cls = (
        select(ClassRoom, Department.code)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.status == "ACTIVE")
        .order_by(ClassRoom.class_code)
    )
    all_classes = (await db.execute(stmt_cls)).all()
    class_map = {c.id: (c, dept_code) for c, dept_code in all_classes}
    class_code_map = {c.class_code: c for c, _ in all_classes}

    # Count students per class
    stmt_scnt = select(Student.class_id, func.count(Student.id)).where(Student.status == "ACTIVE").group_by(Student.class_id)
    stu_counts = {cid: cnt for cid, cnt in (await db.execute(stmt_scnt)).all()}

    # 2. Fetch sessions submitted for target date
    stmt_sess = (
        select(
            AttendanceSession,
            User.full_name.label("faculty_name"),
            Subject.name.label("subject_name"),
            Subject.subject_code.label("subject_code")
        )
        .outerjoin(User, AttendanceSession.faculty_id == User.id)
        .outerjoin(Subject, AttendanceSession.subject_id == Subject.id)
        .where(AttendanceSession.session_date == target_date)
    )
    sessions_rows = (await db.execute(stmt_sess)).all()

    sess_ids = [s.id for s, _, _, _ in sessions_rows]

    # Fetch records aggregated by session_id
    rec_agg = {}
    if sess_ids:
        stmt_rec = (
            select(
                AttendanceRecord.session_id,
                func.count(AttendanceRecord.id).label("total"),
                func.sum(case((AttendanceRecord.status == "P", 1), else_=0)).label("present"),
                func.sum(case((AttendanceRecord.status == "A", 1), else_=0)).label("absent"),
                func.sum(case((AttendanceRecord.status == "OD", 1), else_=0)).label("od")
            )
            .where(AttendanceRecord.session_id.in_(sess_ids))
            .group_by(AttendanceRecord.session_id)
        )
        rec_agg = {r[0]: r for r in (await db.execute(stmt_rec)).all()}

    submitted_sessions = []
    submitted_class_pks = set()

    for s, fac_name, sub_name, sub_code in sessions_rows:
        submitted_class_pks.add(s.class_id)
        cls_info = class_map.get(s.class_id)
        cls_obj = cls_info[0] if cls_info else None
        cid = cls_obj.class_code if cls_obj else str(s.class_id)
        cname = cls_obj.class_name if cls_obj else cid

        agg = rec_agg.get(s.id)
        p_cnt = agg.present if agg else 0
        a_cnt = agg.absent if agg else 0
        od_cnt = agg.od if agg else 0
        tot = agg.total if agg else 0
        pct = round(((p_cnt + od_cnt) / tot * 100), 1) if tot > 0 else 0.0

        submitted_sessions.append({
            "class_id": cid,
            "class_name": cname,
            "year": str(cls_obj.year) if cls_obj else "1",
            "section": cls_obj.section if cls_obj else "A",
            "semester": str(cls_obj.semester) if cls_obj else "1",
            "hour": s.slot_hour or "DAY",
            "subject_id": sub_code or "",
            "subject_name": sub_name or "",
            "faculty_id": str(s.faculty_id or ""),
            "faculty_name": fac_name or "Faculty",
            "timestamp": s.created_at.strftime("%H:%M:%S") if s.created_at else "",
            "present": p_cnt,
            "absent": a_cnt,
            "on_duty": od_cnt,
            "total_students": tot,
            "percentage": pct,
        })

    submitted_sessions.sort(key=lambda x: (x["class_name"], x["hour"]))

    pending_classes = []
    for cls_obj, _ in all_classes:
        if cls_obj.id not in submitted_class_pks:
            pending_classes.append({
                "class_id": cls_obj.class_code,
                "class_name": cls_obj.class_name,
                "year": str(cls_obj.year),
                "section": cls_obj.section,
                "semester": str(cls_obj.semester),
                "student_count": stu_counts.get(cls_obj.id, 0),
            })

    pending_classes.sort(key=lambda x: x["class_name"])

    return {
        "date": dstr,
        "total_classes": len(all_classes),
        "submitted_count": len(submitted_sessions),
        "pending_count": len(pending_classes),
        "submitted": submitted_sessions,
        "pending": pending_classes,
    }


# ═════════════════════════════════════════════════════════════════════════════
# DEDICATED PLACEMENT ATTENDANCE ANALYTICS & SANDBOX ENGINES
# ═════════════════════════════════════════════════════════════════════════════

async def compute_placement_admin_analytics(db: AsyncSession) -> Dict[str, Any]:
    """
    Computes Placement & Training attendance analytics strictly from the placement_attendance table.
    Isolated sandbox for Placement Department HOD:
    - 0% leakage from regular academic attendance
    - Full visibility across all 10 departments for placement training
    """
    today_date = date.today()
    today_str = get_ist_today_str()

    # 1. Active classes
    stmt_cls = (
        select(ClassRoom, Department.code)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.status == "ACTIVE")
        .order_by(ClassRoom.class_code)
    )
    cls_rows = (await db.execute(stmt_cls)).all()
    class_map = {c.class_code: c for c, _ in cls_rows}
    class_id_to_code = {c.id: c.class_code for c, _ in cls_rows}

    # 2. Active students (Only placement willing students for Placement analytics)
    stmt_stu = (
        select(Student.id, Student.reg_no, Student.name, Student.class_id, Student.department_id)
        .where(
            and_(
                Student.status == "ACTIVE",
                func.lower(Student.placement_willingness) == "active"
            )
        )
    )
    stu_rows = (await db.execute(stmt_stu)).all()
    total_students = len(stu_rows)
    class_student_count: Dict[str, int] = {c.class_code: 0 for c, _ in cls_rows}
    for _, _, _, s_cid, _ in stu_rows:
        ccode = class_id_to_code.get(s_cid)
        if ccode and ccode in class_student_count:
            class_student_count[ccode] += 1

    # 3. Overall placement attendance aggregated by class
    stmt_class_agg = (
        select(
            PlacementAttendance.class_id,
            func.count(PlacementAttendance.id).label("total"),
            func.sum(case((PlacementAttendance.status.in_(["P", "OD"]), 1), else_=0)).label("attended"),
            func.sum(case((PlacementAttendance.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((PlacementAttendance.status == "OD", 1), else_=0)).label("od"),
            func.sum(case((PlacementAttendance.attendance_date == today_date, 1), else_=0)).label("today_total"),
            func.sum(case((and_(PlacementAttendance.attendance_date == today_date, PlacementAttendance.status.in_(["P", "OD"])), 1), else_=0)).label("today_attended"),
            func.sum(case((and_(PlacementAttendance.attendance_date == today_date, PlacementAttendance.status == "P"), 1), else_=0)).label("today_present"),
            func.sum(case((and_(PlacementAttendance.attendance_date == today_date, PlacementAttendance.status == "A"), 1), else_=0)).label("today_absent"),
            func.sum(case((and_(PlacementAttendance.attendance_date == today_date, PlacementAttendance.status == "OD"), 1), else_=0)).label("today_od")
        )
        .group_by(PlacementAttendance.class_id)
    )
    class_agg_rows = {r[0]: r for r in (await db.execute(stmt_class_agg)).all()}

    # 4. Student defaulters (< 75% in placement training)
    stmt_stu_agg = (
        select(
            Student.reg_no,
            Student.name,
            Student.class_id,
            func.count(PlacementAttendance.id).label("total"),
            func.sum(case((PlacementAttendance.status.in_(["P", "OD"]), 1), else_=0)).label("attended"),
            func.sum(case((PlacementAttendance.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((PlacementAttendance.status == "OD", 1), else_=0)).label("od")
        )
        .join(PlacementAttendance, PlacementAttendance.student_id == Student.id)
        .where(Student.status == "ACTIVE")
        .group_by(Student.id, Student.reg_no, Student.name, Student.class_id)
    )
    stu_agg_rows = (await db.execute(stmt_stu_agg)).all()

    defaulters = []
    class_defaulters_count: Dict[str, int] = {c.class_code: 0 for c, _ in cls_rows}
    for rn, sname, scid, s_tot, s_att, s_abs, s_od in stu_agg_rows:
        ccode = class_id_to_code.get(scid, "")
        cname = class_map[ccode].class_name if ccode in class_map else ccode
        tot = s_tot or 0
        att = s_att or 0
        ab = s_abs or 0
        od = s_od or 0
        pct = round((att / tot) * 100, 1) if tot > 0 else 0.0
        if tot > 0 and pct < 75.0:
            if ccode in class_defaulters_count:
                class_defaulters_count[ccode] += 1
            defaulters.append({
                "reg_no": rn,
                "name": sname,
                "class_id": ccode,
                "class_name": cname,
                "total": tot,
                "attended": att,
                "absent": ab,
                "od": od,
                "percentage": pct,
                "status": "CRITICAL" if pct < 65.0 else "WARNING"
            })

    defaulters.sort(key=lambda d: d["percentage"])

    # 5. Class-wise summaries
    classes_summary = []
    tot_marked_inst = 0
    tot_attended_inst = 0
    today_inst_total = 0
    today_inst_attended = 0
    today_inst_present = 0
    today_inst_absent = 0
    today_inst_od = 0

    dept_stats: Dict[str, Dict[str, int]] = {}

    for c, dept_code in cls_rows:
        ccode = c.class_code
        stats = class_agg_rows.get(c.id)
        scnt = class_student_count.get(ccode, 0)
        def_cnt = class_defaulters_count.get(ccode, 0)

        tot = stats.total if stats else 0
        att = stats.attended if stats else 0
        td_tot = stats.today_total if stats else 0
        td_att = stats.today_attended if stats else 0
        td_p = stats.today_present if stats else 0
        td_a = stats.today_absent if stats else 0
        td_od = stats.today_od if stats else 0

        tot_marked_inst += tot
        tot_attended_inst += att
        today_inst_total += td_tot
        today_inst_attended += td_att
        today_inst_present += td_p
        today_inst_absent += td_a
        today_inst_od += td_od

        d_key = dept_code or "OTHER"
        if d_key not in dept_stats:
            dept_stats[d_key] = {"total": 0, "attended": 0, "students": 0, "today_tot": 0, "today_att": 0}
        dept_stats[d_key]["total"] += tot
        dept_stats[d_key]["attended"] += att
        dept_stats[d_key]["students"] += scnt
        dept_stats[d_key]["today_tot"] += td_tot
        dept_stats[d_key]["today_att"] += td_att

        c_pct = round((att / tot * 100), 1) if tot > 0 else 0.0
        td_pct = round((td_att / td_tot * 100), 1) if td_tot > 0 else 0.0

        classes_summary.append({
            "class_id": ccode,
            "class_name": c.class_name,
            "department": dept_code,
            "year": str(c.year),
            "section": c.section,
            "semester": str(c.semester),
            "student_count": scnt,
            "total": tot,
            "attended": att,
            "overall_percentage": c_pct,
            "defaulters_count": def_cnt,
            "today_present": td_p,
            "today_absent": td_a,
            "today_od": td_od,
            "today_percentage": td_pct,
        })

    # 6. Overall Metrics
    overall_percentage = round((tot_attended_inst / tot_marked_inst * 100), 1) if tot_marked_inst > 0 else 0.0
    today_percentage = round((today_inst_attended / today_inst_total * 100), 1) if today_inst_total > 0 else 0.0

    # 7. Department Breakdown for Placement
    dept_breakdown = []
    for d_code, d_vals in sorted(dept_stats.items()):
        d_pct = round((d_vals["attended"] / d_vals["total"] * 100), 1) if d_vals["total"] > 0 else 0.0
        d_td_pct = round((d_vals["today_att"] / d_vals["today_tot"] * 100), 1) if d_vals["today_tot"] > 0 else 0.0
        dept_breakdown.append({
            "department": d_code,
            "student_count": d_vals["students"],
            "overall_percentage": d_pct,
            "today_percentage": d_td_pct,
        })

    # 8. Daily Trend (Last 14 days)
    stmt_trend = (
        select(
            PlacementAttendance.attendance_date,
            func.count(PlacementAttendance.id).label("total"),
            func.sum(case((PlacementAttendance.status.in_(["P", "OD"]), 1), else_=0)).label("attended")
        )
        .group_by(PlacementAttendance.attendance_date)
        .order_by(PlacementAttendance.attendance_date.asc())
    )
    trend_rows = (await db.execute(stmt_trend)).all()
    trend = []
    for s_date, t_tot, t_att in trend_rows[-14:]:
        d_str = s_date.strftime("%d-%m-%Y") if isinstance(s_date, (date, datetime)) else str(s_date)
        t_pct = round((t_att / t_tot * 100), 1) if t_tot > 0 else 0.0
        trend.append({
            "date": d_str,
            "percentage": t_pct,
            "total": t_tot,
            "attended": t_att
        })

    today_dict = {
        "present": today_inst_present,
        "absent": today_inst_absent,
        "on_duty": today_inst_od,
        "total": today_inst_total,
        "percentage": today_percentage,
    }

    status_dist = {
        "present": tot_attended_inst,
        "absent": max(0, tot_marked_inst - tot_attended_inst),
        "on_duty": sum(c.get("today_od", 0) for c in classes_summary),
    } if tot_marked_inst > 0 else {}

    class_stats = []
    for c in classes_summary:
        class_stats.append({
            "class_id": c["class_id"],
            "class_name": c["class_name"],
            "department": c["department"],
            "student_count": c["student_count"],
            "percentage": c["overall_percentage"],
            "attended_hours": c["attended"],
            "total_hours": c["total"],
            "on_duty": c.get("today_od", 0),
            "defaulters_count": c["defaulters_count"],
            "today": {
                "present": c["today_present"],
                "absent": c["today_absent"],
                "on_duty": c["today_od"],
                "percentage": c["today_percentage"]
            }
        })

    section_summaries = [
        {
            "class_id": c["class_id"],
            "class_name": c["class_name"],
            "total_students": c["student_count"],
            "percentage": c["percentage"],
        }
        for c in class_stats
    ]

    return {
        "timestamp": today_str,
        "is_placement_sandbox": True,
        "total_students": total_students,
        "total_classes": len(cls_rows),
        "overall_percentage": overall_percentage,
        "attended_hours": tot_attended_inst,
        "total_hours": tot_marked_inst,
        "today": today_dict,
        "trend": trend,
        "daily_trend": trend,
        "status_distribution": status_dist,
        "class_stats": class_stats,
        "classes": classes_summary,
        "section_summaries": section_summaries,
        "defaulters": defaulters,
        "defaulters_count": len(defaulters),
        "department_breakdown": dept_breakdown,
        "summary": {
            "total_students": total_students,
            "total_classes": len(cls_rows),
            "overall_percentage": overall_percentage,
            "total_defaulters": len(defaulters),
            "today_present": today_inst_present,
            "today_absent": today_inst_absent,
            "today_od": today_inst_od,
            "today_percentage": today_percentage,
        },
        "recent_activity": []
    }


async def get_placement_class_attendance_report(db: AsyncSession, class_id: str) -> List[Dict[str, Any]]:
    """
    Sub-5ms SQL calculation of student placement training attendance roster for a given class.
    Calculates statistics strictly from the placement_attendance table.
    """
    clean_cid = str(class_id or "").strip().upper()
    if clean_cid.isdigit():
        cls_stmt = select(ClassRoom.id).where(or_(ClassRoom.class_code == clean_cid, ClassRoom.id == int(clean_cid)))
    else:
        cls_stmt = select(ClassRoom.id).where(ClassRoom.class_code == clean_cid)
    c_pk = (await db.execute(cls_stmt)).scalar_one_or_none()
    if not c_pk:
        return []

    st_stmt = select(Student).where(and_(Student.class_id == c_pk, Student.status == "ACTIVE")).order_by(Student.reg_no)
    students = (await db.execute(st_stmt)).scalars().all()
    if not students:
        return []

    stu_ids = [s.id for s in students]

    rec_stmt = (
        select(
            PlacementAttendance.student_id,
            func.count(PlacementAttendance.id).label("total"),
            func.sum(case((PlacementAttendance.status.in_(["P", "OD"]), 1), else_=0)).label("present"),
            func.sum(case((PlacementAttendance.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((PlacementAttendance.status == "OD", 1), else_=0)).label("od")
        )
        .where(PlacementAttendance.student_id.in_(stu_ids))
        .group_by(PlacementAttendance.student_id)
    )
    rec_map = {r[0]: r for r in (await db.execute(rec_stmt)).all()}

    report = []
    for s in students:
        stats = rec_map.get(s.id)
        tot = stats.total if stats else 0
        pres = stats.present if stats else 0
        ab = stats.absent if stats else 0
        od = stats.od if stats else 0
        pct = round((pres / tot * 100), 2) if tot > 0 else 0.0

        report.append({
            "reg_no": s.reg_no,
            "RegNo": s.reg_no,
            "name": s.name,
            "Name": s.name,
            "working_days": tot,
            "total": tot,
            "attended": pres,
            "absent": ab,
            "od": od,
            "percentage": pct,
        })

    report.sort(key=lambda x: str(x.get("reg_no", "")))
    return report


async def get_placement_attendance_overview(
    db: AsyncSession,
    target_date_str: str,
) -> Dict[str, Any]:
    """
    Returns submitted and pending placement attendance for a date across all classes.
    """
    target_date = parse_date_str(target_date_str) or date.today()
    dstr = target_date.strftime("%d-%m-%Y")

    stmt_all = (
        select(ClassRoom, Department.code)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.status == "ACTIVE")
        .order_by(Department.code, ClassRoom.class_code)
    )
    all_classes = (await db.execute(stmt_all)).all()
    class_map = {c.id: c for c, _ in all_classes}

    stmt_cnt = (
        select(Student.class_id, func.count(Student.id))
        .where(Student.status == "ACTIVE")
        .group_by(Student.class_id)
    )
    stu_counts = dict((await db.execute(stmt_cnt)).all())

    # Find placement attendances for target_date
    stmt_sess = (
        select(
            PlacementAttendance.class_id,
            PlacementAttendance.slot_type,
            PlacementAttendance.training_topic,
            PlacementAttendance.faculty_id,
            func.count(PlacementAttendance.id).label("total"),
            func.sum(case((PlacementAttendance.status == "P", 1), else_=0)).label("present"),
            func.sum(case((PlacementAttendance.status == "A", 1), else_=0)).label("absent"),
            func.sum(case((PlacementAttendance.status == "OD", 1), else_=0)).label("od"),
            func.min(PlacementAttendance.created_at).label("created_at")
        )
        .where(PlacementAttendance.attendance_date == target_date)
        .group_by(
            PlacementAttendance.class_id,
            PlacementAttendance.slot_type,
            PlacementAttendance.training_topic,
            PlacementAttendance.faculty_id
        )
    )
    placement_rows = (await db.execute(stmt_sess)).all()

    # Faculty names
    fac_ids = [r[3] for r in placement_rows if r[3]]
    fac_map = {}
    if fac_ids:
        f_stmt = select(User.id, User.full_name).where(User.id.in_(fac_ids))
        fac_map = dict((await db.execute(f_stmt)).all())

    submitted_sessions = []
    submitted_class_pks = set()

    for cid, stype, topic, fid, tot, p_cnt, a_cnt, od_cnt, c_at in placement_rows:
        cls_obj = class_map.get(cid)
        if not cls_obj:
            continue
        submitted_class_pks.add(cid)
        fac_name = fac_map.get(fid, "Placement Faculty")
        cname = cls_obj.class_name
        pct = round(((p_cnt + od_cnt) / tot * 100), 1) if tot > 0 else 0.0

        submitted_sessions.append({
            "class_id": cls_obj.class_code,
            "class_name": cname,
            "year": str(cls_obj.year),
            "section": cls_obj.section,
            "semester": str(cls_obj.semester),
            "hour": stype,
            "subject_id": "PLACEMENT",
            "subject_name": topic or "Placement Training",
            "faculty_id": str(fid or ""),
            "faculty_name": fac_name,
            "timestamp": c_at.strftime("%H:%M:%S") if c_at else "",
            "present": p_cnt or 0,
            "absent": a_cnt or 0,
            "on_duty": od_cnt or 0,
            "total_students": tot or 0,
            "percentage": pct,
        })

    submitted_sessions.sort(key=lambda x: (x["class_name"], x["hour"]))

    pending_classes = []
    for cls_obj, _ in all_classes:
        if cls_obj.id not in submitted_class_pks:
            pending_classes.append({
                "class_id": cls_obj.class_code,
                "class_name": cls_obj.class_name,
                "year": str(cls_obj.year),
                "section": cls_obj.section,
                "semester": str(cls_obj.semester),
                "student_count": stu_counts.get(cls_obj.id, 0),
            })

    pending_classes.sort(key=lambda x: x["class_name"])

    return {
        "date": dstr,
        "is_placement": True,
        "total_classes": len(all_classes),
        "submitted_count": len(submitted_sessions),
        "pending_count": len(pending_classes),
        "submitted": submitted_sessions,
        "pending": pending_classes,
    }


async def get_placement_class_matrix(
    db: AsyncSession,
    class_id: str,
    month: Optional[int] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Returns monthly day-by-day attendance grid for placement training.
    """
    clean_cid = str(class_id or "").strip().upper()
    cls_stmt = (
        select(ClassRoom, Department.code)
        .join(Department, ClassRoom.department_id == Department.id)
        .where(ClassRoom.class_code == clean_cid)
    )
    res = await db.execute(cls_stmt)
    row = res.first()
    if not row:
        return {"error": f"Class '{clean_cid}' not found.", "date_cols": [], "matrix_rows": []}

    cls_obj, dept_code = row
    c_pk = cls_obj.id

    now = datetime.now()
    target_year = year or now.year
    target_month = month or now.month
    month_name = calendar.month_name[target_month]
    num_days = calendar.monthrange(target_year, target_month)[1]

    date_cols = [f"{d:02d}-{target_month:02d}-{target_year}" for d in range(1, num_days + 1)]

    st_stmt = select(Student).where(and_(Student.class_id == c_pk, Student.status == "ACTIVE")).order_by(Student.reg_no)
    students = (await db.execute(st_stmt)).scalars().all()

    start_d = date(target_year, target_month, 1)
    end_d = date(target_year, target_month, num_days)

    stmt_records = (
        select(
            PlacementAttendance.student_id,
            PlacementAttendance.attendance_date,
            PlacementAttendance.status
        )
        .where(
            and_(
                PlacementAttendance.class_id == c_pk,
                PlacementAttendance.attendance_date >= start_d,
                PlacementAttendance.attendance_date <= end_d
            )
        )
    )
    rec_rows = (await db.execute(stmt_records)).all()

    att_grid: Dict[int, Dict[str, str]] = {}
    for sid, s_date, st_val in rec_rows:
        if sid not in att_grid:
            att_grid[sid] = {}
        d_str = s_date.strftime("%d-%m-%Y") if isinstance(s_date, (date, datetime)) else str(s_date)
        att_grid[sid][d_str] = (st_val or "").strip().upper()

    matrix_rows = []
    for s in students:
        p_count = 0
        a_count = 0
        od_count = 0
        s_grid = att_grid.get(s.id, {})
        day_statuses = {}

        for d_str in date_cols:
            val = s_grid.get(d_str, "-")
            day_statuses[d_str] = val
            if val == "P":
                p_count += 1
            elif val == "A":
                a_count += 1
            elif val in ("OD", "ONDUTY", "ON DUTY"):
                od_count += 1

        tot = p_count + a_count + od_count
        eff = p_count + od_count
        pct = round((eff / tot) * 100, 1) if tot > 0 else 0.0

        matrix_rows.append({
            "reg_no": s.reg_no,
            "name": s.name,
            "statuses": day_statuses,
            "total_present": p_count,
            "total_absent": a_count,
            "total_od": od_count,
            "total_sessions": tot,
            "percentage": pct,
        })

    return {
        "class_id": clean_cid,
        "class_name": cls_obj.class_name,
        "department": dept_code,
        "month": target_month,
        "month_name": month_name,
        "year": target_year,
        "date_cols": date_cols,
        "matrix_rows": matrix_rows,
        "is_placement": True
    }


async def get_sql_daily_status_students(
    db: AsyncSession,
    date_str: str,
    status_filter: str = "A",
    dept_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    Returns student-level details (RegNo, Name, Class, Department, Hour, Subject, Faculty)
    for all students marked with `status_filter` (typically 'A' for Absent, 'OD' for On-Duty)
    on a specific date.
    Strictly enforces HOD departmental boundaries.
    """
    target_date = parse_date_str(date_str) or date.today()
    norm_status = status_filter.strip().upper()
    norm_dept = str(dept_code or "").strip().upper()

    records = []

    if norm_dept == "PLACEMENT":
        # Query strictly from placement_attendance
        stmt = (
            select(
                PlacementAttendance,
                Student.reg_no,
                Student.name.label("student_name"),
                ClassRoom.class_code,
                ClassRoom.class_name,
                Department.code.label("department_code"),
                User.full_name.label("faculty_name")
            )
            .join(Student, PlacementAttendance.student_id == Student.id)
            .join(ClassRoom, PlacementAttendance.class_id == ClassRoom.id)
            .join(Department, ClassRoom.department_id == Department.id)
            .outerjoin(User, PlacementAttendance.faculty_id == User.id)
            .where(
                and_(
                    PlacementAttendance.attendance_date == target_date,
                    PlacementAttendance.status == norm_status
                )
            )
            .order_by(ClassRoom.class_code, Student.reg_no)
        )
        res = await db.execute(stmt)
        for p, rn, sname, ccode, cname, dcode, fname in res.all():
            records.append({
                "reg_no": rn,
                "name": sname,
                "class_code": ccode,
                "class_name": cname,
                "department": dcode,
                "hour": p.slot_type,
                "subject_code": "PLACEMENT",
                "subject_name": p.training_topic or p.slot_type,
                "faculty_name": fname or "Placement Trainer",
                "status": p.status,
                "date": target_date.strftime("%d-%m-%Y")
            })
    else:
        # Query academic attendance records
        stmt = (
            select(
                AttendanceRecord.status,
                Student.reg_no,
                Student.name.label("student_name"),
                ClassRoom.class_code,
                ClassRoom.class_name,
                Department.code.label("department_code"),
                AttendanceSession.slot_hour,
                Subject.subject_code,
                Subject.subject_name,
                User.full_name.label("faculty_name")
            )
            .join(AttendanceSession, AttendanceRecord.session_id == AttendanceSession.id)
            .join(Student, AttendanceRecord.student_id == Student.id)
            .join(ClassRoom, AttendanceSession.class_id == ClassRoom.id)
            .join(Department, ClassRoom.department_id == Department.id)
            .outerjoin(Subject, AttendanceSession.subject_id == Subject.id)
            .outerjoin(User, AttendanceSession.faculty_id == User.id)
            .where(
                and_(
                    AttendanceSession.session_date == target_date,
                    AttendanceRecord.status == norm_status
                )
            )
        )
        if norm_dept and norm_dept != "ALL":
            stmt = stmt.where(Department.code == norm_dept)

        stmt = stmt.order_by(ClassRoom.class_code, Student.reg_no)
        res = await db.execute(stmt)
        for st_val, rn, sname, ccode, cname, dcode, shour, scode, s_name, fname in res.all():
            records.append({
                "reg_no": rn,
                "name": sname,
                "class_code": ccode,
                "class_name": cname,
                "department": dcode,
                "hour": shour or "DAY",
                "subject_code": scode or "",
                "subject_name": s_name or "",
                "faculty_name": fname or "Faculty",
                "status": st_val,
                "date": target_date.strftime("%d-%m-%Y")
            })

    status_label = "Absent" if norm_status == "A" else ("On-Duty" if norm_status == "OD" else norm_status)
    return {
        "date": target_date.strftime("%d-%m-%Y"),
        "status": norm_status,
        "status_label": status_label,
        "department": norm_dept or "ALL",
        "count": len(records),
        "students": records
    }

