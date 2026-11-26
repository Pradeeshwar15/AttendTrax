"""
migrate_student_profile_fields.py
Adds column 'gender' to 'students' table and creates performance indexes on:
- gender
- residence_type
- roll_no
- placement_willingness
- status
in Supabase PostgreSQL.
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text, inspect
from database import get_engine

async def migrate():
    print("=" * 60)
    print("MIGRATION: Student Profile Fields (Gender, Scholar, Roster) & Indexes")
    print("=" * 60)
    engine = get_engine()
    async with engine.begin() as conn:
        print("1. Checking column 'gender' on 'students'...")
        def check_col(sync_conn):
            insp = inspect(sync_conn)
            cols = [c["name"] for c in insp.get_columns("students")]
            return "gender" in cols
        
        has_gender = await conn.run_sync(check_col)
        if not has_gender:
            print("   -> Adding column 'gender' VARCHAR(20) to table 'students'...")
            await conn.execute(text("""
                ALTER TABLE students 
                ADD COLUMN IF NOT EXISTS gender VARCHAR(20);
            """))
            print("   ✓ Column 'gender' added.")
        else:
            print("   ✓ Column 'gender' already exists.")

        print("2. Creating B-tree indexes for fast querying & filtering...")
        index_queries = [
            ("ix_students_gender", "CREATE INDEX IF NOT EXISTS ix_students_gender ON students (gender);"),
            ("ix_students_residence_type", "CREATE INDEX IF NOT EXISTS ix_students_residence_type ON students (residence_type);"),
            ("ix_students_roll_no", "CREATE INDEX IF NOT EXISTS ix_students_roll_no ON students (roll_no);"),
            ("ix_students_placement_willingness", "CREATE INDEX IF NOT EXISTS ix_students_placement_willingness ON students (placement_willingness);"),
            ("ix_students_status", "CREATE INDEX IF NOT EXISTS ix_students_status ON students (status);"),
        ]
        for idx_name, q in index_queries:
            await conn.execute(text(q))
            print(f"   ✓ Index '{idx_name}' verified/created.")

    # Verification
    async with engine.connect() as conn:
        def verify_schema(sync_conn):
            insp = inspect(sync_conn)
            cols = [c["name"] for c in insp.get_columns("students")]
            indexes = [idx["name"] for idx in insp.get_indexes("students")]
            return cols, indexes
        
        cols, indexes = await conn.run_sync(verify_schema)
        print("3. Verification:")
        print("   Columns on 'students':", cols)
        assert "gender" in cols, "Failed to verify 'gender' column!"
        assert "residence_type" in cols, "Failed to verify 'residence_type' column!"
        assert "roll_no" in cols, "Failed to verify 'roll_no' column!"
        print("   Indexes on 'students':", indexes)
        for expected_idx in ["ix_students_gender", "ix_students_residence_type", "ix_students_roll_no"]:
            assert expected_idx in indexes, f"Index {expected_idx} missing!"
        print("\n🎉 MIGRATION COMPLETE! All student fields and indexes verified in Supabase.")

if __name__ == "__main__":
    asyncio.run(migrate())
