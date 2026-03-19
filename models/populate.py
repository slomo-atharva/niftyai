import os
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, MetaData, Table
from dotenv import load_dotenv
import pandas as pd
import yfinance as yf

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
metadata = MetaData()

daily_prices = Table(
    'daily_prices', metadata,
    Column('id', Integer, primary_key=True, autoincrement=True),
    Column('symbol', String),
    Column('date', Date),
    Column('open', Float),
    Column('high', Float),
    Column('low', Float),
    Column('close', Float),
    Column('volume', Float),
    Column('delivery_pct', Float)
)

metadata.create_all(engine)

symbols = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS"]
fyers_symbols = ["NSE:RELIANCE-EQ", "NSE:TCS-EQ", "NSE:HDFCBANK-EQ", "NSE:INFY-EQ", "NSE:ICICIBANK-EQ", "NSE:SBIN-EQ", "NSE:HINDUNILVR-EQ", "NSE:ITC-EQ", "NSE:LT-EQ", "NSE:BAJFINANCE-EQ"]

all_data = []
for yfsym, fsym in zip(symbols, fyers_symbols):
    print(f"Fetching {fsym}...")
    try:
        df = yf.Ticker(yfsym).history(period="2y")
        if not df.empty:
            df.reset_index(inplace=True)
            for _, row in df.iterrows():
                dt = pd.to_datetime(row['Date']).date()
                all_data.append({
                    "symbol": fsym,
                    "date": dt,
                    "open": float(row['Open']),
                    "high": float(row['High']),
                    "low": float(row['Low']),
                    "close": float(row['Close']),
                    "volume": float(row['Volume']),
                    "delivery_pct": 0.0
                })
    except Exception as e:
         print(e)
         
if all_data:
    df = pd.DataFrame(all_data)
    df.to_sql('daily_prices', engine, if_exists='replace', index=False)
    print(f"Inserted {len(df)} rows to daily_prices")
else:
    print("No data inserted.")
