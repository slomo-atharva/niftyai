import yfinance as yf
import pandas as pd
import numpy as np

class TechnicalScorer:
    def __init__(self):
        pass

    def score(self, symbol: str) -> float:
        try:
            # Format assuming NSE string
            ticker_symbol = f"{symbol}.NS"
            if symbol == "TATAMOTORS": 
                ticker_symbol = "TATAMOTORS.BO"
                
            ticker = yf.Ticker(ticker_symbol)
            hist = ticker.history(period="6mo")
            if hist.empty or len(hist) < 50:
                print(f"TechnicalScorer: Not enough data for {symbol}")
                return 0.5
                
            close = hist['Close']
            volume = hist['Volume']
            
            # RSI 14
            delta = close.diff()
            up = delta.clip(lower=0)
            down = -1 * delta.clip(upper=0)
            ema_up = up.ewm(com=13, adjust=False).mean()
            ema_down = down.ewm(com=13, adjust=False).mean()
            rs = ema_up / ema_down
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            # MACD
            ema_12 = close.ewm(span=12, adjust=False).mean()
            ema_26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema_12 - ema_26
            macd_signal = macd_line.ewm(span=9, adjust=False).mean()
            macd_hist = (macd_line - macd_signal).iloc[-1]
            
            # DMA position
            sma_50 = close.rolling(50).mean().iloc[-1]
            sma_200 = close.rolling(200).mean().iloc[-1]
            current_price = close.iloc[-1]
            
            dma_score = 0.0
            if current_price > sma_50:
                dma_score += 0.5
            if current_price > sma_200:
                dma_score += 0.5
                
            # Volume ratio
            vol_sma_20 = volume.rolling(20).mean().iloc[-1]
            current_vol = volume.iloc[-1]
            vol_ratio = current_vol / vol_sma_20 if vol_sma_20 > 0.0 else 1.0
            
            # Pure calculation score
            base_score = 0.5
            
            # RSI contribution (max ±0.2)
            if rsi < 30: base_score += 0.2
            elif rsi > 70: base_score -= 0.2
            elif rsi < 40: base_score += 0.1
            
            # MACD contribution
            if macd_hist > 0: base_score += 0.15
            else: base_score -= 0.15
            
            # DMA contribution
            if dma_score == 1.0: base_score += 0.1
            elif dma_score == 0.0: base_score -= 0.1
            
            # Volume contribution
            if vol_ratio > 1.2 and current_price >= close.iloc[-2]:
                base_score += 0.1
            elif vol_ratio > 1.2 and current_price < close.iloc[-2]:
                base_score -= 0.1
                
            final_score = max(0.0, min(1.0, base_score))
            print(f"TechnicalScorer calculated {final_score:.3f} for {symbol}")
            return final_score
            
        except Exception as e:
            print(f"TechnicalScorer exception for {symbol}: {e}")
            return 0.5
