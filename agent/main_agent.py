import os
import sys
import logging
import joblib
import pandas as pd
from transformers import pipeline
import warnings
warnings.filterwarnings('ignore')

# Add parent dir to path so we can import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logger = logging.getLogger(__name__)

from models.saved.momentum_scorer import MomentumScorer
from models.xgboost_scorer import load_data, engineer_features

def get_xgboost_scores(symbols: list) -> dict:
    """Score each symbol using the saved XGBoost model.
    
    Symbols should be plain NSE symbols like 'RELIANCE', 'TCS'.
    The function converts them to Fyers format 'NSE:RELIANCE-EQ' for DB lookup.
    Returns a dict of {symbol: float} where float is P(next-day > +1.5%).
    Falls back to 0.5 on any error.
    """
    logger.info(f"Running XGBoost scoring for {len(symbols)} symbols...")
    
    # Step 1: Load and engineer features from Supabase
    try:
        df = load_data()
        if df.empty:
            logger.error("XGBoost: daily_prices table is empty or inaccessible. All scores defaulting to 0.5.")
            return {sym: 0.5 for sym in symbols}
        df = engineer_features(df)
        logger.info(f"XGBoost: Engineered features for {df['symbol'].nunique()} symbols.")
    except Exception as e:
        logger.error(f"XGBoost: Failed to load/engineer data: {e}. All scores defaulting to 0.5.")
        return {sym: 0.5 for sym in symbols}
    
    # Step 2: Load model
    try:
        current_file_path = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(current_file_path)
        model_path = os.path.join(root_dir, "models", "saved", "xgboost_nifty.pkl")
        model_data = joblib.load(model_path)
        model = model_data['model']
        features = model_data['features']
        logger.info(f"XGBoost: Model loaded from {model_path}")
    except Exception as e:
        logger.error(f"XGBoost: Failed to load model: {e}. All scores defaulting to 0.5.")
        return {sym: 0.5 for sym in symbols}
    
    # Step 3: Score each symbol
    scores = {}
    for symbol in symbols:
        try:
            # DB stores symbols in Fyers format: NSE:RELIANCE-EQ
            fyers_sym = f"NSE:{symbol.replace('.NS', '')}-EQ"
            stock_df = df[df['symbol'] == fyers_sym].copy()
            
            if stock_df.empty:
                logger.warning(f"XGBoost: No DB data for '{fyers_sym}' — score defaults to 0.5")
                scores[symbol] = 0.5
                continue
            
            # Fix deprecated fillna: use ffill() then fill 0 for remaining NaN
            stock_df = stock_df.ffill().fillna(0)
            last_row = stock_df.iloc[-1:][features]
            
            # XGBoost predict_proba (class 1 = next-day close > +1.5%)
            proba = model.predict_proba(last_row)[0][1]
            scores[symbol] = float(proba)
            logger.info(f"XGBoost: {symbol} ({fyers_sym}) → score={proba:.4f}")
            
        except Exception as e:
            logger.error(f"XGBoost: Error scoring {symbol}: {e} — defaulting to 0.5")
            scores[symbol] = 0.5
    
    differentiated = {k: v for k, v in scores.items() if v != 0.5}
    logger.info(f"XGBoost: Scored {len(differentiated)}/{len(symbols)} stocks with real predictions.")
    return scores

def get_finbert_scores(symbols):
    nlp = pipeline("sentiment-analysis", model="ProsusAI/finbert")
    scores = {}
    for symbol in symbols:
        # Dummy test headlines to show sentiment integration
        res = nlp(f"{symbol} announces market beating strong quarterly results and growth.")[0]
        if res['label'] == 'positive':
            scores[symbol] = res['score']
        elif res['label'] == 'negative':
            scores[symbol] = 1.0 - res['score']
        else:
            scores[symbol] = 0.5
    return scores

def run_agent():
    symbols = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS", 
               "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "LT.NS", "BAJFINANCE.NS"]
               
    print("Initializing MomentumScorer...")
    momentum = MomentumScorer()
    
    print("Getting XGBoost scores from Supabase historical data...")
    xgb_scores = get_xgboost_scores(symbols)
    
    print("Getting FinBERT sentiment scores...")
    finbert_scores = get_finbert_scores(symbols)
    
    print("\n--- FINAL ENSEMBLE SCORES ---")
    print(f"{'Symbol':<15} | {'XGB (60%)':<10} | {'Mom Raw':<10} | {'Mom Norm':<10} | {'FinB (15%)':<10} | {'Total Score':<10}")
    print("-" * 80)
    
    for sym in symbols:
        xgb_val = xgb_scores.get(sym, 0.5)
        mom_val = momentum.get_score(sym)
        # Normalize Mom to 0.0 - 1.0 (raw is -1 to 4)
        norm_mom = (mom_val + 1) / 5.0
        fin_val = finbert_scores.get(sym, 0.5)
        
        final_score = (xgb_val * 0.60) + (norm_mom * 0.25) + (fin_val * 0.15)
        
        print(f"{sym:<15} | {xgb_val:<10.2f} | {mom_val:<10.2f} | {norm_mom:<10.2f} | {fin_val:<10.2f} | {final_score:<10.2f}")

if __name__ == "__main__":
    run_agent()
