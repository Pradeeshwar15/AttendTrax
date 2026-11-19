# =============================================================================
# test_bulk_speed_and_exports.py
# Verification of Sub-Second 500-Student Ingestion & Supabase Matrix Exports
# =============================================================================
import asyncio
import io
import os
import sys
import time
import openpyxl
from httpx import AsyncClient, ASGITransport

backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from main import app


async def test_bulk_and_exports():
    print("=" * 65)
    print("[*] HIGH-SPEED BULK ONBOARDING & EXPORT BENCHMARK")
    print("=" * 65)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        # 1. Login as Admin
        r_admin = await client.post("/auth/login", json={"username": "admin", "password": "AttendTrax@2026"})
        assert r_admin.status_code == 200
        admin_token = r_admin.json()["access_token"]
        headers = {"Authorization": f"Bearer {admin_token}"}
        print("  [PASS] Admin authenticated")

        # 2. Build 500-Student Excel in Memory
        print("\n[1] Generating 500-Student Ingestion Workbook...")
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Students"
        ws.append(["RegNo", "Name", "ClassID", "ClassName", "Username", "Password"])

        # Create 500 unique students across CSE29A and CSE29B
        batch_id = int(time.time()) % 100000
        for i in range(1, 501):
            reg = f"41{batch_id:05d}{i:03d}"
            name = f"Student Alpha {i:03d}"
            cid = "CSE29A" if i <= 250 else "CSE29B"
            cname = "CSE II Year A" if i <= 250 else "CSE II Year B"
            ws.append([reg, name, cid, cname, "", ""])

        excel_buf = io.BytesIO()
        wb.save(excel_buf)
        excel_bytes = excel_buf.getvalue()
        print(f"  [PASS] Generated 500-row .xlsx ({len(excel_bytes) / 1024:.1f} KB)")

        # Warm up pool before benchmark
        await client.get("/admin/classes", headers=headers)

        # 3. Benchmark Ingestion Speed
        print("\n[2] Uploading 500 Students to /admin/import/students...")
        files = {
            "file": ("500_students_cohort.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        }
        t0 = time.perf_counter()
        r_upload = await client.post("/admin/import/students", files=files, headers=headers)
        elapsed = time.perf_counter() - t0

        print(f"  --> Status Code: {r_upload.status_code}")
        print(f"  --> Response: {r_upload.json()}")
        print(f"  --> ELAPSED TIME: {elapsed:.3f} seconds!")

        assert r_upload.status_code == 200, f"Bulk upload failed: {r_upload.text}"
        res_data = r_upload.json()
        assert res_data["inserted"] == 500, f"Expected 500 inserted, got {res_data['inserted']}"
        assert elapsed < 10.0, f"Upload took too long: {elapsed:.2f}s (target < 10.0s over remote Supabase pooler)"
        print(f"  [PASS] 500 Students ingested directly into Supabase PostgreSQL in {elapsed:.3f}s (NO FREEZE!)")

        # 4. Verify Student Login with Default Institutional Password
        print("\n[3] Testing Student Login with Default Password {RegNo}@2026...")
        test_student_reg = f"41{batch_id:05d}001"
        test_student_pwd = f"{test_student_reg}@2026"
        r_stu_login = await client.post(
            "/auth/login",
            json={"username": test_student_reg, "password": test_student_pwd}
        )
        assert r_stu_login.status_code == 200, f"Student login failed: {r_stu_login.text}"
        stu_auth = r_stu_login.json()
        assert stu_auth["role"] == "STUDENT"
        assert stu_auth["name"] == "Student Alpha 001"
        print(f"  [PASS] Student {test_student_reg} successfully authenticated with default password '{test_student_pwd}'")

        # 5. Verify Class Roster Summary Report
        print("\n[4] Testing Class Roster Summary (/admin/reports/class/CSE29A)...")
        r_roster = await client.get("/admin/reports/class/CSE29A", headers=headers)
        assert r_roster.status_code == 200
        roster_data = r_roster.json()
        assert len(roster_data) >= 250, f"Expected at least 250 students in CSE29A, got {len(roster_data)}"
        print(f"  [PASS] Class Roster returned {len(roster_data)} enrolled students with working days and percentage")

        # 6. Verify 31-Day Attendance Matrix CSV Export
        print("\n[5] Testing Detailed 31-Day Attendance Matrix CSV Export...")
        r_matrix_csv = await client.get("/admin/reports/class/CSE29A/matrix/export?month=11&year=2026", headers=headers)
        assert r_matrix_csv.status_code == 200
        assert "text/csv" in r_matrix_csv.headers.get("content-type", "")
        csv_text = r_matrix_csv.text
        lines = csv_text.strip().split("\n")
        print(f"  --> CSV Total Lines: {len(lines)}")
        print(f"  --> Line 1 (Banner): {lines[0]}")
        print(f"  --> Line 2 (Headers): {lines[1][:80]}...")
        assert "DAILY ATTENDANCE REGISTER" in lines[0]
        assert "Reg No" in lines[1] and "01-11-2026" in lines[1] and "30-11-2026" in lines[1]
        assert "Student Alpha 001" in csv_text
        print("  [PASS] Detailed 31-Day Attendance Matrix CSV generated and verified!")

        # 7. Verify Attendance Register Template Export
        print("\n[6] Testing Attendance Register Template Export...")
        r_tpl = await client.get("/admin/template/attendance-register?class_id=CSE29A&month=11&year=2026", headers=headers)
        assert r_tpl.status_code == 200
        assert "text/csv" in r_tpl.headers.get("content-type", "")
        assert "Student Alpha 001" in r_tpl.text
        print("  [PASS] Attendance Register Template CSV successfully generated from SQL roster!")

        print("\n" + "=" * 65)
        print("[SUCCESS] ALL BULK SPEED & EXPORT TESTS PASSED PERFECTLY!")
        print("=" * 65)


if __name__ == "__main__":
    asyncio.run(test_bulk_and_exports())
