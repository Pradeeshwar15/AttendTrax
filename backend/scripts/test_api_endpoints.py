# =============================================================================
# backend/scripts/test_api_endpoints.py
# Verify API HTTP endpoints using TestClient
# =============================================================================
import os
import sys

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
import httpx
from main import app
from auth import create_access_token

async def test_endpoints():
    print("\n--- Testing API Endpoints via AsyncClient ---")

    from database import get_session_factory
    from models import User
    from sqlalchemy import select

    async with get_session_factory()() as session:
        users = (await session.execute(select(User))).scalars().all()
        admin_u = next((u for u in users if u.role == "SUPER_ADMIN"), None)
        plc_u = next((u for u in users if "placement" in (u.username or "").lower()), None)
        acad_u = next((u for u in users if u.role in ("FACULTY", "DEPT_ADMIN") and "placement" not in (u.username or "").lower()), None)

    print(f"Users resolved: admin={admin_u.username if admin_u else None}, plc={plc_u.username if plc_u else None}, acad={acad_u.username if acad_u else None}")

    # 1. Super Admin Token
    admin_token = create_access_token(data={"sub": admin_u.username, "role": admin_u.role, "department": "CSE"})
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # 2. Placement Token
    plc_sub = plc_u.username if plc_u else "hod.placement"
    plc_token = create_access_token(data={"sub": plc_sub, "role": plc_u.role if plc_u else "DEPT_ADMIN", "department": "PLACEMENT", "department_code": "PLACEMENT"})
    plc_headers = {"Authorization": f"Bearer {plc_token}"}

    # 3. Academic Faculty Token
    acad_sub = acad_u.username if acad_u else "hod.cse"
    acad_token = create_access_token(data={"sub": acad_sub, "role": acad_u.role if acad_u else "DEPT_ADMIN", "department": "CSE", "department_code": "CSE"})
    acad_headers = {"Authorization": f"Bearer {acad_token}"}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # Test GET /admin/attendance/status-students
        res = await client.get("/admin/attendance/status-students?date=23-11-2026&status=A", headers=admin_headers)
        print(f"Status Students (A): status={res.status_code}, count={len(res.json()) if res.status_code == 200 else res.text}")
        assert res.status_code == 200

        # Test GET /admin/attendance/status-students/export (CSV)
        res_csv = await client.get("/admin/attendance/status-students/export?date=23-11-2026&status=A", headers=admin_headers)
        print(f"Status Students CSV Export: status={res_csv.status_code}, length={len(res_csv.text)}")
        assert res_csv.status_code == 200
        assert "S.No,Roll No,Student Name,Class,Department" in res_csv.text

        # Test PATCH /admin/students/{reg_no}/placement-willingness
        res_patch = await client.patch(
            "/admin/students/410125104001/placement-willingness",
            json={"placement_willingness": "inactive"},
            headers=admin_headers
        )
        print(f"Patch Willingness (inactive): status={res_patch.status_code}, res={res_patch.json()}")
        assert res_patch.status_code == 200

        # Test Placement faculty roster excludes 410125104001
        res_plc_roster = await client.get("/faculty/classes/CSE2A/students", headers=plc_headers)
        print(f"res_plc_roster status={res_plc_roster.status_code}, type={type(res_plc_roster.json())}, data={res_plc_roster.json()[:3] if isinstance(res_plc_roster.json(), list) else res_plc_roster.json()}")
        plc_regs = [s["reg_no"] for s in res_plc_roster.json()]
        assert "410125104001" not in plc_regs, "410125104001 must NOT be in placement roster when inactive"
        print(f"✓ Verified 410125104001 is excluded from placement roster (total willing: {len(plc_regs)})")

        # Test Academic faculty roster includes 410125104001
        res_acad_roster = await client.get("/faculty/classes/CSE2A/students", headers=acad_headers)
        acad_regs = [s["reg_no"] for s in res_acad_roster.json()]
        assert "410125104001" in acad_regs, "410125104001 MUST be in academic roster"
        print(f"✓ Verified 410125104001 is included in academic roster (total: {len(acad_regs)})")

        # Restore student willingness
        res_restore = await client.patch(
            "/admin/students/410125104001/placement-willingness",
            json={"placement_willingness": "active"},
            headers=admin_headers
        )
        assert res_restore.status_code == 200
        print("✓ Restored 410125104001 to active placement willingness")

        # Test GET /faculty/classes/CSE2A/subjects
        res_subs = await client.get("/faculty/classes/CSE2A/subjects", headers=acad_headers)
        print(f"Class CSE2A subjects: status={res_subs.status_code}, subjects={res_subs.json()}")
        assert res_subs.status_code == 200
        assert any(s["SubjectID"] == "TEST_CS901" for s in res_subs.json())
        print("✓ Department-scoped subjects retrieved successfully!")

    print("\n✅ All API endpoints verified and functioning perfectly!")

if __name__ == "__main__":
    asyncio.run(test_endpoints())
