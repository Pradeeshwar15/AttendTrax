"""
Automated Test Suite: System Hardening, Danger Zone Security & System Health
Verifies:
1. GET /admin/executive/system-health returns database telemetry, latency, table counts, and integrity.
2. POST /admin/executive/factory-reset enforces confirmation phrase 'RESET ATTENDANCE' and password verification.
3. POST /admin/executive/purge-academic-cohorts enforces confirmation phrase 'PURGE INSTITUTION' and password verification.
4. Tamper-evident AuditLog records are generated with auth confirmation.
"""
import asyncio
from fastapi import HTTPException
from database import get_session_factory
from models import User, AuditLog
from routers.executive_router import (
    SecurityActionRequest,
    get_system_health,
    executive_factory_default_reset,
    executive_purge_academic_cohorts
)
from sqlalchemy import select

TEST_PRINCIPAL_USER = {
    "UserID": 1,
    "Username": "principal",
    "role": "SUPER_ADMIN",
    "sub": "principal"
}

VALID_PASSWORD = "Principal@2026"
WRONG_PASSWORD = "IncorrectPassword999!"

async def run_tests():
    print("=" * 70)
    print("STARTING DANGER ZONE SECURITY & SYSTEM HEALTH TESTS")
    print("=" * 70)

    session_factory = get_session_factory()
    async with session_factory() as db:
        # ── TEST 1: GET /admin/executive/system-health ──────────────────────
        print("\n--- 1. Testing GET /admin/executive/system-health ---")
        health = await get_system_health(current_user=TEST_PRINCIPAL_USER, db=db)
        assert health["status"] == "healthy", f"Expected healthy status, got {health['status']}"
        assert health["database"]["connected"] is True, "Database should report connected"
        assert health["database"]["latency_ms"] >= 0, "Latency must be a positive number"
        assert "departments" in health["table_counts"], "Table counts must include departments"
        assert "students" in health["table_counts"], "Table counts must include students"
        assert health["integrity"]["is_clean"] is True, "Database integrity should be clean"
        print(f"  ✓ Database Connected: {health['database']['provider']} (Latency: {health['database']['latency_ms']} ms)")
        print(f"  ✓ Integrity Check: Clean ({health['integrity']['orphan_students']} orphan students, {health['integrity']['orphan_attendance_records']} orphan attendance records)")
        print(f"  ✓ Table counts verified ({len(health['table_counts'])} tables tracked)")

        # ── TEST 2: POST /admin/executive/factory-reset Validations ─────────
        print("\n--- 2. Testing Factory Reset Security Gate ---")
        
        # Case A: Incorrect Confirmation Phrase
        try:
            await executive_factory_default_reset(
                payload=SecurityActionRequest(password=VALID_PASSWORD, confirm_phrase="WRONG PHRASE"),
                current_user=TEST_PRINCIPAL_USER,
                db=db
            )
            assert False, "Should have raised HTTPException for wrong confirmation phrase"
        except HTTPException as e:
            assert e.status_code == 400, f"Expected 400, got {e.status_code}"
            print(f"  ✓ Case A passed: Rejected wrong phrase with HTTP {e.status_code} ({e.detail})")

        # Case B: Incorrect Password
        try:
            await executive_factory_default_reset(
                payload=SecurityActionRequest(password=WRONG_PASSWORD, confirm_phrase="RESET ATTENDANCE"),
                current_user=TEST_PRINCIPAL_USER,
                db=db
            )
            assert False, "Should have raised HTTPException for incorrect password"
        except HTTPException as e:
            assert e.status_code == 401, f"Expected 401, got {e.status_code}"
            print(f"  ✓ Case B passed: Rejected incorrect password with HTTP {e.status_code} ({e.detail})")

        # Case C: Valid Password and Valid Phrase
        res = await executive_factory_default_reset(
            payload=SecurityActionRequest(password=VALID_PASSWORD, confirm_phrase="RESET ATTENDANCE"),
            current_user=TEST_PRINCIPAL_USER,
            db=db
        )
        assert res["status"] == "success", f"Expected success, got {res}"
        print(f"  ✓ Case C passed: Factory Reset executed successfully ({res['message']})")

        # Verify Audit Log
        audit_res = await db.execute(
            select(AuditLog)
            .where(AuditLog.action == "FACTORY_RESET")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        latest_audit = audit_res.scalars().first()
        assert latest_audit is not None, "AuditLog record must be created"
        assert latest_audit.old_values.get("auth_verified") is True, "AuditLog must record auth_verified=True"
        print(f"  ✓ AuditLog Entry Verified: Action='{latest_audit.action}', AuthVerified={latest_audit.old_values.get('auth_verified')}")

        # ── TEST 3: POST /admin/executive/purge-academic-cohorts Validations ─
        print("\n--- 3. Testing Institutional Purge Security Gate ---")
        
        # Case A: Incorrect Confirmation Phrase
        try:
            await executive_purge_academic_cohorts(
                payload=SecurityActionRequest(password=VALID_PASSWORD, confirm_phrase="INVALID PURGE"),
                current_user=TEST_PRINCIPAL_USER,
                db=db
            )
            assert False, "Should have raised HTTPException for wrong confirmation phrase"
        except HTTPException as e:
            assert e.status_code == 400, f"Expected 400, got {e.status_code}"
            print(f"  ✓ Case A passed: Rejected wrong phrase with HTTP {e.status_code} ({e.detail})")

        # Case B: Incorrect Password
        try:
            await executive_purge_academic_cohorts(
                payload=SecurityActionRequest(password=WRONG_PASSWORD, confirm_phrase="PURGE INSTITUTION"),
                current_user=TEST_PRINCIPAL_USER,
                db=db
            )
            assert False, "Should have raised HTTPException for incorrect password"
        except HTTPException as e:
            assert e.status_code == 401, f"Expected 401, got {e.status_code}"
            print(f"  ✓ Case B passed: Rejected incorrect password with HTTP {e.status_code} ({e.detail})")

        # Case C: Valid Password and Valid Phrase
        res_purge = await executive_purge_academic_cohorts(
            payload=SecurityActionRequest(password=VALID_PASSWORD, confirm_phrase="PURGE INSTITUTION"),
            current_user=TEST_PRINCIPAL_USER,
            db=db
        )
        assert res_purge["status"] == "success", f"Expected success, got {res_purge}"
        print(f"  ✓ Case C passed: Cohort Purge executed successfully ({res_purge['message']})")

        # Verify Audit Log
        audit_res2 = await db.execute(
            select(AuditLog)
            .where(AuditLog.action == "PURGE_ACADEMIC_COHORTS")
            .order_by(AuditLog.created_at.desc())
            .limit(1)
        )
        latest_audit2 = audit_res2.scalars().first()
        assert latest_audit2 is not None, "AuditLog record must be created"
        assert latest_audit2.old_values.get("auth_verified") is True, "AuditLog must record auth_verified=True"
        print(f"  ✓ AuditLog Entry Verified: Action='{latest_audit2.action}', AuthVerified={latest_audit2.old_values.get('auth_verified')}")

    print("\n" + "=" * 70)
    print("ALL DANGER ZONE SECURITY & HEALTH TESTS PASSED (100% SUCCESS)")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_tests())
