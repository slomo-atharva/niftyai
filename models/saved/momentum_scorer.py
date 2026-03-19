import yfinance as yf
import pandas as pd
import numpy as np

class MomentumScorer:
    def __init__(self):
        pass

    def get_score(self, symbol: str) -> float:
        stock_df = yf.Ticker(symbol).history(period="6mo")
        if stock_df.empty or len(stock_df) < 50:
            return 0.0
        
        close_price = stock_df['Close'].iloc[-1]
        dma_20 = stock_df['Close'].rolling(window=20).mean().iloc[-1]
        dma_50 = stock_df['Close'].rolling(window=50).mean().iloc[-1]
        
        price_score = 0
        if close_price > dma_20:
            price_score += 1
        if close_price > dma_50:
            price_score += 1

        current_vol = stock_df['Volume'].iloc[-1]
        avg_vol_20 = stock_df['Volume'].rolling(window=20).mean().iloc[-1]
        vol_score = 1 if current_vol > avg_vol_20 else 0

        nifty_df = yf.Ticker("^NSEI").history(period="1mo")
        if len(nifty_df) >= 5 and len(stock_df) >= 5:
            stock_5d_ret = (stock_df['Close'].iloc[-1] / stock_df['Close'].iloc[-5]) - 1
            nifty_5d_ret = (nifty_df['Close'].iloc[-1] / nifty_df['Close'].iloc[-5]) - 1
            
            if stock_5d_ret > nifty_5d_ret:
                rs_score = 1
            elif stock_5d_ret < nifty_5d_ret:
                rs_score = -1
            else:
                rs_score = 0
        else:
            rs_score = 0

        return float(price_score + vol_score + rs_score)
