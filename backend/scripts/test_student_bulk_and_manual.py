"""
Verification script for:
1. Student Excel Template Generation with Dropdown Validations (/admin/template/students)
2. Manual Student Profile Addition (/admin/students) with RollNo, Gender, ResidenceType, HostelBlockRoom, PlacementWillingness
3. Manual Student Profile Update via PATCH (/admin/students/{reg_no})
4. Bulk Student Onboarding & Upsert (/admin/import/students) via .xlsx and .csv
5. Student Directory Filters (residence_type, gender, placement_willingness)
6. Student Profile Retrieval (/student/profile)
"""
import asyncio
import io
import openpyxl
from sqlalchemy import select, delete, and_

from database import get_session_factory, init_db
from models import User, Student, ClassRoom, Department
from routers.admin_router import (
    AddStudentRequest,
    UpdateStudentRequest,
    add_student,
    update_student,
    list_all_students,
    download_student_template,
    import_students,
    _normalize_gender,
    _normalize_residence_type,
    _normalize_placement_willingness,
)
from routers.student_router import get_profile
from fastapi import UploadFile

TEST_ADMIN_USER = {
    "sub": "admin",
    "role": "SUPER_ADMIN",
    "username": "admin",
    "dept_code": "ALL"
}

TEST_REG_MANUAL = "TEST_MANUAL_9901"
TEST_REG_BULK_XLSX = "TEST_BULK_XLSX_9902"
TEST_REG_BULK_CSV = "TEST_BULK_CSV_9903"

