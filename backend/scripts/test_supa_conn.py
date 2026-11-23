import asyncio
import asyncpg
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import get_settings

async def test():
    db_url = get_settings().DATABASE_URL
    if not db_url:
        raise RuntimeError("DATABASE_URL is not configured in .env")
    clean_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    print(f"Testing Supabase connection with URL: {clean_url.split('@')[1]}...")
    try:
        conn = await asyncio.wait_for(asyncpg.connect(clean_url), timeout=8)
        res = await conn.fetchval("SELECT version()")
        print(f"  [SUCCESS] {res[:50]}")
        tables = await conn.fetch("SELECT table_name FROM information_schema.tables WHERE table_schema='public'")
        print(f"  Tables count: {len(tables)} -> {[r['table_name'] for r in tables]}")
        await conn.close()
    except Exception as e:
        print(f"  [FAILED] {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(test())
