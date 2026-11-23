# =============================================================================
# clean_live_database.py
# Wipes all students, classes, faculty, logs, attendance, and leaves from
# live Supabase PostgreSQL and resets sequences, preserving only core admin accounts.
# =============================================================================
import asyncio
import asyncpg
import sqlite3
import os
import sys

# Ensure UTF-8 on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings

SUPABASE_URL = get_settings().DATABASE_URL
if not SUPABASE_URL:
    raise RuntimeError("DATABASE_URL is not configured in .env")

ADMIN_USERNAMES = [
    "admin",
    "principal",
    "viceprincipal",
    "hod.cse",
    "hod.it",
    "hod.aids",
    "hod.ece",
    "hod.mech",
    "hod.eee",
    "hod.cyber",
    "hod.aiml",
    "hod.sh",
    "hod.placement",
]

CORE_DEPARTMENTS = [
    ("CSE", "Department of Computer Science & Engineering", "Dr. Antony Sudha K (HOD CSE)"),
    ("IT", "Department of Information Technology", "Dr. S.Banu Priya (HOD IT)"),
    ("AIDS", "Department of Artificial Intelligence & Data Science", "Dr. K. Rajesh (HOD AI&DS)"),
    ("ECE", "Department of Electronics & Communication Engineering", "Dr. Dinesh Babu (HOD ECE)"),
    ("MECH", "Department of Mechanical Engineering", "Dr. V. Anand (HOD MECH)"),
    ("EEE", "Department of Electrical & Electronics Engineering", "Dr. Baskar (HOD EEE)"),
    ("CYBER", "Department of Cyber Security", "Dr. Fathima (HOD CYBER)"),
    ("AIML", "Department of Artificial Intelligence & Machine Learning", "Dr. T. Suresh (HOD AI&ML)"),
    ("SH", "Department of Science & Humanities", "Dr. Devi (HOD S&H)"),
    ("PLACEMENT", "Department of Training & Placement", "Mr. Krishnamoorthy (Head - Training & Placement)"),
]


async def clean_supabase():
    print("=" * 60)
    print(">>> CONNECTING TO LIVE SUPABASE POSTGRESQL (SINGAPORE) <<<")
    print("=" * 60)

    conn = await asyncpg.connect(SUPABASE_URL)

    try:
        # 1. Truncate / delete dependent child tables
        tables_to_purge = [
            "audit_logs",
            "notifications",
            "hostel_gate_passes",
            "student_leaves",
            "faculty_leaves",
            "attendance_records",
            "attendance_sessions",
            "faculty_allocations",
            "students",
            "faculty",
            "subjects",
            "classes",
        ]

        print("[1/5] Truncating operational and cohort tables in Supabase...")
        for tbl in tables_to_purge:
            try:
                await conn.execute(f"TRUNCATE TABLE {tbl} CASCADE")
                print(f"  ✓ Truncated {tbl}")
            except Exception as e:
                # Fallback to DELETE if TRUNCATE has foreign key restriction
                await conn.execute(f"DELETE FROM {tbl}")
                print(f"  ✓ Deleted all rows from {tbl} (fallback: {e})")

        # 2. Reset sequences for clean ID assignment starting from 1
        print("[2/5] Resetting auto-increment sequences...")
        seq_query = """
            SELECT sequence_name 
            FROM information_schema.sequences 
            WHERE sequence_schema = 'public'
        """
        sequences = await conn.fetch(seq_query)
        for s in sequences:
            seq_name = s["sequence_name"]
            # don't reset departments sequence or users sequence if keeping rows
            if not any(x in seq_name for x in ["departments", "users"]):
                try:
                    await conn.execute(f"ALTER SEQUENCE {seq_name} RESTART WITH 1")
                    print(f"  ✓ Reset sequence: {seq_name}")
                except Exception as ex:
                    print(f"  - Could not reset sequence {seq_name}: {ex}")

        # 3. Clean non-admin users
        print("[3/5] Cleaning non-admin users from users table...")
        del_users = await conn.execute(
            """
            DELETE FROM users 
            WHERE username NOT IN (
                'admin', 'principal', 'viceprincipal',
                'hod.cse', 'hod.it', 'hod.aids', 'hod.ece', 'hod.mech',
                'hod.eee', 'hod.cyber', 'hod.aiml', 'hod.sh', 'hod.placement'
            )
            """
        )
        print(f"  ✓ {del_users}")

        # 4. Ensure departments and link HOD users
        print("[4/5] Verifying 10 core departments and HOD user mapping...")
        # Get user id map
        users = await conn.fetch("SELECT id, username FROM users")
        user_map = {u["username"]: u["id"] for u in users}

        for code, name, hod_name in CORE_DEPARTMENTS:
            hod_username = f"hod.{code.lower()}"
            hod_uid = user_map.get(hod_username)

            # Check if department exists
            dept = await conn.fetchrow("SELECT id FROM departments WHERE code = $1", code)
            if not dept:
                await conn.execute(
                    """
                    INSERT INTO departments (code, name, hod_user_id, is_active, created_at)
                    VALUES ($1, $2, $3, TRUE, NOW())
                    """,
                    code, name, hod_uid
                )
                print(f"  ✓ Inserted department: {code}")
            else:
                await conn.execute(
                    """
                    UPDATE departments 
                    SET name = $1, hod_user_id = $2, is_active = TRUE 
                    WHERE code = $3
                    """,
                    name, hod_uid, code
                )
                print(f"  ✓ Updated department: {code} (HOD User ID: {hod_uid})")

        # Deactivate any non-core departments
        await conn.execute(
            """
            UPDATE departments 
            SET is_active = FALSE 
            WHERE code NOT IN ('CSE','IT','AIDS','ECE','MECH','EEE','CYBER','AIML','SH','PLACEMENT')
            """
        )

        # 5. Verify final live table row counts
        print("\n[5/5] Final Table Verification in Live Supabase:")
        all_tables = [
            "departments", "users", "classes", "subjects", "students", "faculty",
            "attendance_sessions", "attendance_records", "faculty_allocations",
            "faculty_leaves", "student_leaves", "hostel_gate_passes", "notifications", "audit_logs"
        ]
        results = {}
        for tbl in all_tables:
            count = await conn.fetchval(f"SELECT COUNT(*) FROM {tbl}")
            results[tbl] = count
            status = "✓ CLEAN (0)" if count == 0 else f"✓ ACTIVE ({count})"
            print(f"  - {tbl:<25}: {count:<5} [{status}]")

        # Verify active users list
        remaining_users = await conn.fetch("SELECT id, username, role, full_name FROM users ORDER BY id")
        print("\nActive Administrative Accounts in Live Supabase:")
        for u in remaining_users:
            print(f"  ID: {u['id']:<3} | User: {u['username']:<16} | Role: {u['role']:<12} | Name: {u['full_name']}")

    finally:
        await conn.close()


def clean_sqlite():
    db_path = os.path.join(os.path.dirname(__file__), "..", "attendtrax.db")
    if os.path.exists(db_path):
        os.remove(db_path)
        print("  ✓ Removed legacy attendtrax.db file.")
    else:
        print("  ✓ Pure Supabase confirmed: no local attendtrax.db present.")


if __name__ == "__main__":
    asyncio.run(clean_supabase())
    clean_sqlite()
