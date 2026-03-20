"""
LSTM Time-Series Model for Stock Movement Prediction (v9).

Improvements:
1. 1-day prediction target (cleaner signal).
2. Extra features: FinBERT sentiment, Nifty 50 direction, RSI, MACD.
3. Architecture: 1 LSTM layer (prevents overfitting).
4. Window: 30 days lookback.
5. Confidence weight: Saved anyway with 0.6 if acc < 60%.
"""
from __future__ import annotations

import os
import logging
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader
from sqlalchemy import create_engine
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_score, recall_score
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

load_dotenv()
DATABASE_URL: str = os.getenv("DATABASE_URL", "")
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Hyper-parameters
SEQ_LEN = 30           # 30-day window
FORECAST_HORIZON = 1   # 1-day prediction
HIDDEN_SIZE = 128
NUM_LAYERS = 1         # 1 LSTM layer
DROPOUT = 0.2
BATCH_SIZE = 64
LR = 0.001
MAX_EPOCHS = 100
PATIENCE = 15
TARGET_ACCURACY = 0.60 # New target threshold

FEATURES = [
    "open", "high", "low", "close", "volume", 
    "rsi", "macd", "nifty_dir", "sentiment"
]

# ---------------------------------------------------------------------------
# Data Loading & Engineering
# ---------------------------------------------------------------------------

def compute_rsi(series, period=14):
    delta = series.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=period-1, adjust=False).mean()
    ema_down = down.ewm(com=period-1, adjust=False).mean()
    rs = ema_up / (ema_down + 1e-9)
    return 100 - (100 / (1 + rs))

def compute_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd = exp1 - exp2
    return macd

def load_data_v9() -> pd.DataFrame:
    import yfinance as yf
    
    # 1. Fetch Nifty 50 Index (5y)
    logger.info("Fetching NIFTY ^NSEI index data...")
    nifty = yf.download("^NSEI", period="5y", progress=False)
    nifty.columns = nifty.columns.get_level_values(0) if isinstance(nifty.columns, pd.MultiIndex) else nifty.columns
    nifty.reset_index(inplace=True)
    nifty["Date"] = pd.to_datetime(nifty["Date"]).dt.tz_localize(None)
    nifty["nifty_dir"] = (nifty["Close"].pct_change() > 0).astype(int)
    nifty = nifty[["Date", "nifty_dir"]]
    nifty.columns = ["date", "nifty_dir"]

    # 2. Fetch Sentiment from Database
    sentiment_df = pd.DataFrame()
    if DATABASE_URL:
        try:
            engine = create_engine(DATABASE_URL)
            query = """
                SELECT symbol, DATE(created_at) as date, 
                       AVG(bullish - bearish) as sentiment
                FROM news_sentiment
                GROUP BY symbol, DATE(created_at)
            """
            sentiment_df = pd.read_sql(query, engine)
            sentiment_df["date"] = pd.to_datetime(sentiment_df["date"])
            logger.info(f"Loaded {len(sentiment_df)} sentiment records")
        except Exception as e:
            logger.warning(f"Failed to load sentiment: {e}")

    # 3. Fetch Stock History (~50 liquid stocks)
    symbols = [
        "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ICICIBANK.NS",
        "HINDUNILVR.NS", "SBIN.NS", "ITC.NS", "BHARTIARTL.NS", "KOTAKBANK.NS",
        "LT.NS", "AXISBANK.NS", "BAJFINANCE.NS", "HCLTECH.NS", "ASIANPAINT.NS",
        "MARUTI.NS", "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "NTPC.NS",
        "M&M.NS", "POWERGRID.NS", "TATAMOTORS.BO", "TECHM.NS", "ONGC.NS", 
        "COALINDIA.NS", "GRASIM.NS", "CIPLA.NS", "DRREDDY.NS", "WIPRO.NS"
    ]
    
    logger.info(f"Fetching {len(symbols)} stocks history (5y)...")
    data = yf.download(symbols, period="5y", progress=False)
    
    all_dfs = []
    for sym in symbols:
        try:
            s_data = data.xs(sym, level=1, axis=1).copy()
            s_data.reset_index(inplace=True)
            s_data["Date"] = pd.to_datetime(s_data["Date"]).dt.tz_localize(None)
            s_data["symbol"] = f"NSE:{sym.replace('.NS', '')}-EQ"
            s_data = s_data[["symbol", "Date", "Open", "High", "Low", "Close", "Volume"]].dropna()
            s_data.columns = ["symbol", "date", "open", "high", "low", "close", "volume"]
            
            s_data = s_data.sort_values("date")
            s_data["rsi"] = compute_rsi(s_data["close"])
            s_data["macd"] = compute_macd(s_data["close"])
            s_data.dropna(inplace=True)
            all_dfs.append(s_data)
        except Exception: continue
            
    df = pd.concat(all_dfs, ignore_index=True)
    
    # 4. Merge Nifty and Sentiment
    df = pd.merge(df, nifty, on="date", how="left")
    if not sentiment_df.empty:
        df = pd.merge(df, sentiment_df, on=["symbol", "date"], how="left")
    else:
        df["sentiment"] = 0.0
    
    df["sentiment"] = df["sentiment"].fillna(0.0)
    df["nifty_dir"] = df["nifty_dir"].fillna(0).astype(int)
    
    logger.info(f"Dataset ready: {len(df)} rows across {df['symbol'].nunique()} stocks")
    return df

# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

class StockDataset(Dataset):
    def __init__(self, X, y):
        self.X = torch.tensor(X, dtype=torch.float32); self.y = torch.tensor(y, dtype=torch.float32)
    def __len__(self): return len(self.X)
    def __getitem__(self, i): return self.X[i], self.y[i]

class LSTMNet(nn.Module):
    def __init__(self, feat_size):
        super().__init__()
        # Simplified to 1 layer
        self.lstm = nn.LSTM(feat_size, HIDDEN_SIZE, num_layers=1, batch_first=True)
        self.fc = nn.Linear(HIDDEN_SIZE, 1)
    def forward(self, x):
        o, _ = self.lstm(x)
        return torch.sigmoid(self.fc(o[:, -1, :])).view(-1)

def run_v9():
    df = load_data_v9()
    
    # Chronological Split
    dates = sorted(df["date"].unique())
    t1 = dates[int(len(dates) * 0.70)]; t2 = dates[int(len(dates) * 0.85)]
    
    X_train, y_train = [], []
    X_val, y_val = [], []
    X_test, y_test = [], []

    for _, grp in df.groupby("symbol"):
        grp = grp.sort_values("date")
        if len(grp) < SEQ_LEN + FORECAST_HORIZON: continue
        
        # Norm per stock history
        normed = StandardScaler().fit_transform(grp[FEATURES])
        closes = grp["close"].values
        grp_dates = grp["date"].values
        
        for i in range(SEQ_LEN, len(grp) - FORECAST_HORIZON):
            seq = normed[i-SEQ_LEN : i]
            # 1-day prediction target
            target = 1 if closes[i+FORECAST_HORIZON] > closes[i] else 0
            
            d = grp_dates[i]
            if d < t1: X_train.append(seq); y_train.append(target)
            elif d < t2: X_val.append(seq); y_val.append(target)
            else: X_test.append(seq); y_test.append(target)

    X_tr, y_tr = np.array(X_train), np.array(y_train)
    X_va, y_va = np.array(X_val), np.array(y_val)
    X_te, y_te = np.array(X_test), np.array(y_test)
    
    logger.info(f"Train: {len(X_tr)} | Val: {len(X_va)} | Test: {len(X_te)}")
    
    model = LSTMNet(len(FEATURES)).to(DEVICE)
    crit = nn.BCELoss()
    opt = torch.optim.Adam(model.parameters(), lr=LR)
    
    best_acc = 0
    best_state = None
    patience_cnt = 0
    
    logger.info("Starting Training v9...")
    for epoch in range(1, MAX_EPOCHS + 1):
        model.train()
        for xb, yb in DataLoader(StockDataset(X_tr, y_tr), BATCH_SIZE, shuffle=True):
            opt.zero_grad()
            crit(model(xb.to(DEVICE)), yb.to(DEVICE)).backward()
            opt.step()
        
        model.eval(); p = []
        with torch.no_grad():
            for xb, _ in DataLoader(StockDataset(X_va, y_va), BATCH_SIZE):
                p.extend((model(xb.to(DEVICE)).cpu().numpy() >= 0.5).astype(int))
        acc = accuracy_score(y_va, p)
        
        if acc > best_acc:
            best_acc = acc; best_state = {k: v.clone() for k,v in model.state_dict().items()}; patience_cnt = 0
        else:
            patience_cnt += 1
            if patience_cnt >= PATIENCE: break
            
        logger.info(f"Epoch {epoch:02d} Val Acc: {acc:.4f} (Best: {best_acc:.4f})")
        if acc >= TARGET_ACCURACY: break

    model.load_state_dict(best_state)
    model.eval(); p = []
    with torch.no_grad():
        for xb, _ in DataLoader(StockDataset(X_te, y_te), BATCH_SIZE):
            p.extend((model(xb.to(DEVICE)).cpu().numpy() >= 0.5).astype(int))
            
    f_acc = accuracy_score(y_te, p)
    f_prec = precision_score(y_te, p, zero_division=0)
    f_rec = recall_score(y_te, p, zero_division=0)
    
    logger.info(f"FINAL TEST ACCURACY: {f_acc:.4f}")
    
    # Save Logic: Always save, but add confidence_weight if < 60%
    current_file_path = os.path.dirname(os.path.abspath(__file__))
    save_path = os.path.join(current_file_path, "saved", "lstm_model.pth")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    
    confidence_weight = 1.0 if f_acc >= TARGET_ACCURACY else 0.6
    
    torch.save({
        "model_state": model.state_dict(),
        "accuracy": f_acc,
        "precision": f_prec,
        "recall": f_rec,
        "confidence_weight": confidence_weight,
        "features": FEATURES,
        "seq_len": SEQ_LEN
    }, save_path)
    
    logger.info(f"Model saved to {save_path} (Accuracy: {f_acc:.4f}, Weight: {confidence_weight})")

if __name__ == "__main__":
    run_v9()
