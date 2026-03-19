import os
import sys
import json
import logging
import argparse
from datetime import datetime, timezone
import yfinance as yf
from dotenv import load_dotenv
import pandas_market_calendars as mcal
import pandas as pd

# Add parent directory to path to allow importing local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.news_scraper import run_scrape_and_score, KNOWN_SYMBOLS, get_supabase_client
from agent.main_agent import get_xgboost_scores
from models.saved.momentum_scorer import MomentumScorer
from data.fyers_client import place_order
from openai import OpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def log_error_to_db(step: str, error_message: str):
    """Log errors to database without crashing"""
    try:
        supabase = get_supabase_client()
        now = datetime.now(timezone.utc).isoformat()
        # Fallback table name to logs or error_logs if schema expects it. 
        # Using a generic 'error_logs' for the demonstration.
        supabase.table('error_logs').insert({
            "step": step,
            "error_message": error_message,
            "created_at": now
        }).execute()
    except Exception as e:
        logger.error(f"Failed to log error to DB: {e}")

def is_market_holiday_or_weekend(date_obj=None) -> tuple[bool, str]:
    """Check if today is a weekend or market holiday."""
    if date_obj is None:
        date_obj = datetime.now(timezone.utc).date()
    
    # date_obj is now derived from today's actual date if not provided
        
    bse = None
    try:
        bse = mcal.get_calendar('BSE')
    except Exception as e:
        logger.warning(f"Error getting BSE calendar: {e}")

    # Check if there is a special trading session on a weekend
    if date_obj.weekday() >= 5:
        if bse is not None:
            try:
                schedule = bse.schedule(start_date=date_obj, end_date=date_obj)
                if not schedule.empty:
                    logger.warning("NSE opens today due to a special session despite being weekend! Continuing anyway.")
                    return False, "SPECIAL_SESSION"
            except Exception:
                pass
        return True, "WEEKEND"
    
    if bse is not None:
        try:
            schedule = bse.schedule(start_date=date_obj, end_date=date_obj)
            if schedule.empty:
                return True, "HOLIDAY"
            
            # Check for late opening (special session typically opens after 9:15am IST / 03:45am UTC)
            open_time = schedule.iloc[0]['market_open']
            if open_time.hour > 4 or (open_time.hour == 4 and open_time.minute > 15):
                logger.warning("NSE opens late today due to a special session! Continuing anyway.")
                
            return False, "TRADING_DAY"
        except Exception as e:
            logger.warning(f"Error checking market calendar schedule: {e}")
            
    # Default to false in case of error, to allow scan to attempt
    return False, "UNKNOWN"

def get_next_trading_day(date_obj=None) -> str:
    """Returns the next working market day."""
    if date_obj is None:
        date_obj = datetime.now(timezone.utc).date()
    try:
        bse = mcal.get_calendar('BSE')
        # Look ahead up to 10 days to find the next valid day
        end_date = date_obj + pd.Timedelta(days=10)
        schedule = bse.schedule(start_date=date_obj + pd.Timedelta(days=1), end_date=end_date)
        if not schedule.empty:
            next_day = schedule.index[0]
            if isinstance(next_day, pd.Timestamp):
                return next_day.date().isoformat()
            return str(next_day.date())
    except Exception as e:
        logger.warning(f"Error fetching next trading day: {e}")
    return "UNKNOWN"

