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
PROGRESS_FILE = "/tmp/scan_progress.json"

def update_scan_progress(status: str, percent: int):
    """Update progress for the backend to poll."""
    try:
        with open(PROGRESS_FILE, 'w') as f:
            json.dump({"status": status, "percent": percent, "timestamp": datetime.now(timezone.utc).isoformat()}, f)
    except Exception as e:
        logger.error(f"Failed to update progress file: {e}")


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

def get_vix_regime(vix: float) -> dict:
    """Returns regime name, position multiplier, and GPT instructions based on VIX."""
    if vix < 15:
        return {
            "name": "Normal Trading Mode",
            "multiplier": 1.0,
            "instruction": "Market is calm. Select best intraday and swing trades normally.",
            "color": "teal"
        }
    elif 15 <= vix < 20:
        return {
            "name": "Cautious Mode",
            "multiplier": 0.75,
            "instruction": "Market is slightly volatile. Prefer stocks with strong momentum and clear support levels. Tighter stop losses.",
            "color": "blue"
        }
    elif 20 <= vix < 25:
        return {
            "name": "High Volatility Mode",
            "multiplier": 0.50,
            "instruction": (
                f"VIX is at {vix} indicating high volatility. This does NOT mean avoid trading — it means trade smarter. "
                "You MUST recommend between 3 to 5 trades. Focus only on these large cap stocks: "
                "RELIANCE, HDFCBANK, INFY, TCS, ICICIBANK, SBIN, BAJFINANCE, KOTAKBANK, AXISBANK, LT, "
                "HINDUNILVR, WIPRO, HCLTECH, TATAMOTORS, MARUTI. "
                "Rules for high volatility: "
                "- Entry must be near strong support level "
                "- Stop loss wider than normal — 1.5x ATR "
                "- Target 1 conservative — 1% move minimum "
                "- Prefer stocks showing relative strength vs Nifty "
                "- Both BUY and SELL trades allowed "
                "- Tag each trade as INTRADAY or SWING "
                "- Position size reduced to 50% of normal. "
                "You must return between 3 and 5 trades as JSON. Returning 0 trades is not acceptable unless ALL stocks are showing extreme weakness."
            ),
            "color": "amber"
        }
    elif 25 <= vix < 30:
        return {
            "name": "Extreme Volatility Mode",
            "multiplier": 0.25,
            "instruction": f"VIX extremely high at {vix}. Only recommend SELL or SHORT trades on weak stocks. No BUY trades unless stock is showing exceptional strength vs market.",
            "color": "orange"
        }
    else: # vix >= 30
        return {
            "name": "Panic Mode",
            "multiplier": 0.0,
            "instruction": "Market in panic mode. Only recommend swing trades with 7-10 day horizon for strong fundamentally sound stocks at support levels. These are buying opportunities for patient traders.",
            "color": "red"
        }

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
        vix_ticker = yf.Ticker("^INDIAVIX").history(period="1d")
        if not vix_ticker.empty:
            vix_val = round(float(vix_ticker['Close'].iloc[-1]), 2)
            context['vix'] = vix_val
            regime = get_vix_regime(vix_val)
            context['vix_regime'] = regime['name']
            context['vix_instruction'] = regime['instruction']
            context['position_multiplier'] = regime['multiplier']
            context['vix_color'] = regime['color']
            
            if vix_val >= 30:
                context['vix_message'] = f"Panic Mode — VIX {vix_val} — Intraday trades killed. Showing swing opportunities only."
            elif vix_val >= 15:
                context['vix_message'] = f"{regime['name']} — VIX {vix_val} — Showing reduced position size recommendations"
            else:
                context['vix_message'] = f"Normal Trading Mode — VIX {vix_val}"
        else:
            context['vix'] = 0.0
            context['vix_regime'] = "Unknown"
    except Exception as e:
        msg = f"Error fetching VIX: {e}"
        logger.error(msg)
        log_error_to_db("market_context - vix", msg)
        context['vix'] = 0.0
        context['vix_regime'] = "Unknown"

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

def score_nifty_500(per_stock_sentiment: dict, symbols: list = None) -> list:
    """Step 3: Score Nifty stocks. If symbols is None, uses all KNOWN_SYMBOLS."""
    logger.info("Scoring stocks...")
    if symbols is None:
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
    
    print(f"\n--- TOP 10 STOCKS SENT TO GPT-4o ---")
    for s in combined_scores[:10]:
        print(f"{s['symbol']}: Score {s['combined_score']} (XGB: {s['xgb_score']}, Mom: {s['mom_score']}, Fin: {s['finbert_score']})")
    print("------------------------------------\n")

    top_20 = combined_scores[:20]
    logger.info(f"Top 20 stocks identified: {[x['symbol'] for x in top_20]}")
    return top_20


