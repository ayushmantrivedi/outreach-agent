"""Script to count companies by source."""
from ai_outreach_agent.database.db import get_connection

with get_connection() as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT source, COUNT(*) FROM companies GROUP BY source;")
        results = cur.fetchall()
        for source, count in results:
            print(f"- {source}: {count} companies")
        
        cur.execute("SELECT COUNT(*) FROM companies;")
        total = cur.fetchone()[0]
        print(f"\nTotal: {total} companies discovered and ready for ranking.")