def fetch_market_context() -> dict:
    """Step 1: Fetch market context"""
    logger.info("Fetching market context...")
    context = {}
    
    try:
        sgx = yf.Ticker("^NSEI").history(period="5d")
        if len(sgx) >= 2:
            prev_close = float(sgx['Close'].iloc[-2])
            last_close = float(sgx['Close'].iloc[-1])
            sgx_change_pct = ((last_close - prev_close) / prev_close) * 100
            context['sgx_nifty_pct'] = round(sgx_change_pct, 2)
            context['sgx_nifty_value'] = round(last_close, 2)
        else:
            context['sgx_nifty_pct'] = 0.0
            context['sgx_nifty_value'] = 0.0
    except Exception as e:
        msg = f"Error fetching SGX Nifty: {e}"
        logger.error(msg)
        log_error_to_db("market_context - sgx", msg)
        context['sgx_nifty_pct'] = 0.0
        context['sgx_nifty_value'] = 0.0

    try:
        usd_inr = yf.Ticker("INR=X").history(period="1d")
        if not usd_inr.empty:
            context['usd_inr'] = round(float(usd_inr['Close'].iloc[-1]), 2)
        else:
            context['usd_inr'] = 0.0
    except Exception as e:
        msg = f"Error fetching USD/INR: {e}"
        logger.error(msg)
        log_error_to_db("market_context - usd_inr", msg)
        context['usd_inr'] = 0.0

    try:
        crude = yf.Ticker("CL=F").history(period="1d")
        if not crude.empty:
            context['crude_oil'] = round(float(crude['Close'].iloc[-1]), 2)
        else:
            context['crude_oil'] = 0.0
    except Exception as e:
        msg = f"Error fetching Crude Oil: {e}"
        logger.error(msg)
        log_error_to_db("market_context - crude", msg)
        context['crude_oil'] = 0.0

    try:
        vix = yf.Ticker("^INDIAVIX").history(period="1d")
        if not vix.empty:
            context['vix'] = round(float(vix['Close'].iloc[-1]), 2)
        else:
            context['vix'] = 0.0
    except Exception as e:
        msg = f"Error fetching VIX: {e}"
        logger.error(msg)
        log_error_to_db("market_context - vix", msg)
        context['vix'] = 0.0

    logger.info(f"Market context: {context}")
    return context

def run_news_scraper() -> dict:
    """Step 2: Run news scraper and get sentiments"""
    logger.info("Running news scraper...")
    per_stock_sentiment = {}
    try:
        news_records = run_scrape_and_score()
        for record in news_records:
            sym = record.get('symbol')
            bullish = float(record.get('bullish', 0.5))
            if sym:
                if sym not in per_stock_sentiment:
                    per_stock_sentiment[sym] = []
                per_stock_sentiment[sym].append(bullish)
        
        # Average per stock
        for sym, scores in per_stock_sentiment.items():
            per_stock_sentiment[sym] = sum(scores) / len(scores)
            
    except Exception as e:
        msg = f"Error running news scraper: {e}"
        logger.error(msg)
        log_error_to_db("news_scraper", msg)
    
    return per_stock_sentiment

def score_nifty_500(per_stock_sentiment: dict) -> list:
    """Step 3: Score all Nifty 500 stocks"""
    logger.info("Scoring Nifty 500 stocks...")
    symbols = KNOWN_SYMBOLS
    
    xgb_scores = {}
    try:
        xgb_scores = get_xgboost_scores(symbols)
    except Exception as e:
        msg = f"Error fetching XGBoost scores: {e}"
        logger.error(msg)
        log_error_to_db("score_nifty - xgboost", msg)

    momentum = MomentumScorer()
    combined_scores = []
    
    for sym in symbols:
        try:
            xgb_val = float(xgb_scores.get(sym, 0.5))
            mom_raw = float(momentum.get_score(sym + ".NS"))
            mom_norm = (mom_raw + 1) / 5.0 # normalize -1 to 4 to 0.0 to 1.0
            fin_val = float(per_stock_sentiment.get(sym, 0.5))
            
            combined = (xgb_val * 0.60) + (mom_norm * 0.25) + (fin_val * 0.15)
            combined_scores.append({
                "symbol": sym,
                "xgb_score": round(xgb_val, 3),
                "mom_score": round(mom_norm, 3),
                "finbert_score": round(fin_val, 3),
                "combined_score": round(combined, 3)
            })
        except Exception as e:
            msg = f"Error scoring {sym}: {e}"
            logger.error(msg)
            log_error_to_db(f"score_nifty - {sym}", msg)
    
    # Sort and get top 20
    combined_scores.sort(key=lambda x: x['combined_score'], reverse=True)
    top_20 = combined_scores[:20]
    logger.info(f"Top 20 stocks identified: {[x['symbol'] for x in top_20]}")
    return top_20

