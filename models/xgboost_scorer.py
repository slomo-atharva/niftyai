import os
import logging
import pandas as pd
import numpy as np
import xgboost as xgb
import joblib
from dotenv import load_dotenv
from supabase import create_client
from sklearn.metrics import accuracy_score, precision_score, recall_score

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


def get_supabase_client():
    """Return a supabase-py REST client using HTTPS (port 443)."""
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in environment")
    return create_client(url, key)

def load_data() -> pd.DataFrame:
    """Loads daily prices from Supabase via REST API (HTTPS port 443).
    
    Uses paginated supabase-py queries instead of direct SQLAlchemy connection
    so this works on GitHub Actions where PostgreSQL port 5432 is blocked.
    """
    logger.info("Loading daily_prices from Supabase REST API...")
    try:
        supabase = get_supabase_client()
        
        all_rows = []
        page_size = 1000
        offset = 0
        
        while True:
            response = (
                supabase.table('daily_prices')
                .select('symbol, date, open, high, low, close, volume, delivery_pct')
                .order('symbol')
                .order('date')
                .range(offset, offset + page_size - 1)
                .execute()
            )
            batch = response.data
            if not batch:
                break
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
            logger.info(f"Fetched {len(all_rows)} rows so far...")
        
        if not all_rows:
            logger.warning("No data returned from daily_prices table.")
            return pd.DataFrame()
        
        df = pd.DataFrame(all_rows)
        
        # --- URGENT DEBUG & FIX ---
        print(f"XGBoost Debug - Loaded {len(df)} rows")
        print(f"XGBoost Debug - Columns: {df.columns.tolist()}")
        if not df.empty:
            print(f"XGBoost Debug - First row: {df.iloc[0].to_dict()}")
        
        # Normalise columns to lowercase to ensure consistency (handles 'Symbol' vs 'symbol')
        df.columns = [c.lower() for c in df.columns]
        
        print(f"XGBoost Debug - Sample symbols: {df['symbol'].unique()[:5] if 'symbol' in df.columns else 'SYMBOL COL MISSING'}")
        # -------------------------

        df['date'] = pd.to_datetime(df['date'])
        
        # If delivery_pct doesn't exist or is mostly null, fill with 0
        if 'delivery_pct' not in df.columns:
            logger.warning("'delivery_pct' column not found, filling with 0")
            df['delivery_pct'] = 0.0
        else:
            df['delivery_pct'] = df['delivery_pct'].fillna(0.0)
            
        logger.info(f"Loaded {len(df)} rows of daily_prices data")
        return df
    except Exception as e:
        logger.error(f"Failed to load data from Supabase: {e}")
        raise

def compute_rsi(data: pd.Series, window: int = 14) -> pd.Series:
    delta = data.diff()
    up = delta.clip(lower=0)
    down = -1 * delta.clip(upper=0)
    ema_up = up.ewm(com=window - 1, adjust=False).mean()
    ema_down = down.ewm(com=window - 1, adjust=False).mean()
    rs = ema_up / ema_down
    return 100 - (100 / (1 + rs))

def compute_atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.ewm(alpha=1/window, min_periods=window).mean()

def engineer_features(df: pd.DataFrame) -> pd.DataFrame:
    """Calculates all technical indicators per stock"""
    logger.info("Computing technical features...")
    
    def process_group(g):
        g = g.sort_values('date').copy()
        
        # 1. RSI 14
        g['rsi_14'] = compute_rsi(g['close'], 14)
        
        # 2. MACD
        ema_12 = g['close'].ewm(span=12, adjust=False).mean()
        ema_26 = g['close'].ewm(span=26, adjust=False).mean()
        g['macd_line'] = ema_12 - ema_26
        g['macd_signal'] = g['macd_line'].ewm(span=9, adjust=False).mean()
        g['macd_hist'] = g['macd_line'] - g['macd_signal']
        
        # 3. Bollinger Bands
        sma_20 = g['close'].rolling(window=20).mean()
        std_20 = g['close'].rolling(window=20).std()
        g['bb_upper'] = sma_20 + (std_20 * 2)
        g['bb_lower'] = sma_20 - (std_20 * 2)
        # Position within bands (0 = at lower band, 1 = at upper band)
        g['bb_pos'] = np.where(g['bb_upper'] == g['bb_lower'], 0, 
                             (g['close'] - g['bb_lower']) / (g['bb_upper'] - g['bb_lower']))
        
        # 4. Volume Ratio vs 20d average
        vol_sma_20 = g['volume'].rolling(window=20).mean()
        g['vol_ratio_20d'] = np.where(vol_sma_20 == 0, 0, g['volume'] / vol_sma_20)
        
        # 5. Price position vs DMA
        g['price_vs_20dma'] = np.where(sma_20 == 0, 0, g['close'] / sma_20 - 1)
        sma_50 = g['close'].rolling(window=50).mean()
        g['price_vs_50dma'] = np.where(sma_50 == 0, 0, g['close'] / sma_50 - 1)
        sma_200 = g['close'].rolling(window=200).mean()
        g['price_vs_200dma'] = np.where(sma_200 == 0, 0, g['close'] / sma_200 - 1)
        
        # 6. ATR 14
        g['atr_14'] = compute_atr(g, 14)
        
        # 7. OBV (On-Balance Volume)
        obv = np.where(g['close'] > g['close'].shift(1), g['volume'], 
               np.where(g['close'] < g['close'].shift(1), -g['volume'], 0))
        g['obv'] = pd.Series(obv, index=g.index).cumsum()
        
        # Raw features like delivery_pct are already present
        return g
    
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        df = df.groupby('symbol', group_keys=False).apply(process_group).reset_index(drop=True)
    return df