def fetch_live_prices(stocks: list) -> list:
    """Fetch live price for each stock via yfinance and attach to the stock dict.
    
    Uses fast_info['last_price'] which is the most recent trade price.
    Falls back to history period='1d' close if fast_info is unavailable.
    
    Args:
        stocks: List of stock dicts with 'symbol' key (NSE symbols without .NS suffix)
    
    Returns:
        Same list with 'live_price' key added to each dict.
    """
    logger.info("Fetching live prices for top stocks via yfinance...")
    for stock in stocks:
        symbol = stock.get('symbol', '')
        live_price = None
        try:
            ticker = yf.Ticker(f"{symbol}.NS")
            # fast_info is the quickest way — single lightweight API call
            live_price = ticker.fast_info.get('last_price') or ticker.fast_info.get('lastPrice')
            if not live_price:
                # Fallback: use last close from 1d history
                hist = ticker.history(period="1d")
                if not hist.empty:
                    live_price = float(hist['Close'].iloc[-1])
        except Exception as e:
            logger.warning(f"Could not fetch live price for {symbol}: {e}")
        
        stock['live_price'] = round(float(live_price), 2) if live_price else None
        if live_price:
            logger.info(f"{symbol}: live price = ₹{stock['live_price']}")
        else:
            logger.warning(f"{symbol}: live price unavailable, GPT-4o will estimate")
    
    return stocks

def generate_holiday_watchlist(top_20: list):
    """Step 4b: Generate a watchlist for the next session on holidays"""
    logger.info("Generating next session watchlist for holiday...")
    watchlist = []
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        prompt = (
            "Market is closed today. Analyse these stocks and "
            "give me a watchlist of best 5 stocks to watch when "
            "market opens next. For each give: symbol, why to "
            "watch, key price levels, risk factors. "
            "Tag each as INTRADAY or SWING opportunity. "
            "Return JSON only.\n\n"
            f"Top 20 Stocks: {json.dumps(top_20)}\n"
        )
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a professional NSE/BSE analyst. Return only a JSON array of objects with keys: symbol, reason, key_levels, risk_factors, opportunity_type."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=2000
        )
        
        text_resp = response.choices[0].message.content.strip()
        parsed = json.loads(text_resp)
        
        # Expecting {"watchlist": [...]} or just [...]
        if isinstance(parsed, dict):
            for key, val in parsed.items():
                if isinstance(val, list):
                    watchlist = val
                    break
        elif isinstance(parsed, list):
            watchlist = parsed
            
        if watchlist:
            supabase = get_supabase_client()
            now = datetime.now(timezone.utc).isoformat()
            
            # Format according to our table schema
            to_insert = []
            for item in watchlist[:5]: # Ensure max 5 as requested
                to_insert.append({
                    "symbol": item.get('symbol'),
                    "reason": item.get('reason'),
                    "key_levels": item.get('key_levels'),
                    "risk_factors": item.get('risk_factors'),
                    "opportunity_type": item.get('opportunity_type'),
                    "created_at": now
                })
            
            if to_insert:
                supabase.table('watchlist').insert(to_insert).execute()
                logger.info(f"Successfully saved {len(to_insert)} stocks to holiday watchlist.")
            
    except Exception as e:
        msg = f"Error generating holiday watchlist: {e}"
        logger.error(msg)
        log_error_to_db("generate_holiday_watchlist", msg)
    
    return watchlist

