# NiftyAI Trading Agent

## Project Overview
Self-improving AI trading agent for NSE/BSE Indian markets.
Pre-market scan runs midnight to 9 AM. Trades fire at 9:15 AM sharp.
Never analyze stocks after 9:15 AM for intraday.

## Stack
- Backend: FastAPI + Python 3.11
- Database: PostgreSQL (Supabase)
- Broker: Fyers API v3 (fyers-apiv3 Python library)
- AI: OpenAI GPT-4o for reasoning, local ML models for signals
- Frontend: React + Tailwind deployed on Vercel
- Queue: Celery + Redis

## Hard Rules
- Minimum R:R 1:2 on every trade
- VIX Regime Logic:
    - VIX < 15: Normal Mode (Full position)
    - 15-20: Cautious Mode (75% size, tighter SL)
    - 20-25: High Volatility (50% size, Large Cap only)
    - 25-30: Extreme Volatility (25% size, SELL/SHORT preferred)
    - VIX > 30: Panic Mode (0% size, Swing trades only)
- Kill all BUY trades if SGX Nifty < -1%
- Never chase a stock that moved 2%+ from entry price
- All intraday analysis must complete before 9:00 AM

## Code Style
- Python: type hints always, docstrings on every function
- All API keys from .env — never hardcode credentials
- Every trade logged to database with full context
- Error handling on every external API call
- Retry logic (3 attempts) on all broker and data API calls

## Database Tables
- stocks — master list of all Nifty 500 symbols
- daily_prices — OHLCV data per stock per day
- signals — model scores per stock per day
- trades — every trade the agent stages
- outcomes — result of every trade (target hit / SL hit)

## Models
- XGBoost: scores stocks on technical indicators, saved to /models/saved/xgboost_nifty.pkl
- LSTM: time-series pattern detection, saved to /models/saved/lstm_model.pth
- FinBERT: sentiment scoring of news headlines (ProsusAI/finbert)
- Claude Sonnet API: final reasoning, trade selection, JSON output only