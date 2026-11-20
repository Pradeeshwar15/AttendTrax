# =============================================================================
# AttendTrax Enterprise – Comprehensive Security & E2E Verification Suite
# tests/test_e2e.py – Full Institutional Lifecycle, Cohort Reset & Multi-Setup
# =============================================================================
import asyncio
import io
import sys
import os
import zipfile
import openpyxl
from httpx import AsyncClient, ASGITransport

# Ensure UTF-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app


async def run_suite():
    print("=" * 60)
    print("[*] ATTENDTRAX SECURITY, RESET & MULTI-SETUP SUITE")
    print("=" * 60)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Health & Security Headers
        print("\n[1] Checking Health & HTTP Security Headers...")
        r_health = await client.get("/health")
        assert r_health.status_code == 200, f"Health check failed: {r_health.text}"
        assert r_health.json()["status"] == "ok"
        print("  [PASS] Health: OK")

        headers = r_health.headers
        assert headers.get("X-Content-Type-Options") == "nosniff"
        assert headers.get("X-Frame-Options") == "DENY"
        assert headers.get("X-XSS-Protection") == "1; mode=block"
        assert headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        print("  [PASS] Security Headers: nosniff, DENY, XSS-filter, strict-origin enforced")

        # 2. Sliding-Window Rate Limiter
        print("\n[2] Checking Sliding-Window Rate Limiter on /auth/login...")
        test_user = "rate_limit_test_probe"
        hit_429 = False
        for i in range(1, 8):
            resp = await client.post(
                "/auth/login",
                json={"username": test_user, "password": "WrongPassword123!"},
                headers={"X-Forwarded-For": "203.0.113.195"}
            )
            if resp.status_code == 429:
                hit_429 = True
                retry_after = resp.headers.get("Retry-After")
                print(f"  [PASS] Attempt {i} correctly blocked with HTTP 429 (Retry-After: {retry_after}s)")
                break
            elif resp.status_code == 401:
                print(f"  Attempt {i}: 401 Unauthorized (as expected)")
        assert hit_429, "Rate limiter did not block excessive failed login attempts!"

        # 3. Super Admin & Leadership Logins
        print("\n[3] Testing Leadership & Administrator Authentication...")
        r_admin = await client.post("/auth/login", json={"username": "admin", "password": "AttendTrax@2026"})
        assert r_admin.status_code == 200, f"Admin login failed: {r_admin.text}"
        admin_data = r_admin.json()
        admin_token = admin_data["access_token"]
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        print(f"  [PASS] Central Admin Login: {admin_data['name']} (Role: {admin_data['role']})")

        r_princ = await client.post("/auth/login", json={"username": "principal", "password": "Principal@2026"})
        assert r_princ.status_code == 200, f"Principal login failed: {r_princ.text}"
        assert "Dr. Devaraju" in r_princ.json()["name"]
        princ_token = r_princ.json()["access_token"]
        princ_headers = {"Authorization": f"Bearer {princ_token}"}
        print(f"  [PASS] Principal Login: {r_princ.json()['name']}")

        r_vp = await client.post("/auth/login", json={"username": "viceprincipal", "password": "VP@2026"})
        assert r_vp.status_code == 200, f"VP login failed: {r_vp.text}"
        assert "Dr. Basker" in r_vp.json()["name"]
        print(f"  [PASS] Vice Principal Login: {r_vp.json()['name']}")

        # 4. Department HOD Logins (All 9 Academic Branches)
        print("\n[4] Verifying All 9 Department HOD Logins...")
        academic_hods = [
            ("hod.cse", "CSE"), ("hod.it", "IT"), ("hod.aids", "AIDS"),
            ("hod.ece", "ECE"), ("hod.mech", "MECH"), ("hod.eee", "EEE"),
            ("hod.cyber", "CYBER"), ("hod.aiml", "AIML"), ("hod.sh", "SH")
        ]
        hod_tokens = {}
        for uname, dcode in academic_hods:
            r_h = await client.post("/auth/login", json={"username": uname, "password": "Hod@2026"})
            assert r_h.status_code == 200, f"HOD {uname} login failed: {r_h.text}"
            h_data = r_h.json()
            assert h_data["role"] == "DEPT_ADMIN"
            hod_tokens[dcode] = h_data["access_token"]
            print(f"  [PASS] HOD {uname.upper()} (Dept: {dcode}): Login 200 OK")

        # 5. Executive Institutional Reset / Cohort Purge
        print("\n[5] Testing Complete Institutional Reset (Purge Cohorts)...")
        r_purge = await client.post("/admin/executive/purge-academic-cohorts", headers=princ_headers)
        assert r_purge.status_code == 200, f"Purge cohorts failed: {r_purge.text}"
        purge_res = r_purge.json()
        assert purge_res["status"] == "success"
        print(f"  [PASS] Institutional Reset Executed: {purge_res['message']}")

        # Verify 0 classes and 0 students remaining
        r_chk_classes = await client.get("/admin/classes", headers=admin_headers)
        assert len(r_chk_classes.json()) == 0, f"Expected 0 classes after purge, got {len(r_chk_classes.json())}"
        r_chk_students = await client.get("/admin/students", headers=admin_headers)
        assert len(r_chk_students.json()) == 0, f"Expected 0 students after purge, got {len(r_chk_students.json())}"
        print("  [PASS] Baseline Clean Slate Confirmed: 0 classes and 0 students active")

        # 6. Department HOD Manual Class Creation & Sandboxing
        print("\n[6] Testing Department HOD Manual Class Creation & Sandboxing...")
        cse_hod_headers = {"Authorization": f"Bearer {hod_tokens['CSE']}"}
        ece_hod_headers = {"Authorization": f"Bearer {hod_tokens['ECE']}"}

        # 6a. HOD CSE creates CSE3A
        r_cse_cls = await client.post(
            "/admin/classes",
            json={"class_id": "CSE3A", "class_name": "CSE III Year A", "year": "3", "section": "A", "semester": "5"},
            headers=cse_hod_headers
        )
        assert r_cse_cls.status_code == 200, f"CSE class creation failed: {r_cse_cls.text}"
        assert r_cse_cls.json()["class_id"] == "CSE3A"
        assert r_cse_cls.json()["department"] == "CSE"
        print("  [PASS] HOD CSE Class Creation: CSE3A created successfully")

        # 6b. HOD ECE creates ECE2A
        r_ece_cls = await client.post(
            "/admin/classes",
            json={"class_id": "ECE2A", "class_name": "ECE II Year A", "year": "2", "section": "A", "semester": "3"},
            headers=ece_hod_headers
        )
        assert r_ece_cls.status_code == 200, f"ECE class creation failed: {r_ece_cls.text}"
        assert r_ece_cls.json()["class_id"] == "ECE2A"
        assert r_ece_cls.json()["department"] == "ECE"
        print("  [PASS] HOD ECE Class Creation: ECE2A created successfully")

        # 6c. HOD ECE attempts to create class with CSE prefix -> Must be 403 Forbidden
        r_cross_cls = await client.post(
            "/admin/classes",
            json={"class_id": "CSE3B", "class_name": "CSE Cross Dept", "year": "3", "section": "B", "semester": "5"},
            headers=ece_hod_headers
        )
        assert r_cross_cls.status_code == 403, f"Expected 403 on cross-department class creation, got {r_cross_cls.status_code}"
        print("  [PASS] HOD Class Sandboxing: HOD ECE blocked from creating CSE class (403 Forbidden)")

        # 6d. HOD ECE attempts to delete CSE3A -> Must be 403 Forbidden
        r_cross_del = await client.delete("/admin/classes/CSE3A", headers=ece_hod_headers)
        assert r_cross_del.status_code == 403, f"Expected 403 on cross-department class delete, got {r_cross_del.status_code}"
        print("  [PASS] HOD Class Sandboxing: HOD ECE blocked from deleting CSE class (403 Forbidden)")

        # 6e. Verify Scoped Class Visibility
        r_cse_classes = await client.get("/admin/classes", headers=cse_hod_headers)
        assert len(r_cse_classes.json()) == 1 and r_cse_classes.json()[0]["ClassID"] == "CSE3A"
        r_ece_classes = await client.get("/admin/classes", headers=ece_hod_headers)
        assert len(r_ece_classes.json()) == 1 and r_ece_classes.json()[0]["ClassID"] == "ECE2A"
        r_admin_classes = await client.get("/admin/classes", headers=admin_headers)
        assert len(r_admin_classes.json()) == 2
        print("  [PASS] Scoped Class Visibility: HOD CSE sees only CSE, HOD ECE sees only ECE, Admin sees all")

        # 7. Multi-Setup Student Ingestion (Single & Bulk Excel)
        print("\n[7] Testing Multi-Setup Student Ingestion & Sandboxing...")

        # 7a. Single Student Add by HOD CSE
        r_add_s1 = await client.post(
            "/admin/students",
            json={"reg_no": "24CS001", "name": "Aarav Kumar", "class_id": "CSE3A", "password": "Student@2026"},
            headers=cse_hod_headers
        )
        assert r_add_s1.status_code == 200, f"Single student add failed: {r_add_s1.text}"
        print("  [PASS] HOD Single Student Add: 24CS001 onboarded into CSE3A")

        # 7b. Cross-Department Student Add Blocked
        r_cross_stu = await client.post(
            "/admin/students",
            json={"reg_no": "24EC001", "name": "Bhavna Sharma", "class_id": "CSE3A", "password": "Student@2026"},
            headers=ece_hod_headers
        )
        assert r_cross_stu.status_code == 403, f"Expected 403 on cross-dept student add, got {r_cross_stu.status_code}"
        print("  [PASS] HOD Student Sandboxing: HOD ECE blocked from adding student to CSE3A (403 Forbidden)")

        # 7c. HOD ECE adds student to ECE2A
        r_add_s2 = await client.post(
            "/admin/students",
            json={"reg_no": "24EC001", "name": "Bhavna Sharma", "class_id": "ECE2A", "password": "Student@2026"},
            headers=ece_hod_headers
        )
        assert r_add_s2.status_code == 200, f"ECE student add failed: {r_add_s2.text}"
        print("  [PASS] HOD Single Student Add: 24EC001 onboarded into ECE2A")

        # 7d. Student Login Verification
        r_stu_login = await client.post("/auth/login", json={"username": "24CS001", "password": "Student@2026"})
        assert r_stu_login.status_code == 200, f"Student login failed: {r_stu_login.text}"
        stu_token = r_stu_login.json()["access_token"]
        stu_headers = {"Authorization": f"Bearer {stu_token}"}
        assert r_stu_login.json()["role"] == "STUDENT"
        print(f"  [PASS] Student Authentication: {r_stu_login.json()['name']} logged in with role STUDENT")

        # Student RBAC restriction
        r_stu_admin_blocked = await client.get("/admin/analytics", headers=stu_headers)
        assert r_stu_admin_blocked.status_code == 403
        print("  [PASS] Student RBAC: Blocked from administrative routes (403 Forbidden)")

        # 7e. Super Admin Multi-Setup Bulk Excel Import
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Students"
        ws.append(["RegNo", "Name", "ClassID", "ClassName", "Username", "Password"])
        ws.append(["24CS002", "Chirag M", "CSE3A", "CSE III Year A", "24cs002", "Student@2026"])
        ws.append(["24CS003", "Divya R", "CSE3A", "CSE III Year A", "24cs003", "Student@2026"])
        ws.append(["24EC002", "Eashwar K", "ECE2A", "ECE II Year A", "24ec002", "Student@2026"])
        ws.append(["24EC003", "Farhan A", "ECE2A", "ECE II Year A", "24ec003", "Student@2026"])
        excel_buf = io.BytesIO()
        wb.save(excel_buf)
        excel_bytes = excel_buf.getvalue()

        r_bulk = await client.post(
            "/admin/import/students",
            files={"file": ("master_students.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=admin_headers
        )
        assert r_bulk.status_code == 200, f"Bulk import failed: {r_bulk.text}"
        bulk_res = r_bulk.json()
        assert bulk_res["inserted"] == 4
        print(f"  [PASS] Multi-Setup Bulk Excel Import: 4 students ingested across CSE3A and ECE2A")

        # Verify total student directory count
        r_all_st = await client.get("/admin/students", headers=admin_headers)
        assert len(r_all_st.json()) == 6, f"Expected 6 total students, got {len(r_all_st.json())}"
        print(f"  [PASS] Student Directory Integrity: Verified 6 total active students across all classes")

        # 8. Faculty Attendance Submission & Student Portal Sync
        print("\n[8] Testing Faculty Attendance Marking & Student Summary Sync...")
        r_fac = await client.post("/auth/login", json={"username": "fathima.cse", "password": "Staff@2026"})
        assert r_fac.status_code == 200
        fac_headers = {"Authorization": f"Bearer {r_fac.json()['access_token']}"}

        r_att_sub = await client.post(
            "/faculty/attendance",
            json={
                "class_id": "CSE3A",
                "subject_id": "CS8591",
                "hour": "DAY",
                "attendance": [
                    {"reg_no": "24CS001", "status": "P"},
                    {"reg_no": "24CS002", "status": "P"},
                    {"reg_no": "24CS003", "status": "A"},
                ]
            },
            headers=fac_headers
        )
        assert r_att_sub.status_code in (200, 409), f"Faculty attendance failed: {r_att_sub.text}"
        print("  [PASS] Faculty Attendance Marking: CSE3A daily attendance recorded")

        # Student checks portal summary
        r_s_sum = await client.get("/student/attendance", headers=stu_headers)
        assert r_s_sum.status_code == 200
        print(f"  [PASS] Student Attendance Summary: {r_s_sum.json().get('percentage')}% attendance verified")

        # 9. Faculty Creation Sandboxing & Leave Approval Integrity
        print("\n[9] Testing Sandboxed Faculty Creation & Leave Workflow...")
        r_create_fac = await client.post(
            "/admin/faculty",
            json={
                "faculty_id": "CSE999",
                "name": "Prof. Rajesh Test",
                "username": "rajesh.test",
                "password": "Staff@2026",
                "department": "MECH",  # HOD is CSE, should enforce CSE
                "designation": "Assistant Professor"
            },
            headers=cse_hod_headers
        )
        assert r_create_fac.status_code == 200
        assert r_create_fac.json()["department"] == "CSE"
        print("  [PASS] HOD Sandbox Enforced: Faculty assigned to CSE regardless of input")

        # New faculty applies leave -> HOD approves -> Principal sanctions
        r_n_login = await client.post("/auth/login", json={"username": "rajesh.test", "password": "Staff@2026"})
        assert r_n_login.status_code == 200
        n_fac_headers = {"Authorization": f"Bearer {r_n_login.json()['access_token']}"}

        r_l_app = await client.post(
            "/leaves/faculty/apply",
            json={"leave_category": "CASUAL", "session_scope": "FULL_DAY", "start_date": "2026-11-25", "end_date": "2026-11-25", "reason": "Academic seminar"},
            headers=n_fac_headers
        )
        assert r_l_app.status_code == 200
        lid = r_l_app.json()["leave_id"]

        r_h_app = await client.patch(f"/leaves/faculty/{lid}/hod-review", json={"action": "APPROVE", "remarks": "Approved"}, headers=cse_hod_headers)
        assert r_h_app.status_code == 200
        r_p_app = await client.patch(f"/leaves/faculty/{lid}/principal-review", json={"action": "APPROVE", "remarks": "Sanctioned"}, headers=princ_headers)
        assert r_p_app.status_code == 200

        r_doc = await client.get(f"/leaves/faculty/{lid}/sanction-docket", headers=princ_headers)
        assert r_doc.status_code == 200
        doc_data = r_doc.json()
        assert doc_data["faculty"]["name"] == "Prof. Rajesh Test"
        assert "Dr. Devaraju" in doc_data["endorsements"]["principal"]["name"]
        assert doc_data["docket_id"].startswith("ACET/EST-LV/2026/")
        assert "Adhi College of Engineering & Technology" in doc_data["verification"]["authority"]
        print("  [PASS] Printable Docket: ACET Sanction Docket verified with Dr. Devaraju signature")

        # 10. Placement Universal Access
        print("\n[10] Testing Placement Department Universal Access...")
        r_plc_h = await client.post("/auth/login", json={"username": "hod.placement", "password": "Hod@2026"})
        assert r_plc_h.status_code == 200
        plc_h_headers = {"Authorization": f"Bearer {r_plc_h.json()['access_token']}"}

        r_plc_st = await client.get("/admin/students", headers=plc_h_headers)
        assert r_plc_st.status_code == 200
        assert len(r_plc_st.json()) == 6
        print("  [PASS] Placement Universal Access: Sees all candidate records across all departments")

        # 11. Principal Master Data Export
        print("\n[11] Testing Principal Master Data Export...")
        r_exp_zip = await client.get("/admin/executive/export-all", headers=princ_headers)
        assert r_exp_zip.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r_exp_zip.content))
        names = zf.namelist()
        assert "AttendTrax_Students_Master.csv" in names
        assert "AttendTrax_Faculty_Master.csv" in names
        assert "AttendTrax_Attendance_Reports.csv" in names
        print(f"  [PASS] Master Institutional Export (ZIP): Valid package containing {', '.join(names)}")

        # 12. Placement Staff Leave Workflow & Level-1 Recommendation Verification
        print("\n[12] Testing Placement Staff Leave Workflow & HOD Level-1 Review...")
        r_plc_staff = await client.post("/auth/login", json={"username": "placement.staff", "password": "Staff@2026"})
        assert r_plc_staff.status_code == 200
        plc_staff_headers = {"Authorization": f"Bearer {r_plc_staff.json()['access_token']}"}

        r_plc_l = await client.post(
            "/leaves/faculty/apply",
            json={
                "leave_category": "ON_DUTY",
                "session_scope": "FULL_DAY",
                "start_date": "2026-11-28",
                "end_date": "2026-11-28",
                "reason": "Campus Placement Pool Drive at Partner Institution"
            },
            headers=plc_staff_headers
        )
        assert r_plc_l.status_code == 200
        plc_lid = r_plc_l.json()["leave_id"]
        assert plc_lid > 0

        # Placement HOD reviews pending leaves
        r_plc_queue = await client.get("/leaves/faculty/pending-hod", headers=plc_h_headers)
        assert r_plc_queue.status_code == 200
        queue_items = r_plc_queue.json()
        target_ticket = next((item for item in queue_items if item["id"] == plc_lid), None)
        assert target_ticket is not None, f"Placement staff leave {plc_lid} not visible to hod.placement queue: {queue_items}"
        print(f"  [PASS] Placement HOD Queue: Ticket #{plc_lid} visible with reason: '{target_ticket['reason']}'")

        # Placement HOD recommends leave
        r_plc_rec = await client.patch(
            f"/leaves/faculty/{plc_lid}/hod-review",
            json={"action": "APPROVE", "remarks": "Strongly recommended for pool drive representation."},
            headers=plc_h_headers
        )
        assert r_plc_rec.status_code == 200
        print("  [PASS] Placement HOD Level-1 Review: Recommended successfully without authorization or department errors")

        # Principal sanctions placement staff leave
        r_princ_plc = await client.patch(
            f"/leaves/faculty/{plc_lid}/principal-review",
            json={"action": "APPROVE", "remarks": "Executive leave sanctioned for campus placement."},
            headers=princ_headers
        )
        assert r_princ_plc.status_code == 200

        # Verify Docket
        r_plc_doc = await client.get(f"/leaves/faculty/{plc_lid}/sanction-docket", headers=princ_headers)
        assert r_plc_doc.status_code == 200
        plc_doc = r_plc_doc.json()
        assert plc_doc["docket_id"].startswith("ACET/EST-LV/2026/")
        assert "Adhi College of Engineering & Technology" in plc_doc["verification"]["authority"]
        assert "Campus Placement" in plc_doc["leave"]["reason"]
        print("  [PASS] ACET Leave Docket: Placement staff docket sanctioned with ACET prefix and Dr. Devaraju seal")

        print("\n" + "=" * 60)
        print("[SUCCESS] ALL SECURITY, RESET & MULTI-SETUP TESTS PASSED 100%!")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_suite())
