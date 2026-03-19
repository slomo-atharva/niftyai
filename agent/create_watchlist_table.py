"""
Create the `watchlist` table in Supabase.
Run once:  python agent/create_watchlist_table.py
"""

import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")

SQL = """
CREATE TABLE IF NOT EXISTS public.watchlist (
    id                BIGSERIAL    PRIMARY KEY,
    symbol            TEXT         NOT NULL,
    reason            TEXT         NOT NULL,
    key_levels        TEXT         NOT NULL,
    risk_factors      TEXT         NOT NULL,
    opportunity_type  TEXT         NOT NULL, -- INTRADAY or SWING
    created_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Index for fast queries by date
CREATE INDEX IF NOT EXISTS idx_watchlist_created
    ON public.watchlist (created_at DESC);
"""

if __name__ == "__main__":
    if not DATABASE_URL:
        print("DATABASE_URL not set in .env")
        exit(1)

    try:
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(SQL)
        cur.close()
        conn.close()
        print("✅  watchlist table created successfully.")
    except Exception as e:
        print(f"❌  Error creating watchlist table: {e}")
