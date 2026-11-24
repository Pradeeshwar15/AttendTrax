# Ralph Loop Progress Tracker: Dynamic Department Subjects & Placement Attendance

**Active Goal**: Replace hardcoded placement subject dropdowns with dynamic department-scoped subjects in Supabase, require subject selection before loading students in faculty attendance, and provide first-class subject management for all departments (including Placement).

## Status Checklist
- [x] Research existing subject models, admin endpoints, and faculty dropdowns
- [x] Create comprehensive implementation plan artifact (`department_subjects_and_dynamic_placement_attendance_plan.md`)
- [x] User review & approval of the implementation plan
- [x] Step 1: Update `backend/routers/admin_router.py` for full Placement department subject management
- [x] Step 2: Update `backend/routers/faculty_router.py` to dynamically return department-scoped subjects for Placement vs Academic faculty
- [x] Step 3: Update `frontend/admin.html` Subjects tab with department filter and Placement option
- [x] Step 4: Update `frontend/faculty.html` to dynamically render department subjects and enforce selection before loading students
- [x] Step 5: Automated test verification (`backend/scripts/test_dynamic_department_subjects.py`)
- [x] Step 6: Restart servers, verify end-to-end, and push to GitHub

## Completed Verification
- `test_dynamic_department_subjects.py`: PASSED (Step 1-6 verified)
- `test_performance_and_willingness.py`: PASSED
- `test_attendance_extensions.py`: PASSED
- `test_placement_attendance_sandbox.py`: PASSED