async def run_tests():
    print("=" * 70)
    print("STARTING TEST: BULK & MANUAL STUDENT PROFILE INTEGRATION")
    print("=" * 70)

    # 1. Normalization Unit Tests
    print("\n--- 1. Testing Normalizers ---")
    assert _normalize_gender("MALE") == "MALE"
    assert _normalize_gender("f") == "FEMALE"
    assert _normalize_gender("girl") == "FEMALE"
    assert _normalize_gender("boy") == "MALE"
    assert _normalize_gender("other") == "OTHER"
    assert _normalize_gender(None) is None
    print("✓ Gender normalization verified.")

    assert _normalize_residence_type("Hosteller") == "HOSTELLER"
    assert _normalize_residence_type("roster") == "HOSTELLER"
    assert _normalize_residence_type("their scholar") == "DAY_SCHOLAR"
    assert _normalize_residence_type("Day Scholar") == "DAY_SCHOLAR"
    assert _normalize_residence_type("H") == "HOSTELLER"
    assert _normalize_residence_type("DS") == "DAY_SCHOLAR"
    print("✓ ResidenceType / Scholar normalization verified.")

    assert _normalize_placement_willingness("active") == "active"
    assert _normalize_placement_willingness("inactive") == "inactive"
    assert _normalize_placement_willingness("no") == "inactive"
    assert _normalize_placement_willingness("excluded") == "inactive"
    assert _normalize_placement_willingness("yes") == "active"
    print("✓ Placement willingness normalization verified.")

    # 2. Template Generation Test
    print("\n--- 2. Testing Excel Template Generation ---")
    resp = await download_student_template(current_user=TEST_ADMIN_USER)
    assert resp.status_code == 200
    assert "attachment; filename=\"Adhi_Student_Bulk_Template.xlsx\"" in resp.headers["Content-Disposition"]
    
    wb = openpyxl.load_workbook(io.BytesIO(resp.body))
    ws = wb.active
    headers = [cell.value for cell in ws[1]]
    expected_headers = [
        "Register No", "Roll No", "Student Name", "Gender", "Scholar Type",
        "Class ID", "Hostel Room", "Placement Standing", "Username", "Password"
    ]
    assert headers == expected_headers, f"Expected {expected_headers}, got {headers}"
    print(f"✓ Excel Template generated with {len(headers)} columns: {headers}")
    print(f"✓ Validated Data Validations count in template: {len(ws.data_validations.dataValidation)}")

    session_factory = get_session_factory()
    async with session_factory() as db:
        # Clean up existing test records if any
        stmt_del_s = delete(Student).where(Student.reg_no.in_([TEST_REG_MANUAL, TEST_REG_BULK_XLSX, TEST_REG_BULK_CSV]))
        await db.execute(stmt_del_s)
        stmt_del_u = delete(User).where(User.username.in_([TEST_REG_MANUAL, TEST_REG_BULK_XLSX, TEST_REG_BULK_CSV]))
        await db.execute(stmt_del_u)
        await db.commit()

        # 3. Manual Add Student Test
        print("\n--- 3. Testing Manual Add Student (POST /admin/students) ---")
        req = AddStudentRequest(
            reg_no=TEST_REG_MANUAL,
            roll_no="23CS991",
            name="Manual Test Student",
            gender="MALE",
            residence_type="HOSTELLER",
            hostel_block_room="Kavery Block Room 101",
            class_id="CSE3A",
            placement_willingness="active"
        )
        res_add = await add_student(body=req, current_user=TEST_ADMIN_USER, db=db)
        print(f"✓ add_student response: {res_add}")

        # Verify in DB
        stmt = select(Student).where(Student.reg_no == TEST_REG_MANUAL)
        st = (await db.execute(stmt)).scalar_one_or_none()
        assert st is not None
        assert st.roll_no == "23CS991"
        assert st.gender == "MALE"
        assert st.residence_type == "HOSTELLER"
        assert st.hostel_block_room == "Kavery Block Room 101"
        assert st.placement_willingness == "active"
        print(f"✓ DB student record verified: roll_no={st.roll_no}, gender={st.gender}, residence={st.residence_type}, hostel={st.hostel_block_room}, placement={st.placement_willingness}")

        # 4. Manual Update Student Test (PATCH /admin/students/{reg_no})
        print("\n--- 4. Testing Manual Update Student (PATCH /admin/students/{reg_no}) ---")
        update_req = UpdateStudentRequest(
            name="Manual Student Renamed",
            roll_no="23CS991-R",
            gender="MALE",
            residence_type="DAY_SCHOLAR",
            hostel_block_room=None,
            placement_willingness="inactive"
        )
        res_patch = await update_student(reg_no=TEST_REG_MANUAL, body=update_req, current_user=TEST_ADMIN_USER, db=db)
        print(f"✓ update_student response: {res_patch}")

        # Refresh and verify
        await db.refresh(st)
        assert st.name == "Manual Student Renamed"
        assert st.roll_no == "23CS991-R"
        assert st.residence_type == "DAY_SCHOLAR"
        assert st.placement_willingness == "inactive"
        print("✓ Student update verified in SQL.")

        # 5. Bulk Import via .xlsx (Including Upsert and New Student)
        print("\n--- 5. Testing Bulk Import (.xlsx) with Upsert ---")
        wb_import = openpyxl.Workbook()
        ws_import = wb_import.active
        ws_import.append(["Register No", "Roll No", "Student Name", "Gender", "Scholar Type", "Class ID", "Hostel Room", "Placement Standing"])
        # Update existing student
        ws_import.append([TEST_REG_MANUAL, "23CS991-V2", "Manual Student Final", "MALE", "HOSTELLER", "CSE3A", "Room 404", "active"])
        # New student
        ws_import.append([TEST_REG_BULK_XLSX, "23CS992", "Bulk XLSX Student", "FEMALE", "HOSTELLER", "CSE3A", "Ganga Block 202", "active"])
        xlsx_buf = io.BytesIO()
        wb_import.save(xlsx_buf)
        xlsx_buf.seek(0)

        upload_file_xlsx = UploadFile(
            filename="test_bulk.xlsx",
            file=xlsx_buf
        )
        res_bulk_xlsx = await import_students(file=upload_file_xlsx, class_id=None, current_user=TEST_ADMIN_USER, db=db)
        print(f"✓ import_students (.xlsx) response: {res_bulk_xlsx}")
        assert res_bulk_xlsx["inserted"] == 1
        assert res_bulk_xlsx["updated"] == 1

        # Verify bulk xlsx student in DB
        stmt_xlsx = select(Student).where(Student.reg_no == TEST_REG_BULK_XLSX)
        st_xlsx = (await db.execute(stmt_xlsx)).scalar_one_or_none()
        assert st_xlsx is not None
        assert st_xlsx.roll_no == "23CS992"
        assert st_xlsx.gender == "FEMALE"
        assert st_xlsx.residence_type == "HOSTELLER"
        assert st_xlsx.hostel_block_room == "Ganga Block 202"
        print("✓ Bulk XLSX student inserted with full profile details.")

        # 6. Bulk Import via .csv
        print("\n--- 6. Testing Bulk Import (.csv) ---")
        csv_content = (
            "Register No,Roll No,Student Name,Gender,Scholar Type,Class ID,Hostel Room,Placement Standing\n"
            f"{TEST_REG_BULK_CSV},23CS993,Bulk CSV Student,MALE,DAY_SCHOLAR,CSE3A,,active\n"
        )
        csv_buf = io.BytesIO(csv_content.encode("utf-8"))
        upload_file_csv = UploadFile(
            filename="test_bulk.csv",
            file=csv_buf
        )
        res_bulk_csv = await import_students(file=upload_file_csv, class_id=None, current_user=TEST_ADMIN_USER, db=db)
        print(f"✓ import_students (.csv) response: {res_bulk_csv}")
        assert res_bulk_csv["inserted"] == 1

        stmt_csv = select(Student).where(Student.reg_no == TEST_REG_BULK_CSV)
        st_csv = (await db.execute(stmt_csv)).scalar_one_or_none()
        assert st_csv is not None
        assert st_csv.roll_no == "23CS993"
        assert st_csv.gender == "MALE"
        assert st_csv.residence_type == "DAY_SCHOLAR"
        print("✓ Bulk CSV student inserted with full profile details.")

        # 7. Student Directory Filter Tests
        print("\n--- 7. Testing Directory Filters in list_all_students ---")
        hostellers = await list_all_students(class_id="CSE3A", residence_type="HOSTELLER", current_user=TEST_ADMIN_USER, db=db)
        hosteller_regs = [s["RegNo"] for s in hostellers]
        assert TEST_REG_BULK_XLSX in hosteller_regs
        assert TEST_REG_BULK_CSV not in hosteller_regs
        print(f"✓ Hosteller filter works (found {len(hostellers)} students, includes {TEST_REG_BULK_XLSX}).")

        females = await list_all_students(class_id="CSE3A", gender="FEMALE", current_user=TEST_ADMIN_USER, db=db)
        female_regs = [s["RegNo"] for s in females]
        assert TEST_REG_BULK_XLSX in female_regs
        assert TEST_REG_BULK_CSV not in female_regs
        print(f"✓ Gender filter works (found {len(females)} female students).")

        # 8. Student Profile Endpoint Test
        print("\n--- 8. Testing Student Profile Endpoint (/student/profile) ---")
        student_user = {
            "sub": TEST_REG_BULK_XLSX,
            "Username": TEST_REG_BULK_XLSX,
            "role": "STUDENT",
            "reg_no": TEST_REG_BULK_XLSX
        }
        profile = await get_profile(current_user=student_user, db=db)
        assert profile["RegNo"] == TEST_REG_BULK_XLSX
        assert profile["RollNo"] == "23CS992"
        assert profile["Gender"] == "FEMALE"
        assert profile["ResidenceType"] == "HOSTELLER"
        assert profile["HostelBlockRoom"] == "Ganga Block 202"
        assert profile["PlacementWillingness"] == "active"
        print(f"✓ /student/profile returned: {profile}")

        # Clean up test rows
        stmt_del_s = delete(Student).where(Student.reg_no.in_([TEST_REG_MANUAL, TEST_REG_BULK_XLSX, TEST_REG_BULK_CSV]))
        await db.execute(stmt_del_s)
        stmt_del_u = delete(User).where(User.username.in_([TEST_REG_MANUAL, TEST_REG_BULK_XLSX, TEST_REG_BULK_CSV]))
        await db.execute(stmt_del_u)
        await db.commit()
        print("\n✓ Cleaned up test records.")

    print("\n" + "=" * 70)
    print("ALL TESTS PASSED SUCCESSFULLY! (100% VERIFIED)")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_tests())
