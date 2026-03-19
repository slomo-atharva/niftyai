import os
import sys
import joblib
import pandas as pd
from transformers import pipeline
import warnings
warnings.filterwarnings('ignore')

# Add parent dir to path so we can import models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.saved.momentum_scorer import MomentumScorer
from models.xgboost_scorer import load_data, engineer_features

def get_xgboost_scores(symbols):
    df = load_data()
    # we only need the latest feature row per stock
    df = engineer_features(df)
    
    # load model
    model_data = joblib.load("/Users/apple/Downloads/nifty stocks/models/saved/xgboost_nifty.pkl")
    model = model_data['model']
    features = model_data['features']
    
    scores = {}
    for symbol in symbols:
        try:
            fyers_sym = f"NSE:{symbol.replace('.NS', '')}-EQ"
            stock_df = df[df['symbol'] == fyers_sym].copy()
            if stock_df.empty:
                scores[symbol] = 0.5
                continue
            
            # fillna first if any
            stock_df = stock_df.fillna(method='ffill').fillna(0)
            last_row = stock_df.iloc[-1:][features]
            
            # XGBoost predict_proba (class 1 probability)
            proba = model.predict_proba(last_row)[0][1]
            scores[symbol] = float(proba)
        except Exception as e:
            scores[symbol] = 0.5
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
