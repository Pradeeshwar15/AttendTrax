# Ralph Loop Progress Tracker

## Goal
Execute a complete institutional reset clearing all student profiles, student user accounts, past attendance sessions & records, student leaves, and class records across PostgreSQL/SQLite and Google Sheets (while preserving departments, faculty, and administrative accounts), establish synchronous dual-write manual class creation scoped to department HODs, and enable multi-setup bulk student onboarding.

## Plan Reference
`C:\Users\prade\OneDrive\Desktop\Cur Dev\institutional_reset_and_cohort_onboarding_plan.md`

## Current Status
- [x] Initialized Ralph progress tracker for Institutional Reset & Departmental Cohort Onboarding
- [x] Implementation plan approved by user
- [x] **Phase 1: Sheets & Backend Reset Functions (`sheets.py`, `executive_router.py`, `scripts/reset_institutional_cohorts.py`)**
  - Added `clear_all_students_sheet()` and `clear_all_classes_sheet()` to `backend/sheets.py`.
  - Added `POST /admin/executive/purge-academic-cohorts` in `backend/routers/executive_router.py`.
  - Created `backend/scripts/reset_institutional_cohorts.py` CLI utility.
  - Executed reset and verified 0 students, 0 classes, 0 attendance records, while preserving all 10 departments, 32 faculty, 10 HODs, and leadership.
- [x] **Phase 2: Department HOD Manual Class Creation & Dual-Write (`admin_router.py`, `admin.html`)**
  - Updated `POST /admin/classes`: Auto-scopes to HOD's department, inserts into SQL `ClassRoom` and Google Sheets `Classes`.
  - Updated `GET /admin/classes`: Fetches from SQL `ClassRoom` joined with `Department` and merges with Sheets.
  - Updated `DELETE /admin/classes/{class_id}`: Enforces department sandbox, updates SQL and Sheets.
  - Updated `frontend/admin.html` "➕ Add Class" modal: Locks department for HODs, shows dropdown for Super Admin.
- [x] **Phase 3: Multi-Setup Student Ingestion & Dual-Write (`admin_router.py`, `admin.html`)**
  - Updated `POST /admin/import/students` and `POST /admin/students`: Allows HODs and Super Admin.
  - Performs synchronous batch insert into SQL (`User` role='STUDENT' and `Student` table) and Google Sheets.
  - Made "Bulk Setup" accessible to both Super Admin and HODs in `admin.html`.
- [x] **Phase 4: Automated Verification & Walkthrough Artifact**
  - Ran test suite `backend/tests/test_e2e.py` validating clean reset, HOD class creation, and bulk student onboarding (100% pass rate).
  - Cleaned test cohorts with final reset script run (0 classes, 0 students, 0 attendance records).
  - Documented complete walkthrough in `walkthrough.md`.

## Iteration Log
- **Iteration 1**: Plan approved by user.
- **Iteration 2**: Completed Phase 1 (Sheets & Backend reset functions, CLI script).
- **Iteration 3**: Completed Phase 2 (Department HOD manual class creation and sandboxing).
- **Iteration 4**: Completed Phase 3 (Multi-setup bulk student onboarding and SQL/Sheets dual-write).
- **Iteration 5**: Completed Phase 4 (End-to-end verification passing 100%, final clean-slate reset executed, walkthrough artifact generated).
