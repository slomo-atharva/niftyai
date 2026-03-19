import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("No DATABASE_URL found.")
    exit(1)

engine = create_engine(DATABASE_URL)

with engine.begin() as conn:
    try:
        conn.execute(text("ALTER TABLE trades ADD COLUMN trade_type TEXT;"))
        print("Added trade_type column.")
    except Exception as e:
        print("Couldn't add trade_type:", e)

    try:
        conn.execute(text("ALTER TABLE trades ADD COLUMN holding_period TEXT;"))
        print("Added holding_period column.")
    except Exception as e:
        print("Couldn't add holding_period:", e)
