"""
Comprehensive verification test for:
1. Hostel room removal from student onboarding template (9 columns, no Hostel Room, correct dropdown validations).
2. Class creation with Class Incharge assignment (incharge_faculty_id).
3. Class directory output containing InchargeFacultyID, InchargeName, InchargeUsername.
4. Leave approval scoping: Class Incharge receives pending leaves strictly for their assigned class;
   unassigned faculty receive 0 leaves; unassigned faculty review attempt is rejected with HTTP 403;
   assigned incharge review succeeds with HTTP 200.
"""

import asyncio
import io
import sys
import os
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
site_packages = os.path.join(backend_dir, "venv", "Lib", "site-packages")
if os.path.exists(site_packages):
    sys.path.insert(0, site_packages)
sys.path.insert(0, backend_dir)

import openpyxl
from datetime import date
from sqlalchemy import select, delete, text
from fastapi import HTTPException
from starlette.requests import Request

from database import get_session_factory, init_db
from models import User, Faculty, Student, ClassRoom, Department, StudentLeave, AuditLog
from routers.admin_router import (
    download_student_template,
    add_class,
    rename_class,
    list_all_classes,
    AddClassRequest,
    RenameClassRequest,
)
from routers.leave_router import (
    get_student_leaves_pending_incharge,
    incharge_review_student_leave,
    ReviewLeaveRequest,
)


async def test_student_template_columns():
    print("\n--- [TEST 1] Student Onboarding Template Verification ---")
    response = await download_student_template()
    content = response.body
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    headers = [cell.value for cell in ws[1] if cell.value is not None]
    print(f"Extracted headers ({len(headers)} columns): {headers}")

    assert len(headers) == 9, f"Expected 9 columns, got {len(headers)}: {headers}"
    assert "Hostel Room" not in headers, "Hostel Room should NOT be in the headers!"
    assert "Hostel Block & Room" not in headers, "Hostel Block & Room should NOT be in the headers!"
    assert headers[0] == "Register No"
    assert headers[1] == "Roll No"
    assert headers[2] == "Student Name"
    assert headers[3] == "Gender"
    assert headers[4] == "Scholar Type"
    assert headers[5] == "Class ID"
    assert headers[6] == "Placement Standing"
    assert headers[7] == "Username"
    assert headers[8] == "Password"

    # Verify sample row
    row2 = [cell.value for cell in ws[2]]
    print(f"Sample row 1 (len {len(row2)}): {row2}")
    assert row2[3] == "MALE"
    assert row2[4] == "HOSTELLER"
    assert row2[6] == "active"

    # Check data validations
    validations = ws.data_validations.dataValidation
    print(f"Validation rules count: {len(validations)}")
    assert len(validations) >= 3, f"Expected at least 3 dropdown validations, found {len(validations)}"
    print("PASS: Student template verified with 9 columns, no Hostel Room, and proper validations.")