def query_openai(top_20: list, market_context: dict) -> tuple[list, str]:
    """Step 4: Send top 20 to OpenAI API. Returns (trades, prompt)"""
    update_scan_progress("Querying OpenAI for trade selection...", 70)
    logger.info("Querying OpenAI API...")
    trades = []
    try:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        vix_instruction = market_context.get('vix_instruction', "Select best intraday and swing trades normally.")
        
        # Build live price context string for each stock
        live_price_lines = []
        for s in top_20:
            lp = s.get('live_price')
            if lp:
                live_price_lines.append(f"  - {s['symbol']}: ₹{lp}")
        live_price_context = (
            "LIVE PRICES (fetched right now via yfinance):\n" + "\n".join(live_price_lines)
            if live_price_lines else ""
        )
        
        prompt = (
            f"Market Context: {json.dumps(market_context)}\n"
            f"Top 20 Stocks: {json.dumps(top_20)}\n"
            f"{live_price_context}\n"
        )
        
        system_content = (
            "You are an expert NSE/BSE trader. Select maximum 6 high conviction trades from this list. "
            f"VOLATILITY RULE: {vix_instruction} "
            "For each trade return JSON with these fields: symbol, signal (BUY or SELL), entry, sl, t1, t2, t3, rr_ratio, confidence, reasoning, trade_type (INTRADAY or SWING). "
            "Apply these rules: minimum R:R 1:2, no BUY trades if SGX Nifty below -1%. "
            "CRITICAL PRICE RULE: Each stock in the list has a 'live_price' field showing its CURRENT market price fetched right now. "
            "Your entry price for each trade MUST be within 1% of the stock's live_price. "
            "Do NOT suggest entries far from the current market price — this causes stale trade errors. "
            "Example: if live_price is ₹3420, your entry must be between ₹3386 and ₹3454. "
            "IMPORTANT: You MUST return a JSON list of at least 3 high conviction trades. If you cannot find good BUY trades due to market conditions, look for high-conviction SELL/SHORT opportunities on the provided list. "
            "For SWING trades (3-7 days holding), include a 'holding_period' field. Return JSON array only, no other text."
        )
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_content},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=1500
        )
        
        # We need to extract the array, as OpenAI might return a json object with trades array
        text_resp = response.choices[0].message.content.strip()
        
        print(f"\n--- GPT-4o RAW PROMPT ---")
        print(system_content + "\n\n" + prompt)
        print("--------------------------\n")
        
        print(f"\n--- GPT-4o RAW RESPONSE ---")
        print(text_resp)
        print("----------------------------\n")
        
        try:
            parsed = json.loads(text_resp)
            if isinstance(parsed, dict):
                # Check if it's a single trade object directly
                if 'symbol' in parsed and 'signal' in parsed:
                    trades = [parsed]
                else:
                    # Look for a list in any key (e.g. {"trades": [...]})
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
    
    return trades, system_content + "\n\n" + prompt

def apply_kill_rules(trades: list, market_context: dict) -> tuple:
    """Step 5: Apply kill rules programmatically"""
    logger.info("Applying kill rules...")
    approved = []
    killed = []
    
    vix = market_context.get('vix', 0.0)
    sgx = market_context.get('sgx_nifty_pct', 0.0)
    multiplier = market_context.get('position_multiplier', 1.0)
    
    large_caps = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK", "SBIN", "BAJFINANCE", "KOTAKBANK", "AXISBANK", "LT", "HINDUNILVR", "WIPRO", "HCLTECH", "NTPC", "MARUTI"]
    
    for t in trades:
        try:
            symbol = t.get('symbol')
            signal = t.get('signal', '').upper()
            rr = float(t.get('rr_ratio', 0.0))
            entry = float(t.get('entry', 0.0))
            trade_type = t.get('trade_type', 'INTRADAY').upper()
            
            # Attach position multiplier to the trade
            t['position_multiplier'] = multiplier
            
            # Determine RR threshold based on VIX regime
            if vix >= 25:
                min_rr = 1.3
            elif vix >= 20:
                min_rr = 1.5
            else:
                min_rr = 2.0
            
            reason = None
            if rr < min_rr:
                reason = f"R:R ratio {rr} is below {min_rr} (VIX: {vix})"
            elif sgx < -1.0 and signal == "BUY":
                reason = f"SGX Nifty {sgx}% < -1% for BUY trade"
            elif 20 <= vix < 25 and symbol not in large_caps:
                reason = f"High VIX {vix} - Large cap trades only"
            elif 25 <= vix < 30 and signal == "BUY":
                 # We rely on GPT to judge 'exceptional strength', but as a safety:
                 if t.get('confidence', 0) < 0.9:
                    reason = f"Extreme VIX {vix} - BUY trades restricted to exceptional strength"
            elif vix >= 30 and trade_type == "INTRADAY":
                reason = f"Panic Mode VIX {vix} - All intraday trades killed"
            else:
                try:
                    # Fix 2 — Replace TATAMOTORS.NS with TATAMOTORS.BO
                    ticker_symbol = symbol + ".NS"
                    if symbol == "TATAMOTORS":
                        ticker_symbol = "TATAMOTORS.BO"
                    
                    ticker = yf.Ticker(ticker_symbol)
                    # Use live_price already attached to the trade if available, else fetch
                    live_price = t.get('live_price')
                    if not live_price:
                        hist = ticker.history(period="1d")
                        if not hist.empty:
                            live_price = float(hist['Close'].iloc[-1])
                    if live_price:
                        move_pct = abs(live_price - entry) / entry
                        if move_pct > 0.01:
                            reason = f"Stock moved {round(move_pct*100, 2)}% from entry (>1% — entry is stale vs live price ₹{live_price})"
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
            
    kill_summary = ""
    if killed:
        kill_summary = "\n".join([f"{t.get('symbol')}: {t.get('kill_reason')}" for t in killed])
    else:
        kill_summary = "All suggested trades approved."
        
    return approved, killed, kill_summary

