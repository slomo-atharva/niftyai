import os
import time
import logging
from typing import List, Dict, Any, Optional
from fyers_apiv3 import fyersModel
from fyers_apiv3.FyersWebsocket import data_ws
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Fyers Credentials
CLIENT_ID = os.getenv("FYERS_CLIENT_ID", "")
SECRET_KEY = os.getenv("FYERS_SECRET_KEY", "")
REDIRECT_URI = os.getenv("FYERS_REDIRECT_URI", "")
USER_ID = os.getenv("FYERS_USER_ID", "")
TOTP_SECRET = os.getenv("FYERS_TOTP_SECRET", "")
PIN = os.getenv("FYERS_PIN", "")
ACCESS_TOKEN = os.getenv("FYERS_ACCESS_TOKEN", "")

def retry_api_call(retries: int = 3, delay: int = 2):
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_err = None
            for attempt in range(1, retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_err = e
                    logger.warning(f"Attempt {attempt}/{retries} failed for {func.__name__}: {e}")
                    if attempt < retries:
                        time.sleep(delay)
            logger.error(f"All {retries} attempts failed for {func.__name__}")
            raise last_err
        return wrapper
    return decorator

@retry_api_call(retries=3)
def authenticate() -> fyersModel.FyersModel:
    """
    Handles login with TOTP.
    In a real headless environment, one would generate the TOTP via `pyotp` and 
    hit the Fyers login endpoints to generate the auth_code and finally the access_token.
    Since Fyers API V3 requires an interactive login flow by default, many users 
    either use a selenium wrapper or a 3rd party library to simulate the web requests 
    for TOTP + PIN.
    Here we demonstrate where the TOTP logic integrates to retrieve an access token.
    If an ACCESS_TOKEN is already present in .env, we use it directly.
    """
    global ACCESS_TOKEN
    
    if not ACCESS_TOKEN and TOTP_SECRET and USER_ID and PIN:
        try:
            import pyotp
            import requests
            import base64
            
            # This is a representative headless Fyers login flow via their internal endpoints.
            totp = pyotp.TOTP(TOTP_SECRET).now()
            logger.info("Generated TOTP, attempting headless login...")
            
            # Step 1: Send Login OTP
            res1 = requests.post("https://api-t2.fyers.in/vagator/v2/send_login_otp_v2", 
                               json={"fy_id": base64.b64encode(USER_ID.encode()).decode(), "app_id": "2"}).json()
            request_key = res1.get("request_key")
            
            # Step 2: Verify TOTP
            res2 = requests.post("https://api-t2.fyers.in/vagator/v2/verify_otp", 
                               json={"request_key": request_key, "otp": totp}).json()
            request_key = res2.get("request_key")
            
            # Step 3: Verify PIN
            res3 = requests.post("https://api-t2.fyers.in/vagator/v2/verify_pin_v2",
                               json={"request_key": request_key, "identity_type": "pin", "identifier": base64.b64encode(PIN.encode()).decode()}).json()
            auth_token = res3["data"]["access_token"]
            
            # Step 4: Generate Auth Code
            session = fyersModel.SessionModel(client_id=CLIENT_ID, secret_key=SECRET_KEY, 
                                            redirect_uri=REDIRECT_URI, response_type="code", grant_type="authorization_code")
            res4 = requests.post(f"https://api.fyers.in/api/v2/token", 
                               json={"fyers_id": USER_ID, "app_id": CLIENT_ID.split('-')[0], 
                                     "redirect_uri": REDIRECT_URI, "appType": "100", 
                                     "code_challenge": "", "state": "None", "scope": "", 
                                     "nonce": "", "response_type": "code", "create_cookie": True},
                               headers={"Authorization": f"Bearer {auth_token}"}).json()
            
            auth_code = res4["Url"].split("auth_code=")[1].split("&")[0]
            
            # Step 5: Get Access Token
            session.set_token(auth_code)
            response = session.generate_token()
            ACCESS_TOKEN = response["access_token"]
            logger.info("Successfully generated ACCESS_TOKEN using TOTP.")
        except Exception as e:
            logger.error(f"Failed to perform headless TOTP authentication: {e}")
            raise

    fyers = fyersModel.FyersModel(
        client_id=CLIENT_ID,
        is_async=False,
        token=ACCESS_TOKEN,
        log_path="/tmp"
    )
    logger.info("Fyers client initialized.")
    return fyers

@retry_api_call(retries=3)
def get_historical_data(symbol: str, days: int = 365) -> Dict[str, Any]:
    fyers = authenticate()
    import datetime
    end_date = datetime.date.today()
    start_date = end_date - datetime.timedelta(days=days)
    data = {
        "symbol": symbol,
        "resolution": "D",
        "date_format": "1",
        "range_from": start_date.strftime("%Y-%m-%d"),
        "range_to": end_date.strftime("%Y-%m-%d"),
        "cont_flag": "1"
    }
    logger.info(f"Fetching historical data for {symbol} ({days} days)")
    response = fyers.history(data=data)
    if isinstance(response, dict) and response.get("s") == "ok":
        return response
    else:
        raise Exception(f"Historical data error: {response}")

@retry_api_call(retries=3)
def get_live_price(symbol: str) -> Dict[str, Any]:
    fyers = authenticate()
    data = {"symbols": symbol}
    logger.info(f"Fetching live price for {symbol}")
    response = fyers.quotes(data=data)
    if isinstance(response, dict) and response.get("s") == "ok":
        return response
    else:
        raise Exception(f"Live price error: {response}")

@retry_api_call(retries=3)
def get_all_nifty500_symbols() -> List[str]:
    logger.info("Fetching Nifty 500 symbols from NSE/Fyers...")
    import requests
    import pandas as pd
    from io import StringIO
    url = "https://public.fyers.in/sym_details/NSE_CM.csv"
    response = requests.get(url)
    response.raise_for_status()
    df = pd.read_csv(StringIO(response.text), header=None)
    
    symbols = []
    for col in df.columns:
        if df[col].dtype == object:
            matches = df[col].dropna()[df[col].dropna().str.endswith("-EQ", na=False)].tolist()
            symbols.extend(matches)
    unique_symbols = list(set(symbols))
    return unique_symbols[:500] if len(unique_symbols) >= 500 else unique_symbols

@retry_api_call(retries=3)
def place_order(symbol: str, qty: int, side: str, entry: float, sl: float, target: float) -> Dict[str, Any]:
    """
    Places a bracket/cover order or normal order depending on the strategy.
    Maps side 'BUY'/'SELL' to Fyers side constants.
    """
    fyers = authenticate()
    
    # Mapping side to Fyers constants (1 => Buy, -1 => Sell)
    fyers_side = 1 if side.upper() == "BUY" else -1
    
    # Calculate stoploss and take profit points relative to entry for Fyers BO type
    sl_points = abs(entry - sl)
    target_points = abs(target - entry)
    
    data = {
        "symbol": symbol,
        "qty": qty,
        "type": 4, # 4 => Limit Order
        "side": fyers_side,
        "productType": "BO", # Bracket Order for Entry, SL, Target
        "limitPrice": entry,
        "stopPrice": 0,
        "validity": "DAY",
        "disclosedQty": 0,
        "offlineOrder": False,
        "stopLoss": sl_points,
        "takeProfit": target_points
    }
    
    logger.info(f"Placing order for {symbol}: {side} {qty} @ {entry} (SL: {sl}, TGT: {target})")
    response = fyers.place_order(data=data)
    
    if isinstance(response, dict) and response.get("s") == "ok":
        logger.info(f"Order placed successfully: {response}")
        return response
    else:
        raise Exception(f"Order placement failed: {response}")

if __name__ == "__main__":
    try:
        authenticate()
        print("Authentication and initialization successful.")
    except Exception as e:
        print(f"Pipeline execution halted due to error: {e}")