def query_openai(top_20: list, market_context: dict) -> list:
    """Step 4: Send top 20 to OpenAI API"""
    logger.info("Querying OpenAI API...")
    trades = []
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        prompt = (
            f"Market Context: {json.dumps(market_context)}\n"
            f"Top 20 Stocks: {json.dumps(top_20)}\n"
        )
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are an expert NSE/BSE trader. Select maximum 6 high conviction trades from this list. For each trade return JSON with these fields: symbol, signal (BUY or SELL), entry, sl, t1, t2, t3, rr_ratio, confidence, reasoning. Apply these rules: minimum R:R 1:2, no trades if VIX above 20, no BUY trades if SGX Nifty below -1%. Return JSON array only, no other text."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=1500
        )
        
        # We need to extract the array, as OpenAI might return a json object with trades array
        text_resp = response.choices[0].message.content.strip()
        
        try:
            parsed = json.loads(text_resp)
            if isinstance(parsed, dict):
                # E.g. {"trades": [...]}
                for key, val in parsed.items():
                    if isinstance(val, list):
                        trades = val
                        break
            elif isinstance(parsed, list):
                trades = parsed
            else:
                trades = []
            logger.info(f"OpenAI suggested {len(trades)} trades.")
        except json.JSONDecodeError as je:
            msg = f"Failed to parse JSON from OpenAI: {je}"
            logger.error(msg)
            log_error_to_db("query_openai_json_parse", msg)
            
    except Exception as e:
        msg = f"Error querying OpenAI API: {e}"
        logger.error(msg)
        log_error_to_db("query_openai_api", msg)
    
    return trades

def apply_kill_rules(trades: list, market_context: dict) -> tuple:
    """Step 5: Apply kill rules programmatically"""
    logger.info("Applying kill rules...")
    approved = []
    killed = []
    
    vix = market_context.get('vix', 0.0)
    sgx = market_context.get('sgx_nifty_pct', 0.0)
    
    for t in trades:
        try:
            symbol = t.get('symbol')
            signal = t.get('signal', '').upper()
            rr = float(t.get('rr_ratio', 0.0))
            entry = float(t.get('entry', 0.0))
            
            reason = None
            if rr < 2.0:
                reason = f"R:R ratio {rr} is below 2.0"
            elif vix > 20 and signal == "BUY":
                reason = f"VIX {vix} > 20 for BUY trade"
            elif sgx < -1.0 and signal == "BUY":
                reason = f"SGX Nifty {sgx}% < -1% for BUY trade"
            else:
                try:
                    ticker = yf.Ticker(symbol + ".NS")
                    hist = ticker.history(period="1d")
                    if not hist.empty:
                        last_price = float(hist['Close'].iloc[-1])
                        move_pct = abs(last_price - entry) / entry
                        if move_pct > 0.02:
                            reason = f"Stock moved {round(move_pct*100, 2)}% from entry (>{2}%)"
                except Exception as e:
                    logger.warning(f"Could not check price for {symbol}: {e}")
            
            if reason:
                logger.info(f"Killing trade {symbol} ({signal}): {reason}")
                t['kill_reason'] = reason
                killed.append(t)
            else:
                approved.append(t)
        except Exception as e:
            msg = f"Error applying kill rules to trade {t}: {e}"
            logger.error(msg)
            log_error_to_db(f"apply_kill_rules - {t.get('symbol')}", msg)
            t['kill_reason'] = f"Error processing: {e}"
            killed.append(t)
            
    return approved, killed

def save_to_database(approved: list, killed: list, context: dict, stocks_scanned: int):
    """Step 6: Save to database"""
    logger.info("Saving results to database...")
    try:
        supabase = get_supabase_client()
        now = datetime.now(timezone.utc).isoformat()
        
        all_trades = []
        for t in approved:
            t_copy = t.copy()
            t_copy['status'] = 'APPROVED'
            t_copy['market_context'] = context
            t_copy['created_at'] = now
            all_trades.append(t_copy)
            
        for t in killed:
            t_copy = t.copy()
            t_copy['status'] = 'KILLED'
            t_copy['market_context'] = context
            t_copy['created_at'] = now
            all_trades.append(t_copy)
            
        if all_trades:
            supabase.table('trades').insert(all_trades).execute()
            logger.info("Successfully saved trades to Supabase.")
            
        # Also saving raw market_context with summary stats
        supabase.table('market_context').insert({
            "context_data": {
                **context,
                "stocks_scanned": stocks_scanned,
                "trades_staged": len(approved),
                "trades_killed": len(killed),
                "scan_type": "LIVE"
            },
            "created_at": now
        }).execute()
        
    except Exception as e:
        msg = f"Error saving to database: {e}"
        logger.error(msg)
        log_error_to_db("save_to_database", msg)

