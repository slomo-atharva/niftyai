import os
import sys
from datetime import datetime, timezone
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import subprocess

# Add parent directory to path to allow importing local modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.news_scraper import get_supabase_client

app = FastAPI(title="NiftyAI Trading Agent API")

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
    """Returns last pre_market_scan.py run time, how many trades were staged, and VIX + SGX Nifty values from that run"""
    try:
        supabase = get_db()
        mc_response = supabase.table('market_context').select('*').order('created_at', desc=True).limit(1).execute()
        
        last_run_time = None
        vix = None
        sgx_nifty = None
        staged_count = 0
        
        if mc_response.data:
            latest = mc_response.data[0]
            last_run_time = latest.get('created_at')
            context_data = latest.get('context_data', {})
            vix = context_data.get('vix')
            sgx_nifty = context_data.get('sgx_nifty_value')
            
            if last_run_time:
                date_part = last_run_time.split('T')[0]
                trades_resp = supabase.table('trades').select('*', count='exact').gte('created_at', date_part).eq('status', 'APPROVED').execute()
                staged_count = trades_resp.count if trades_resp.count is not None else len(trades_resp.data)
        
        return {
            "last_run_time": last_run_time,
            "staged_trades_count": staged_count,
            "vix": vix,
            "sgx_nifty": sgx_nifty
        }
    except Exception as e:
        return handle_db_error(e, {
            "last_run_time": None,
            "staged_trades_count": 0,
            "vix": None,
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
        script_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "agent", "pre_market_scan.py")
        subprocess.run([sys.executable, script_path, "--run-now"])
    
    background_tasks.add_task(task)
    return {"status": "Agent execution started"}