def save_to_database(approved: list, killed: list, context: dict, stocks_scanned: int, gpt_prompt: str = None, kill_summary: str = None):
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
            # Remove keys that might not exist in the database schema
            for t in all_trades:
                t.pop('kill_reason', None)
            
            supabase.table('trades').insert(all_trades).execute()
            logger.info("Successfully saved trades to Supabase.")
            
        # Also saving raw market_context with summary stats
        supabase.table('market_context').insert({
            "context_data": {
                **context,
                "stocks_scanned": stocks_scanned,
                "trades_staged": len(approved),
                "trades_killed": len(killed),
                "scan_type": "LIVE",
                "gpt_prompt": gpt_prompt,
                "kill_summary": kill_summary
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
    update_scan_progress("Starting pre-market scan...", 5)
    logger.info("=== STARTING PRE-MARKET SCAN ===")
    
    # Step 1: Check holidays
    is_holiday, reason = is_market_holiday_or_weekend()
    
    if is_holiday:
        next_day = get_next_trading_day()
        logger.info(f"Market closed due to {reason}. Generating Next Session Watchlist...")
        
        # Still run the analysis path for watchlist
        per_stock_sentiment = run_news_scraper()
        top_20 = score_nifty_500(per_stock_sentiment)
        
        # Generate the special watchlist
        generate_holiday_watchlist(top_20)
        
        # Save this status to Supabase holiday_logs and market_context
        try:
            supabase = get_supabase_client()
            now = datetime.now(timezone.utc).isoformat()
            supabase.table('holiday_logs').insert({
                "status": "WATCHLIST_GENERATED",
                "reason": reason,
                "created_at": now
            }).execute()
            
            # Unified status in market_context for frontend
            supabase.table('market_context').insert({
                "context_data": {
                    "scan_type": "HOLIDAY_WATCHLIST",
                    "reason": reason,
                    "stocks_scanned": len(KNOWN_SYMBOLS),
                    "trades_staged": 0,
                    "trades_killed": 0
                },
                "created_at": now
            }).execute()
            
            logger.info(f"Successfully logged holiday watchlist status for {reason}")
        except Exception as e:
            logger.error(f"Failed to log holiday status to DB: {e}")
            
        logger.info("=== PRE-MARKET SCAN COMPLETE (HOLIDAY) ===")
        return
    
    update_scan_progress("Fetching market context (VIX, SGX Nifty)...", 10)
    context = fetch_market_context()
    
    update_scan_progress("Running news scraper and sentiment analysis...", 20)
    per_stock_sentiment = run_news_scraper()
    
    update_scan_progress("Scoring Nifty 500 stocks...", 40)
    
    # Bug Fix: If VIX is high (20-25), we MUST only send the 15 large caps requested in the prompt.
    vix = context.get('vix', 0.0)
    symbols_to_score = None
    if 20 <= vix < 25:
        large_caps = ["RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK", "SBIN", "BAJFINANCE", "KOTAKBANK", "AXISBANK", "LT", "HINDUNILVR", "WIPRO", "HCLTECH", "NTPC", "MARUTI"]
        symbols_to_score = [s for s in KNOWN_SYMBOLS if s in large_caps]
        logger.info(f"VIX is {vix} (High Volatility). Restricting universe to {len(symbols_to_score)} large caps.")
    
    top_20 = score_nifty_500(per_stock_sentiment, symbols=symbols_to_score)
    
    update_scan_progress("Fetching live prices for top stocks...", 60)
    top_20 = fetch_live_prices(top_20)
    
    trades, prompt = query_openai(top_20, context)
    
    update_scan_progress("Applying kill rules and risk management...", 85)
    approved, killed, kill_summary = apply_kill_rules(trades, context)
    
    update_scan_progress("Saving results to database...", 95)
    save_to_database(approved, killed, context, stocks_scanned=len(KNOWN_SYMBOLS), gpt_prompt=prompt, kill_summary=kill_summary)
    
    update_scan_progress("Scan complete.", 100)
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