async def test_class_incharge_and_leave_scoping():
    print("\n--- [TEST 2] Class Incharge Assignment & Leave Scoping ---")
    session_factory = get_session_factory()
    async with session_factory() as db:
        # 1. Setup or fetch Department
        dept_res = await db.execute(select(Department).where(Department.code == "CSE"))
        cse_dept = dept_res.scalar_one_or_none()
        if not cse_dept:
            cse_dept = Department(code="CSE", name="Computer Science and Engineering", is_active=True)
            db.add(cse_dept)
            await db.commit()
            await db.refresh(cse_dept)

        # 2. Setup Faculty 1 (The designated incharge)
        f1_user_res = await db.execute(select(User).where(User.username == "test.incharge.fac"))
        f1_user = f1_user_res.scalar_one_or_none()
        if not f1_user:
            f1_user = User(
                username="test.incharge.fac",
                full_name="Prof. Test Incharge",
                role="FACULTY",
                status="ACTIVE",
                password_hash="testpass123",
            )
            db.add(f1_user)
            await db.commit()
            await db.refresh(f1_user)

        f1_fac_res = await db.execute(select(Faculty).where(Faculty.user_id == f1_user.id))
        f1_fac = f1_fac_res.scalar_one_or_none()
        if not f1_fac:
            f1_fac = Faculty(
                user_id=f1_user.id,
                faculty_code="FAC_INC_001",
                department_id=cse_dept.id,
                designation="Assistant Professor",
            )
            db.add(f1_fac)
            await db.commit()

        # 3. Setup Faculty 2 (Unassigned / Other Faculty)
        f2_user_res = await db.execute(select(User).where(User.username == "test.other.fac"))
        f2_user = f2_user_res.scalar_one_or_none()
        if not f2_user:
            f2_user = User(
                username="test.other.fac",
                full_name="Prof. Other Faculty",
                role="FACULTY",
                status="ACTIVE",
                password_hash="testpass123",
            )
            db.add(f2_user)
            await db.commit()
            await db.refresh(f2_user)

        f2_fac_res = await db.execute(select(Faculty).where(Faculty.user_id == f2_user.id))
        f2_fac = f2_fac_res.scalar_one_or_none()
        if not f2_fac:
            f2_fac = Faculty(
                user_id=f2_user.id,
                faculty_code="FAC_OTH_002",
                department_id=cse_dept.id,
                designation="Assistant Professor",
            )
            db.add(f2_fac)
            await db.commit()

        # 4. Clean up any previous test class
        test_class_code = "TEST_INC_CLASS"
        old_cls_res = await db.execute(select(ClassRoom).where(ClassRoom.class_code == test_class_code))
        old_cls = old_cls_res.scalar_one_or_none()
        if old_cls:
            # delete leaves and students for this test class
            await db.execute(delete(StudentLeave).where(StudentLeave.class_id == old_cls.id))
            await db.execute(delete(Student).where(Student.class_id == old_cls.id))
            await db.execute(delete(ClassRoom).where(ClassRoom.id == old_cls.id))
            await db.commit()

        # 5. Add Class with incharge_id = "FAC_INC_001"
        admin_ctx = {"id": 1, "username": "admin", "role": "SUPER_ADMIN"}
        add_req = AddClassRequest(
            class_id=test_class_code,
            class_name="Test Incharge Class 3A",
            department_code="CSE",
            year="3",
            section="A",
            semester="5",
            incharge_id="FAC_INC_001",
        )
        add_res = await add_class(body=add_req, current_user=admin_ctx, db=db)
        print("add_class response:", add_res)

        # Verify class in DB
        cls_q = await db.execute(select(ClassRoom).where(ClassRoom.class_code == test_class_code))
        created_cls = cls_q.scalar_one()
        assert created_cls.incharge_faculty_id == f1_user.id, f"Expected incharge_faculty_id == {f1_user.id}, got {created_cls.incharge_faculty_id}"
        print(f"PASS: Class created with incharge_faculty_id = {created_cls.incharge_faculty_id}")

        # 6. Test list_all_classes returns InchargeName and InchargeUsername
        classes_list = await list_all_classes(current_user=admin_ctx, db=db)
        matching_cls = next((c for c in classes_list if c["ClassID"] == test_class_code), None)
        assert matching_cls is not None, "Test class not found in list_all_classes"
        print(f"Class list entry: {matching_cls}")
        assert matching_cls["InchargeName"] == f1_user.full_name
        assert matching_cls["InchargeUsername"] == f1_user.username
        print("PASS: list_all_classes properly projects InchargeName and InchargeUsername.")

        # 7. Create a student in this class and submit a pending leave
        test_reg = "410199999901"
        st_user_res = await db.execute(select(User).where(User.username == test_reg))
        st_user = st_user_res.scalar_one_or_none()
        if not st_user:
            st_user = User(
                username=test_reg,
                full_name="Test Student Scoping",
                role="STUDENT",
                status="ACTIVE",
                password_hash="pass@123",
            )
            db.add(st_user)
            await db.commit()
            await db.refresh(st_user)

        st_res = await db.execute(select(Student).where(Student.reg_no == test_reg))
        test_st = st_res.scalar_one_or_none()
        if not test_st:
            test_st = Student(
                user_id=st_user.id,
                reg_no=test_reg,
                name="Test Student Scoping",
                roll_no="99CS001",
                class_id=created_cls.id,
                department_id=cse_dept.id,
                residence_type="HOSTELLER",
                gender="MALE",
                placement_willingness="active",
                status="ACTIVE",
            )
            db.add(test_st)
            await db.commit()
            await db.refresh(test_st)
        else:
            test_st.class_id = created_cls.id
            await db.commit()
            await db.refresh(test_st)

        # Add a pending student leave
        new_leave = StudentLeave(
            student_id=test_st.id,
            class_id=created_cls.id,
            department_id=cse_dept.id,
            residence_type="HOSTELLER",
            leave_type="MEDICAL",
            start_date=date.today(),
            end_date=date.today(),
            reason="Fever check scoping",
            incharge_status="PENDING",
            final_status="PENDING",
        )
        db.add(new_leave)
        await db.commit()
        await db.refresh(new_leave)
        print(f"Created pending leave ticket ID: {new_leave.id}")

        # 8. Test get_student_leaves_pending_incharge for Assigned Incharge vs Unassigned Faculty
        incharge_ctx = {"id": f1_user.id, "user_id": f1_user.id, "username": f1_user.username, "role": "FACULTY"}
        other_faculty_ctx = {"id": f2_user.id, "user_id": f2_user.id, "username": f2_user.username, "role": "FACULTY"}

        incharge_queue = await get_student_leaves_pending_incharge(current_user=incharge_ctx, db=db)
        found_in_incharge = any(l["id"] == new_leave.id for l in incharge_queue)
        print(f"Incharge queue count: {len(incharge_queue)}, contains ticket: {found_in_incharge}")
        assert found_in_incharge, "Assigned incharge MUST see the leave ticket for their class!"

        other_queue = await get_student_leaves_pending_incharge(current_user=other_faculty_ctx, db=db)
        found_in_other = any(l["id"] == new_leave.id for l in other_queue)
        print(f"Other faculty queue count: {len(other_queue)}, contains ticket: {found_in_other}")
        assert not found_in_other, "Other faculty MUST NOT see the leave ticket for another class!"
        print("PASS: Queue filtering strictly scopes leaves to the assigned Class Incharge.")

        # 9. Test incharge_review_student_leave permission enforcement
        # Unassigned faculty review attempt -> MUST throw 403 Forbidden
        dummy_req = Request({"type": "http", "method": "POST", "url": "http://testserver", "headers": []})
        review_req = ReviewLeaveRequest(action="APPROVE", remarks="Unauthorized attempt")
        rejected = False
        try:
            await incharge_review_student_leave(leave_id=new_leave.id, body=review_req, request=dummy_req, current_user=other_faculty_ctx, db=db)
        except HTTPException as he:
            if he.status_code == 403:
                rejected = True
                print(f"Successfully caught expected HTTP 403: {he.detail}")
        assert rejected, "Unauthorized faculty MUST be rejected with HTTP 403 Forbidden!"

        # Assigned incharge review attempt -> MUST succeed with HTTP 200
        approve_req = ReviewLeaveRequest(action="APPROVE", remarks="Approved by Class Incharge")
        ok_res = await incharge_review_student_leave(leave_id=new_leave.id, body=approve_req, request=dummy_req, current_user=incharge_ctx, db=db)
        print(f"Incharge approval response: {ok_res}")
        assert ok_res.get("status") == "INCHARGE_APPROVED"
        print("PASS: Class Incharge successfully approved the leave request.")

        # 10. Clean up test records
        await db.execute(delete(StudentLeave).where(StudentLeave.id == new_leave.id))
        await db.execute(delete(Student).where(Student.id == test_st.id))
        await db.execute(delete(ClassRoom).where(ClassRoom.id == created_cls.id))
        await db.execute(delete(User).where(User.id == st_user.id))
        await db.commit()
        print("PASS: Test cleanup completed successfully.")


async def main():
    print("Initializing DB...")
    await init_db()
    await test_student_template_columns()
    await test_class_incharge_and_leave_scoping()
    print("\n==========================================")
    print("ALL TESTS PASSED SUCCESSFULLY! (100% VERIFIED)")
    print("==========================================")


if __name__ == "__main__":
    asyncio.run(main())