def create_target(df: pd.DataFrame) -> pd.DataFrame:
    """Creates the target variable: 1 if next day close > 1.5% up"""
    logger.info("Creating target variable...")
    
    # Next day close
    df['next_close'] = df.groupby('symbol')['close'].shift(-1)
    
    # Calculate % change
    df['next_day_pct_change'] = (df['next_close'] / df['close']) - 1
    
    # Target: > 1.5%
    df['target'] = (df['next_day_pct_change'] > 0.015).astype(int)
    
    # Drop rows where next_close is NaN (the last day of each stock)
    df = df.dropna(subset=['next_close'])
    
    return df

def prepare_data(df: pd.DataFrame):
    """Handles splitting and feature selection based on time"""
    logger.info("Preparing data splits (time-based)...")
    
    features = [
        'rsi_14', 'macd_line', 'macd_signal', 'macd_hist', 
        'bb_pos', 'vol_ratio_20d', 'price_vs_20dma', 'price_vs_50dma', 
        'price_vs_200dma', 'atr_14', 'obv', 'delivery_pct'
    ]
    
    # Drop NaNs from computing rolling features
    df = df.dropna(subset=features)
    
    # Sort entire dataset chronologically
    df = df.sort_values('date')
    
    n = len(df)
    train_idx = int(n * 0.70)
    val_idx = int(n * 0.85)
    
    df_train = df.iloc[:train_idx]
    df_val = df.iloc[train_idx:val_idx]
    df_test = df.iloc[val_idx:]
    
    logger.info(f"Train samples: {len(df_train)}")
    logger.info(f"Val samples:   {len(df_val)}")
    logger.info(f"Test samples:  {len(df_test)}")
    
    if len(df_test) > 0:
        logger.info(f"Test dates: {df_test['date'].min().date()} to {df_test['date'].max().date()}")
    
    X_train, y_train = df_train[features], df_train['target']
    X_val, y_val = df_val[features], df_val['target']
    X_test, y_test = df_test[features], df_test['target']
    
    return X_train, y_train, X_val, y_val, X_test, y_test, features

def train_and_evaluate():
    df = load_data()
    df = engineer_features(df)
    df = create_target(df)
    
    X_train, y_train, X_val, y_val, X_test, y_test, features = prepare_data(df)
    
    # Calculate pos weight to handle class imbalance
    pos_cases = y_train.sum()
    neg_cases = len(y_train) - pos_cases
    scale_pos_weight = neg_cases / max(1, pos_cases)
    logger.info(f"Class imbalance handling: scale_pos_weight = {scale_pos_weight:.2f}")
    
    logger.info("Training XGBoost model...")
    model = xgb.XGBClassifier(
        n_estimators=500,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.8,
        colsample_bytree=0.8,
        eval_metric='logloss',
        scale_pos_weight=scale_pos_weight,
        early_stopping_rounds=50,
        random_state=42
    )
    
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        verbose=False
    )

    
    logger.info(f"Best iteration: {model.best_iteration}")
    
    logger.info("Evaluating on test set...")
    y_pred = model.predict(X_test)
    
    acc = accuracy_score(y_test, y_pred)
    prec = precision_score(y_test, y_pred, zero_division=0)
    rec = recall_score(y_test, y_pred, zero_division=0)
    
    logger.info(f"Test Accuracy:  {acc:.4f}")
    logger.info(f"Test Precision: {prec:.4f}")
    logger.info(f"Test Recall:    {rec:.4f}")
    
    current_file_path = os.path.dirname(os.path.abspath(__file__))
    save_dir = os.path.join(current_file_path, "saved")
    os.makedirs(save_dir, exist_ok=True)
    save_path = os.path.join(save_dir, "xgboost_nifty.pkl")
    
    if acc >= 0.62:
        logger.info("Accuracy >= 62%. Saving model...")
        joblib.dump({"model": model, "features": features}, save_path)
        logger.info(f"Model saved to {save_path}")
    else:
        logger.warning(f"Accuracy {acc:.4f} is below 62% threshold. Model NOT saved.")
        
if __name__ == "__main__":
    train_and_evaluate()
