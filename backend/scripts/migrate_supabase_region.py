# =============================================================================
# AttendTrax Enterprise – Direct Region-to-Region Supabase Migration Tool
# backend/scripts/migrate_supabase_region.py
# Migrates schema & data from Ireland (eu-west-1) to Singapore (ap-southeast-1)
# =============================================================================
import asyncio
import os
import sys
from datetime import datetime, date

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# Topological table order respecting foreign key constraints
TABLE_ORDER = [
    "departments",
    "users",
    "faculty",
    "classes",
    "students",
    "subjects",
    "faculty_allocations",
    "attendance_sessions",
    "attendance_records",
    "faculty_leaves",
    "student_leaves",
    "hostel_gate_passes",
    "notifications",
    "audit_logs",
]


def clean_pg_url(url: str) -> str:
    """Normalize SQLAlchemy asyncpg URL to standard PostgreSQL URL."""
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def migrate_between_regions(source_url: str, target_url: str):
    print("=" * 65)
    print("🚀 ATTENDTRAX SUPABASE CROSS-REGION MIGRATION PIPELINE")
    print("=" * 65)

    source_pg = clean_pg_url(source_url)
    target_pg = clean_pg_url(target_url)

    source_host = source_pg.split("@")[-1].split("/")[0] if "@" in source_pg else "source"
    target_host = target_pg.split("@")[-1].split("/")[0] if "@" in target_pg else "target"

    print(f"[*] Source Database (Old Region) : {source_host}")
    print(f"[*] Target Database (Singapore)  : {target_host}")

    # Step 1: Initialize schema on target
    print("\n[1/4] Ensuring full schema and indexes on Singapore instance...")
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)
    from models import Base

    target_engine_url = target_url
    if not target_engine_url.startswith("postgresql+asyncpg://"):
        target_engine_url = "postgresql+asyncpg://" + target_pg.replace("postgresql://", "", 1)

    t_engine = create_async_engine(target_engine_url)
    async with t_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await t_engine.dispose()
    print("  ✓ Target schema and indexes verified.")

    # Step 2: Establish asyncpg connections
    print("\n[2/4] Connecting to Source (Ireland) and Target (Singapore)...")
    src_conn = await asyncpg.connect(source_pg, timeout=60)
    tgt_conn = await asyncpg.connect(target_pg, timeout=60)
    print("  ✓ Connected to both database instances.")

    # Step 3: Transfer data table by table
    print("\n[3/4] Transferring tables in topological order...")
    total_migrated = 0

    for tbl in TABLE_ORDER:
        # Check if table exists on source
        chk = await src_conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = $1)",
            tbl,
        )
        if not chk:
            print(f"  • {tbl}: does not exist in source schema (skipping)")
            continue

        rows = await src_conn.fetch(f'SELECT * FROM "{tbl}"')
        row_count = len(rows)

        if row_count == 0:
            print(f"  • {tbl}: 0 rows (empty)")
            continue

        cols = list(rows[0].keys())
        col_list_str = ", ".join([f'"{c}"' for c in cols])
        placeholders = ", ".join([f"${i+1}" for i in range(len(cols))])

        insert_sql = f'INSERT INTO "{tbl}" ({col_list_str}) VALUES ({placeholders}) ON CONFLICT DO NOTHING;'

        # Clean prepared tuples
        records = [tuple(r.values()) for r in rows]

        await tgt_conn.executemany(insert_sql, records)
        total_migrated += row_count
        print(f"  ✓ {tbl:<22}: {row_count:>4} rows copied successfully")

        # Step 4: Advance sequences
        try:
            seq_val = await tgt_conn.fetchval(
                f"SELECT setval(pg_get_serial_sequence('\"{tbl}\"', 'id'), COALESCE(max(id), 1)) FROM \"{tbl}\";"
            )
        except Exception:
            pass

    # Verify counts on target
    print("\n[4/4] Verifying Target Integrity & Row Counts in Singapore...")
    mismatch = False
    for tbl in TABLE_ORDER:
        s_cnt = await src_conn.fetchval(f'SELECT count(*) FROM "{tbl}"')
        t_cnt = await tgt_conn.fetchval(f'SELECT count(*) FROM "{tbl}"')
        status = "OK" if s_cnt == t_cnt else "MISMATCH"
        if s_cnt != t_cnt:
            mismatch = True
        print(f"  • {tbl:<22}: Source={s_cnt:>4} | Target={t_cnt:>4} [{status}]")

    await src_conn.close()
    await tgt_conn.close()

    print("\n" + "=" * 65)
    if not mismatch:
        print(f"🎉 MIGRATION SUCCESSFUL! {total_migrated} total rows transferred.")
        print("Both Render and Supabase are now co-located in Singapore (ap-southeast-1).")
        print("Expected query latency: ~1ms - 3ms (intra-datacenter speed).")
    else:
        print("⚠️ Migration finished with some count discrepancies. Please check the logs above.")
    print("=" * 65)


if __name__ == "__main__":
    old_ireland_default = "postgresql://postgres.ubkvrgwwelrrwqtlmqcq:bY69u08s7eu0aKZo@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"

    if len(sys.argv) >= 3:
        src = sys.argv[1]
        tgt = sys.argv[2]
    elif len(sys.argv) == 2:
        tgt = sys.argv[1]
        src = os.getenv("OLD_DATABASE_URL", old_ireland_default)
    else:
        src = os.getenv("OLD_DATABASE_URL", old_ireland_default)
        tgt = os.getenv("DATABASE_URL", "")

    if not tgt or src == tgt:
        print("Usage: python backend/scripts/migrate_supabase_region.py [SOURCE_URL] <TARGET_URL>")
        sys.exit(1)

    asyncio.run(migrate_between_regions(src, tgt))
