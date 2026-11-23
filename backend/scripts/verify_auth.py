import asyncio
import asyncpg
import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import verify_password

from config import get_settings

SUPABASE_URL = get_settings().DATABASE_URL
if not SUPABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured in .env")

TEST_CREDENTIALS = [
    ("admin", "AttendTrax@2026"),
    ("principal", "Principal@2026"),
    ("viceprincipal", "VP@2026"),
    ("hod.cse", "Hod@2026"),
    ("hod.it", "Hod@2026"),
    ("hod.aids", "Hod@2026"),
    ("hod.ece", "Hod@2026"),
    ("hod.mech", "Hod@2026"),
    ("hod.eee", "Hod@2026"),
    ("hod.cyber", "Hod@2026"),
    ("hod.aiml", "Hod@2026"),
    ("hod.sh", "Hod@2026"),
    ("hod.placement", "Hod@2026"),
]

async def verify_auth():
    conn = await asyncpg.connect(SUPABASE_URL)
    print("=" * 70)
    print(">>> VERIFYING AUTHENTICATION AGAINST LIVE SUPABASE (SINGAPORE) <<<")
    print("=" * 70)
    all_ok = True
    for uname, raw_pwd in TEST_CREDENTIALS:
        row = await conn.fetchrow("SELECT username, password_hash, role, full_name FROM users WHERE username = $1", uname)
        if not row:
            print(f"  ❌ {uname:<16}: USER NOT FOUND")
            all_ok = False
            continue
        valid = verify_password(raw_pwd, row["password_hash"])
        if valid:
            print(f"  ✓ {uname:<16} -> LOGIN SUCCESS | Role: {row['role']:<12} | Name: {row['full_name']}")
        else:
            print(f"  ❌ {uname:<16} -> INVALID PASSWORD HASH")
            all_ok = False
    await conn.close()
    if all_ok:
        print("\nAll 13 administrative credentials verified successfully!")
    else:
        print("\nSome credentials failed verification.")

if __name__ == "__main__":
    asyncio.run(verify_auth())
