"""
migrate_placement_willingness.py
Adds column 'placement_willingness' to 'students' table in Supabase PostgreSQL
"""
import sys
import os
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text, inspect
from database import get_engine

async def migrate():
    print("Connecting to Supabase PostgreSQL...")
    engine = get_engine()
    async with engine.begin() as conn:
        print("Checking if column 'placement_willingness' exists in 'students'...")
        def check_col(sync_conn):
            insp = inspect(sync_conn)
            cols = [c["name"] for c in insp.get_columns("students")]
            return "placement_willingness" in cols
        
        has_col = await conn.run_sync(check_col)
        if not has_col:
            print("Adding column 'placement_willingness' to table 'students'...")
            await conn.execute(text("""
                ALTER TABLE students 
                ADD COLUMN IF NOT EXISTS placement_willingness VARCHAR(20) DEFAULT 'active' NOT NULL;
            """))
            print("Updating any existing null values to 'active'...")
            await conn.execute(text("""
                UPDATE students SET placement_willingness = 'active' WHERE placement_willingness IS NULL;
            """))
            print("Migration successful: column 'placement_willingness' added.")
        else:
            print("Column 'placement_willingness' already exists.")

    # Verify
    async with engine.connect() as conn:
        def verify_col(sync_conn):
            insp = inspect(sync_conn)
            return [c["name"] for c in insp.get_columns("students")]
        cols = await conn.run_sync(verify_col)
        print("Verified students columns:", cols)
        assert "placement_willingness" in cols, "Failed to verify placement_willingness column!"
        print("✅ Column 'placement_willingness' verified successfully in Supabase.")

if __name__ == "__main__":
    asyncio.run(migrate())
