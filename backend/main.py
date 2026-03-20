import os
import sys
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
import subprocess
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

# ---------------------------------------------------------------------------
# Lightweight Supabase client — does NOT import the heavy agent/news_scraper
# (which transitively loads PyTorch, FinBERT, Transformers, etc.)
# ---------------------------------------------------------------------------
def get_supabase_client() -> Client:
    """Initialise and return a Supabase client from environment variables."""
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set as environment variables")
    return create_client(url, key)

app = FastAPI(title="NiftyAI Trading Agent API")

from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    try:
        return get_supabase_client()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

def handle_db_error(e, default_return):
    if "PGRST205" in str(e):
        return default_return
    raise HTTPException(status_code=500, detail=f"Database error: {e}")

@app.get("/trades/today")
async def get_trades_today():
    """Returns today's staged trades from Supabase"""
    try:
        supabase = get_db()
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        response = supabase.table('trades').select('*').gte('created_at', today).eq('status', 'APPROVED').execute()
        return {"trades": response.data}
    except Exception as e:
        return handle_db_error(e, {"trades": []})

@app.get("/trades/history")
async def get_trades_history():
    """Returns all past trades with outcomes"""
    try:
        supabase = get_db()
        trades_resp = supabase.table('trades').select('*').execute()
        outcomes_resp = supabase.table('outcomes').select('*').execute()
        
        trades = trades_resp.data
        outcomes = {o['trade_id']: o for o in outcomes_resp.data} if outcomes_resp.data else {}
        
        for t in trades:
            t['outcome'] = outcomes.get(t.get('id'))
        
        return {"trades": trades}
    except Exception as e:
        return handle_db_error(e, {"trades": []})

@app.get("/agent/status")
async def get_agent_status():
    """Returns last pre_market_scan.py run time, how many trades were staged, and scan details"""
    try:
        supabase = get_db()
        # Fetch the latest record from market_context
        mc_response = supabase.table('market_context').select('*').order('created_at', desc=True).limit(1).execute()
        
        if mc_response.data:
            latest = mc_response.data[0]
            last_run_time = latest.get('created_at')
            context_data = latest.get('context_data', {})
            
            # Extract new fields from context_data
            stocks_scanned = context_data.get('stocks_scanned', 0)
            trades_staged = context_data.get('trades_staged', 0)
            trades_killed = context_data.get('trades_killed', 0)
            scan_type = context_data.get('scan_type', 'LIVE')
            vix = context_data.get('vix')
            vix_regime = context_data.get('vix_regime')
            vix_message = context_data.get('vix_message')
            sgx_nifty = context_data.get('sgx_nifty_value')
            
            # Fallback for older records that might not have these fields yet
            if not stocks_scanned and last_run_time:
                # If it's an old record, try to calculate staged_count like before
                date_part = last_run_time.split('T')[0]
                trades_resp = supabase.table('trades').select('*', count='exact').gte('created_at', date_part).eq('status', 'APPROVED').execute()
                trades_staged = trades_resp.count if trades_resp.count is not None else len(trades_resp.data)
            
            return {
                "last_run_time": last_run_time,
                "stocks_scanned": stocks_scanned,
                "trades_staged": trades_staged,
                "trades_killed": trades_killed,
                "scan_type": scan_type,
                "vix": vix,
                "vix_regime": vix_regime,
                "vix_message": vix_message,
                "sgx_nifty": sgx_nifty
            }
        
        return {
            "last_run_time": None,
            "stocks_scanned": 0,
            "trades_staged": 0,
            "trades_killed": 0,
            "scan_type": "UNKNOWN",
            "vix": None,
            "vix_regime": None,
            "vix_message": None,
            "sgx_nifty": None
        }
    except Exception as e:
        return handle_db_error(e, {
            "last_run_time": None,
            "stocks_scanned": 0,
            "trades_staged": 0,
            "trades_killed": 0,
            "scan_type": "UNKNOWN",
            "vix": None,
            "vix_regime": None,
            "vix_message": None,
            "sgx_nifty": None
        })

@app.get("/signals")
async def get_signals():
    """Returns today's top 20 XGBoost + Momentum scores before Claude filtering"""
    try:
        supabase = get_db()
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        resp = supabase.table('signals').select('*').gte('created_at', today).order('combined_score', desc=True).limit(20).execute()
        return {"signals": resp.data}
    except Exception as e:
        return handle_db_error(e, {"signals": []})

@app.post("/agent/run")
async def run_agent(background_tasks: BackgroundTasks):
    """Manually triggers pre_market_scan.py immediately"""
    def task():
        try:
            # Use absolute path for reliability
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            script_path = os.path.join(base_dir, "agent", "pre_market_scan.py")
            
            print(f"Executing agent at: {script_path}")
            result = subprocess.run(
                [sys.executable, script_path, "--run-now"],
                capture_output=True,
                text=True,
                cwd=base_dir # Run from project root
            )
            if result.returncode != 0:
                print(f"Agent failed with exit code {result.returncode}")
                print(f"Stderr: {result.stderr}")
            else:
                print("Agent executed successfully")
        except Exception as e:
            print(f"Error triggering agent: {e}")
    
    background_tasks.add_task(task)
    return {"status": "Agent execution started"}

@app.get("/agent/debug")
async def get_agent_debug():
    """Returns debug info from the last scan: VIX, regime, kill reasons, and GPT prompt"""
    try:
        supabase = get_db()
        mc_response = supabase.table('market_context').select('*').order('created_at', desc=True).limit(1).execute()
        
        if mc_response.data:
            latest = mc_response.data[0]
            context_data = latest.get('context_data', {})
            
            return {
                "vix": context_data.get('vix'),
                "vix_regime": context_data.get('vix_regime'),
                "kill_summary": context_data.get('kill_summary', "No kill summary available."),
                "gpt_prompt": context_data.get('gpt_prompt', "No prompt recorded."),
                "created_at": latest.get('created_at')
            }
        
        raise HTTPException(status_code=404, detail="No scan data found")
    except Exception as e:
        return handle_db_error(e, {"error": str(e)})

@app.get("/watchlist")
async def get_watchlist():
    """Returns the latest holiday/weekend watchlist from Supabase"""
    try:
        supabase = get_db()
        # Fetch the latest 5 records from watchlist table
        response = supabase.table('watchlist').select('*').order('created_at', desc=True).limit(5).execute()
        return {"watchlist": response.data}
    except Exception as e:
        return handle_db_error(e, {"watchlist": []})

if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port)
