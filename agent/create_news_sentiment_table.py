"""
Create the `news_sentiment` table in Supabase.
Run once:  python agent/create_news_sentiment_table.py
"""

import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

SQL = """
CREATE TABLE IF NOT EXISTS public.news_sentiment (
    id            BIGSERIAL    PRIMARY KEY,
    headline      TEXT         NOT NULL,
    symbol        TEXT,
    source        TEXT         NOT NULL,
    bullish       DOUBLE PRECISION NOT NULL DEFAULT 0,
    bearish       DOUBLE PRECISION NOT NULL DEFAULT 0,
    neutral       DOUBLE PRECISION NOT NULL DEFAULT 0,
    sentiment     TEXT         NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Index for fast queries by symbol and date
CREATE INDEX IF NOT EXISTS idx_news_sentiment_symbol
    ON public.news_sentiment (symbol);
CREATE INDEX IF NOT EXISTS idx_news_sentiment_created
    ON public.news_sentiment (created_at DESC);
"""

if __name__ == "__main__":
    import psycopg2

    DATABASE_URL = os.getenv("DATABASE_URL", "")
    if not DATABASE_URL:
        print("DATABASE_URL not set in .env")
        exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(SQL)
    cur.close()
    conn.close()
    print("✅  news_sentiment table created successfully.")