def stage_orders(approved: list):
    """Step 7: Set PAPER_TRADE flag"""
    paper_trade = os.getenv("PAPER_TRADE", "true").lower() == "true"
    if paper_trade:
        logger.info("PAPER_TRADE is true. Stopping here. No live orders placed.")
        return
        
    logger.info("PAPER_TRADE is false. Staging orders via Fyers API...")
    for t in approved:
        try:
            place_order(
                symbol=f"NSE:{t['symbol']}-EQ", 
                qty=1,
                side=t['signal'], 
                entry=t['entry'], 
                sl=t['sl'], 
                target=t['t1']
            )
        except Exception as e:
            msg = f"Error placing order for {t['symbol']}: {e}"
            logger.error(msg)
            log_error_to_db("stage_orders", msg)

def run_scan():
    logger.info("=== STARTING PRE-MARKET SCAN ===")
    
    # Step 1: Check holidays
    is_holiday, reason = is_market_holiday_or_weekend()
    if is_holiday:
        next_day = get_next_trading_day()
        msg = "Today is an NSE market holiday. Agent going back to sleep."
        if reason == "WEEKEND":
            msg = "Today is a weekend. Agent going back to sleep."
            
        logger.info(msg)
        logger.info(f"Next trading day will be: {next_day}")
        
        # Save this status to Supabase holiday_logs and market_context
        try:
            supabase = get_supabase_client()
            now = datetime.now(timezone.utc).isoformat()
            supabase.table('holiday_logs').insert({
                "status": "SLEEP",
                "reason": reason,
                "created_at": now
            }).execute()
            
            # Unified status in market_context for frontend
            supabase.table('market_context').insert({
                "context_data": {
                    "scan_type": "HOLIDAY",
                    "reason": reason,
                    "stocks_scanned": 0,
                    "trades_staged": 0,
                    "trades_killed": 0
                },
                "created_at": now
            }).execute()
            
            logger.info(f"Successfully logged sleep status for {reason}")
        except Exception as e:
            logger.error(f"Failed to log sleep status to DB: {e}")
            
        logger.info("=== PRE-MARKET SCAN COMPLETE ===")
        return
    
    context = fetch_market_context()
    per_stock_sentiment = run_news_scraper()
    top_20 = score_nifty_500(per_stock_sentiment)
    trades = query_openai(top_20, context)
    approved, killed = apply_kill_rules(trades, context)
    save_to_database(approved, killed, context, stocks_scanned=len(KNOWN_SYMBOLS))
    stage_orders(approved)
    
    logger.info("=== PRE-MARKET SCAN COMPLETE ===")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pre-market scan agent")
    parser.add_argument('--run-now', action='store_true', help='Run the scan immediately')
    parser.add_argument('--dry-run-fast', action='store_true', help='Run scan quickly on a subset for testing')
    args = parser.parse_args()
    
    if args.dry_run_fast:
        global KNOWN_SYMBOLS
        KNOWN_SYMBOLS = ["RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK"]
        run_scan()
    elif args.run_now:
        run_scan()
    else:
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
            scheduler = BlockingScheduler()
            scheduler.add_job(run_scan, 'cron', day_of_week='mon-fri', hour=6, minute=0)
            logger.info("Scheduler started. Waiting for next run at 6:00 AM Mon-Fri.")
            scheduler.start()
        except ImportError:
            logger.error("apscheduler not installed. Install via pip install apscheduler")
            log_error_to_db("init", "apscheduler not installed")
        except KeyboardInterrupt:
            logger.info("Scheduler stopped.")
