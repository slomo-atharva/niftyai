"""
News Scraper and Sentiment Scorer for Indian Markets.

Scrapes headlines from:
  - Moneycontrol markets section
  - Economic Times markets section

Note: BSE scraping is disabled — it requires Playwright for JS-rendered
pages. Will be added in a future update.

For each headline:
  - Extracts a stock symbol if mentioned (via company-name-to-symbol mapping)
  - Runs through ProsusAI/finbert for bullish / bearish / neutral scores
  - Stores result in Supabase `news_sentiment` table with timestamp
"""

import os
import re
import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import requests
from bs4 import BeautifulSoup
import feedparser
from dotenv import load_dotenv
from transformers import AutoTokenizer, AutoModelForSequenceClassification, pipeline
from supabase import create_client, Client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
load_dotenv()

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Common request headers to avoid being blocked
HEADERS: Dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Retry decorator (3 attempts as per project rules)
# ---------------------------------------------------------------------------
def retry_api_call(retries: int = 3, delay: int = 2):
    """Retry decorator for external API / web calls."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            last_err: Optional[Exception] = None
            for attempt in range(1, retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_err = exc
                    logger.warning(
                        f"Attempt {attempt}/{retries} failed for "
                        f"{func.__name__}: {exc}"
                    )
                    if attempt < retries:
                        time.sleep(delay)
            logger.error(f"All {retries} attempts failed for {func.__name__}")
            raise last_err  # type: ignore[misc]
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Supabase client
# ---------------------------------------------------------------------------
def get_supabase_client() -> Client:
    """Initialise and return a Supabase client."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise ValueError("SUPABASE_URL and SUPABASE_KEY must be set in .env")
    return create_client(SUPABASE_URL, SUPABASE_KEY)


# ---------------------------------------------------------------------------
# FinBERT sentiment pipeline (loaded once)
# ---------------------------------------------------------------------------
_finbert_pipeline = None


def get_finbert_pipeline():
    """Lazily load the ProsusAI/finbert pipeline."""
    global _finbert_pipeline
    if _finbert_pipeline is None:
        logger.info("Loading ProsusAI/finbert model – this may take a moment ...")
        tokenizer = AutoTokenizer.from_pretrained("ProsusAI/finbert")
        model = AutoModelForSequenceClassification.from_pretrained("ProsusAI/finbert")
        _finbert_pipeline = pipeline(
            "sentiment-analysis",
            model=model,
            tokenizer=tokenizer,
            top_k=None,          # return scores for ALL labels
            truncation=True,
            max_length=512,
        )
        logger.info("FinBERT model loaded successfully.")
    return _finbert_pipeline


# ---------------------------------------------------------------------------
# Company Name → NSE Symbol Mapping (Nifty 500 comprehensive coverage)
# ---------------------------------------------------------------------------
# Maps common company names (as they appear in headlines) to their NSE ticker
# symbols. Sorted alphabetically for maintainability.
COMPANY_TO_SYMBOL: Dict[str, str] = {
    # --- A ---
    "ABB India": "ABB",
    "ABB": "ABB",
    "ACC": "ACC",
    "AIA Engineering": "AIAENG",
    "APL Apollo Tubes": "APLAPOLLO",
    "AU Small Finance Bank": "AUBANK",
    "AU Small Finance": "AUBANK",
    "Aarti Industries": "AARTIIND",
    "Aarvee Denims": "AARVEEDEN",
    "Aavas Financiers": "AAVAS",
    "Abbott India": "ABBOTINDIA",
    "Adani Enterprises": "ADANIENT",
    "Adani Green": "ADANIGREEN",
    "Adani Green Energy": "ADANIGREEN",
    "Adani Ports": "ADANIPORTS",
    "Adani Ports and SEZ": "ADANIPORTS",
    "Adani Power": "ADANIPOWER",
    "Adani Total Gas": "ATGL",
    "Adani Transmission": "ADANITRANS",
    "Adani Wilmar": "AWL",
    "Aditya Birla Capital": "ABCAPITAL",
    "Aditya Birla Fashion": "ABFRL",
    "Aditya Birla Sun Life": "ABSLAMC",
    "Ajanta Pharma": "AJANTPHARM",
    "Alembic Pharmaceuticals": "APLLTD",
    "Alkem Laboratories": "ALKEM",
    "Alkyl Amines": "ALKYLAMINE",
    "Amara Raja Batteries": "AMARAJABAT",
    "Amara Raja Energy": "AMARAJABAT",
    "Ambuja Cements": "AMBUJACEM",
    "Angel One": "ANGELONE",
    "Angel Broking": "ANGELONE",
    "Apollo Hospitals": "APOLLOHOSP",
    "Apollo Tyres": "APOLLOTYRE",
    "Ashok Leyland": "ASHOKLEY",
    "Asian Paints": "ASIANPAINT",
    "Astral": "ASTRAL",
    "Atul": "ATUL",
    "Aurobindo Pharma": "AUROPHARMA",
    "Avenue Supermarts": "DMART",
    "DMart": "DMART",
    "Axis Bank": "AXISBANK",
    # --- B ---
    "BPCL": "BPCL",
    "Bharat Petroleum": "BPCL",
    "BSE": "BSE",
    "Bajaj Auto": "BAJAJ-AUTO",
    "Bajaj Finance": "BAJFINANCE",
    "Bajaj Finserv": "BAJAJFINSV",
    "Bajaj Holdings": "BAJAJHLDNG",
    "Balkrishna Industries": "BALKRISIND",
    "Balrampur Chini": "BALRAMCHIN",
    "Bandhan Bank": "BANDHANBNK",
    "Bank of Baroda": "BANKBARODA",
    "Bank of India": "BANKINDIA",
    "Bank of Maharashtra": "MAHABANK",
    "Bata India": "BATAINDIA",
    "Berger Paints": "BERGEPAINT",
    "Bharat Electronics": "BEL",
    "Bharat Forge": "BHARATFORG",
    "Bharat Heavy Electricals": "BHEL",
    "BHEL": "BHEL",
    "Bharti Airtel": "BHARTIARTL",
    "Airtel": "BHARTIARTL",
    "Biocon": "BIOCON",
    "Birla Corporation": "BIRLACORPN",
    "Birlasoft": "BSOFT",
    "Blue Dart": "BLUEDART",
    "Blue Star": "BLUESTARCO",
    "Bosch": "BOSCHLTD",
    "Britannia": "BRITANNIA",
    "Britannia Industries": "BRITANNIA",
    # --- C ---
    "CG Power": "CGPOWER",
    "CRISIL": "CRISIL",
    "CSB Bank": "CSBBANK",
    "Canara Bank": "CANBK",
    "Carborundum Universal": "CARBORUNIV",
    "Castrol India": "CASTROLIND",
    "Central Bank of India": "CENTRALBK",
    "Century Plyboards": "CENTURYPLY",
    "Chambal Fertilisers": "CHAMBLFERT",
    "Chennai Petrochemicals": "CHENNPETRO",
    "Cholamandalam Investment": "CHOLAFIN",
    "Cholamandalam": "CHOLAFIN",
    "Cipla": "CIPLA",
    "City Union Bank": "CUB",
    "Clean Science": "CLEAN",
    "Coal India": "COALINDIA",
    "Cochin Shipyard": "COCHINSHIP",
    "Coforge": "COFORGE",
    "Colgate-Palmolive": "COLPAL",
    "Colgate": "COLPAL",
    "Container Corporation": "CONCOR",
    "Coromandel International": "COROMANDEL",
    "Crompton Greaves Consumer": "CROMPTON",
    "Crompton": "CROMPTON",
    "CUMMINS India": "CUMMINSIND",
    "Cummins India": "CUMMINSIND",
    "Cyient": "CYIENT",
    # --- D ---
    "Dabur India": "DABUR",
    "Dabur": "DABUR",
    "Dalmia Bharat": "DALBHARAT",
    "DCM Shriram": "DCMSHRIRAM",
    "Deepak Fertilisers": "DEEPAKFERT",
    "Deepak Nitrite": "DEEPAKNTR",
    "Delhivery": "DELHIVERY",
    "Delta Corp": "DELTACORP",
    "Devyani International": "DEVYANI",
    "Divi's Laboratories": "DIVISLAB",
    "Divis Labs": "DIVISLAB",
    "Dixon Technologies": "DIXON",
    "DLF": "DLF",
    "Dr Lal PathLabs": "LALPATHLAB",
    "Dr Reddy's Laboratories": "DRREDDY",
    "Dr Reddy's": "DRREDDY",
    "Dr. Reddy's": "DRREDDY",
    # --- E ---
    "EIH": "EIHOTEL",
    "Eicher Motors": "EICHERMOT",
    "Elgi Equipments": "ELGIEQUIP",
    "Emami": "EMAMILTD",
    "Endurance Technologies": "ENDURANCE",
    "Engineers India": "ENGINERSIN",
    "Equitas Small Finance": "EQUITASBNK",
    "Escorts Kubota": "ESCORTS",
    "Escorts": "ESCORTS",
    "Exide Industries": "EXIDEIND",
    # --- F ---
    "FSN E-Commerce": "NYKAA",
    "Nykaa": "NYKAA",
    "Federal Bank": "FEDERALBNK",
    "Fertilisers and Chemicals Travancore": "FACT",
    "Fine Organic": "FINEORG",
    "Firstsource Solutions": "FSL",
    "Fortis Healthcare": "FORTIS",
    "Fortis": "FORTIS",
    # --- G ---
    "GAIL India": "GAIL",
    "GAIL": "GAIL",
    "GMR Airports": "GMRINFRA",
    "GR Infraprojects": "GRINFRA",
    "Galaxy Surfactants": "GALAXYSURF",
    "Garden Reach Shipbuilders": "GRSE",
    "Gillette India": "GILLETTE",
    "Gland Pharma": "GLAND",
    "Glaxosmithkline Pharma": "GLAXO",
    "Glenmark Pharmaceuticals": "GLENMARK",
    "Glenmark": "GLENMARK",
    "Global Health": "MEDANTA",
    "Medanta": "MEDANTA",
    "GMM Pfaudler": "GMMPFAUDLR",
    "Godrej Consumer Products": "GODREJCP",
    "Godrej Consumer": "GODREJCP",
    "Godrej Industries": "GODREJIND",
    "Godrej Properties": "GODREJPROP",
    "Granules India": "GRANULES",
    "Graphite India": "GRAPHITE",
    "Grasim Industries": "GRASIM",
    "Grasim": "GRASIM",
    "Great Eastern Shipping": "GESHIP",
    "Gujarat Gas": "GUJGASLTD",
    "Gujarat Fluorochemicals": "FLUOROCHEM",
    "Gujarat Pipavav Port": "GPPL",
    "Gujarat State Petronet": "GSPL",
    # --- H ---
    "HCL Technologies": "HCLTECH",
    "HCL Tech": "HCLTECH",
    "HDFC AMC": "HDFCAMC",
    "HDFC Asset Management": "HDFCAMC",
    "HDFC Bank": "HDFCBANK",
    "HDFC Life": "HDFCLIFE",
    "HDFC Life Insurance": "HDFCLIFE",
    "HDFC": "HDFCBANK",
    "HPCL": "HINDPETRO",
    "Hindustan Petroleum": "HINDPETRO",
    "HAL": "HAL",
    "Hindustan Aeronautics": "HAL",
    "Happiest Minds": "HAPPSTMNDS",
    "Havells India": "HAVELLS",
    "Havells": "HAVELLS",
    "Hero MotoCorp": "HEROMOTOCO",
    "Hero Moto": "HEROMOTOCO",
    "Hindalco Industries": "HINDALCO",
    "Hindalco": "HINDALCO",
    "Hindustan Copper": "HINDCOPPER",
    "Hindustan Unilever": "HINDUNILVR",
    "HUL": "HINDUNILVR",
    "Hindustan Zinc": "HINDZINC",
    "Hitachi Energy India": "POWERINDIA",
    "Honeywell Automation": "HONAUT",
    # --- I ---
    "ICICI Bank": "ICICIBANK",
    "ICICI Lombard": "ABORTICLOM",
    "ICICI Prudential Life": "ICICIPRULI",
    "ICICI Prudential": "ICICIPRULI",
    "ICICI Securities": "ISEC",
    "IDFC First Bank": "IDFCFISTB",
    "IDFC First": "IDFCFISTB",
    "IEX": "IEX",
    "Indian Energy Exchange": "IEX",
    "IIFL Finance": "IIFL",
    "IIFL Wealth": "IIFLWAM",
    "ITC": "ITC",
    "India Cements": "INDIACEM",
    "Indian Bank": "INDIANB",
    "Indian Hotels": "INDHOTEL",
    "Taj Hotels": "INDHOTEL",
    "Indian Oil Corporation": "IOC",
    "Indian Oil": "IOC",
    "IOC": "IOC",
    "Indian Overseas Bank": "IOB",
    "Indian Railway Catering": "IRCTC",
    "IRCTC": "IRCTC",
    "Indian Railway Finance": "IRFC",
    "IRFC": "IRFC",
    "Indraprastha Gas": "IGL",
    "IGL": "IGL",
    "IndusInd Bank": "INDUSINDBK",
    "Infosys": "INFY",
    "IndiGo": "INDIGO",
    "InterGlobe Aviation": "INDIGO",
    "Intellect Design Arena": "INTELLECT",
    "IPCL": "IPCALAB",
    "Ipca Laboratories": "IPCALAB",
    # --- J ---
    "J&K Bank": "J&KBANK",
    "JBM Auto": "JBMA",
    "JK Cement": "JKCEMENT",
    "JK Lakshmi Cement": "JKLAKSHMI",
    "JK Tyre": "JKTYRE",
    "JM Financial": "JMFINANCIL",
    "JSW Energy": "JSWENERGY",
    "JSW Steel": "JSWSTEEL",
    "Jindal Steel and Power": "JINDALSTEL",
    "Jindal Steel": "JINDALSTEL",
    "Jubilant FoodWorks": "JUBLFOOD",
    "Jubilant Food": "JUBLFOOD",
    "Jupiter Wagons": "JWL",
    "Jyothy Labs": "JYOTHYLAB",
    # --- K ---
    "KPIT Technologies": "KPITTECH",
    "KPIT Tech": "KPITTECH",
    "KNR Constructions": "KNRCON",
    "KPR Mill": "KPRMILL",
    "Kalpataru Projects": "KPIL",
    "Kalyan Jewellers": "KALYANKJIL",
    "Karur Vysya Bank": "KARURVYSYA",
    "KEI Industries": "KEI",
    "Kotak Mahindra Bank": "KOTAKBANK",
    "Kotak Bank": "KOTAKBANK",
    "Kotak Mahindra": "KOTAKBANK",
    # --- L ---
    "L&T": "LT",
    "Larsen & Toubro": "LT",
    "Larsen and Toubro": "LT",
    "L&T Finance": "LTF",
    "L&T Technology Services": "LTTS",
    "LTIMindtree": "LTIM",
    "LTI Mindtree": "LTIM",
    "LIC Housing Finance": "LICHSGFIN",
    "LIC": "LICI",
    "Life Insurance Corporation": "LICI",
    "Laurus Labs": "LAURUSLABS",
    "Linde India": "LINDEINDIA",
    "Lupin": "LUPIN",
    "Lux Industries": "LUXIND",
    # --- M ---
    "MRF": "MRF",
    "Mahanagar Gas": "MGL",
    "MGL": "MGL",
    "Mahindra & Mahindra": "M&M",
    "Mahindra and Mahindra": "M&M",
    "M&M": "M&M",
    "Mahindra": "M&M",
    "Mahindra CIE Automotive": "MAHINDCIE",
    "Mahindra Lifespace": "MAHLIFE",
    "Manappuram Finance": "MANAPPURAM",
    "Mangalore Refinery": "MRPL",
    "Marico": "MARICO",
    "Maruti Suzuki": "MARUTI",
    "Maruti": "MARUTI",
    "Max Financial Services": "MFSL",
    "Max Healthcare": "MAXHEALTH",
    "Mazagon Dock": "MAZAGON",
    "Mazagon Dock Shipbuilders": "MAZAGON",
    "Metropolis Healthcare": "METROPOLIS",
    "Metropolis": "METROPOLIS",
    "Minda Industries": "MINDAIND",
    "Motherson Sumi": "MOTHERSON",
    "Motherson": "MOTHERSON",
    "Motilal Oswal": "MOTILALOFS",
    "Mphasis": "MPHASIS",
    "Multi Commodity Exchange": "MCX",
    "MCX": "MCX",
    "Muthoot Finance": "MUTHOOTFIN",
    "Muthoot": "MUTHOOTFIN",
    # --- N ---
    "NBCC India": "NBCC",
    "NBCC": "NBCC",
    "NCC": "NCC",
    "NHPC": "NHPC",
    "NMDC": "NMDC",
    "NTPC": "NTPC",
    "National Aluminium": "NATIONALUM",
    "NALCO": "NATIONALUM",
    "Navin Fluorine": "NAVINFLUOR",
    "Nestle India": "NESTLEIND",
    "Nestle": "NESTLEIND",
    "NESCO": "NESCO",
    # --- O ---
    "ONGC": "ONGC",
    "Oil and Natural Gas": "ONGC",
    "Oil India": "OIL",
    "Oberoi Realty": "OBEROIRLTY",
    "Oracle Financial Services": "OFSS",
    # --- P ---
    "PB Fintech": "POLICYBZR",
    "Policybazaar": "POLICYBZR",
    "PNB": "PNB",
    "Punjab National Bank": "PNB",
    "PNB Housing Finance": "PNBHOUSING",
    "PTC India": "PTC",
    "PVR Inox": "PVRINOX",
    "PVR INOX": "PVRINOX",
    "Page Industries": "PAGEIND",
    "Patanjali Foods": "PATANJALI",
    "Paytm": "PAYTM",
    "One97 Communications": "PAYTM",
    "Persistent Systems": "PERSISTENT",
    "Persistent": "PERSISTENT",
    "Petronet LNG": "PETRONET",
    "Pfizer": "PFIZER",
    "PI Industries": "PIIND",
    "Pidilite Industries": "PIDILITIND",
    "Pidilite": "PIDILITIND",
    "Polycab India": "POLYCAB",
    "Polycab": "POLYCAB",
    "Poonawalla Fincorp": "POONAWALLA",
    "Power Finance Corporation": "PFC",
    "PFC": "PFC",
    "Power Grid Corporation": "POWERGRID",
    "Power Grid": "POWERGRID",
    "Prestige Estates": "PRESTIGE",
    "Procter & Gamble": "PGHH",
    "P&G": "PGHH",
    # --- R ---
    "RBL Bank": "RBLBANK",
    "REC Limited": "RECLTD",
    "REC": "RECLTD",
    "Radico Khaitan": "RADICO",
    "Rain Industries": "RAIN",
    "Rajesh Exports": "RAJESHEXPO",
    "Rallis India": "RALLIS",
    "Ramco Cements": "RAMCOCEM",
    "Rashtriya Chemicals": "RCF",
    "Raymond": "RAYMOND",
    "Redington": "REDINGTON",
    "Reliance Industries": "RELIANCE",
    "Reliance": "RELIANCE",
    "Route Mobile": "ROUTE",
    # --- S ---
    "SBI Life Insurance": "SBILIFE",
    "SBI Life": "SBILIFE",
    "SBI Cards": "SBICARD",
    "SBI Card": "SBICARD",
    "SJVN": "SJVN",
    "SKF India": "SKFINDIA",
    "SRF": "SRF",
    "SAIL": "SAIL",
    "Steel Authority of India": "SAIL",
    "Steel Authority": "SAIL",
    "Sanofi India": "SANOFI",
    "Sapphire Foods": "SAPPHIRE",
    "Schaeffler India": "SCHAEFFLER",
    "Shree Cement": "SHREECEM",
    "Shriram Finance": "SHRIRAMFIN",
    "Shriram Transport": "SHRIRAMFIN",
    "Siemens": "SIEMENS",
    "Sobha": "SOBHA",
    "Solar Industries": "SOLARINDS",
    "Sonata Software": "SONATSOFTW",
    "Star Health": "STARHEALTH",
    "State Bank of India": "SBIN",
    "SBI": "SBIN",
    "Sterling and Wilson": "SWSOLAR",
    "Strides Pharma": "STAR",
    "Sun Pharmaceutical": "SUNPHARMA",
    "Sun Pharma": "SUNPHARMA",
    "Sundaram Finance": "SUNDARMFIN",
    "Sundram Fasteners": "SUNDRMFAST",
    "Supreme Industries": "SUPREMEIND",
    "Suzlon Energy": "SUZLON",
    "Suzlon": "SUZLON",
    "Syngene International": "SYNGENE",
    "Syngene": "SYNGENE",
    # --- T ---
    "TVS Motor": "TVSMOTOR",
    "TVS Motor Company": "TVSMOTOR",
    "Tata Chemicals": "TATACHEM",
    "Tata Communications": "TATACOMM",
    "Tata Consultancy Services": "TCS",
    "TCS": "TCS",
    "Tata Consumer Products": "TATACONSUM",
    "Tata Consumer": "TATACONSUM",
    "Tata Elxsi": "TATAELXSI",
    "Tata Motors": "TATAMOTORS",
    "Tata Power": "TATAPOWER",
    "Tata Steel": "TATASTEEL",
    "Tata Technologies": "TATATECH",
    "Tech Mahindra": "TECHM",
    "Thermax": "THERMAX",
    "Timken India": "TIMKEN",
    "Titan Company": "TITAN",
    "Titan": "TITAN",
    "Torrent Pharmaceuticals": "TORNTPHARM",
    "Torrent Pharma": "TORNTPHARM",
    "Torrent Power": "TORNTPOWER",
    "Trent": "TRENT",
    "Trident": "TRIDENT",
    "Triveni Turbine": "TRITURBINE",
    "Tube Investments": "TIINDIA",
    # --- U ---
    "UPL": "UPL",
    "UltraTech Cement": "ULTRACEMCO",
    "Ultratech Cement": "ULTRACEMCO",
    "UltraTech": "ULTRACEMCO",
    "Union Bank of India": "UNIONBANK",
    "Union Bank": "UNIONBANK",
    "United Breweries": "UBL",
    "United Spirits": "UNITDSPR",
    # --- V ---
    "Varun Beverages": "VBL",
    "Vedanta": "VEDL",
    "Vinati Organics": "VINATIORGA",
    "Vodafone Idea": "IDEA",
    "Vi": "IDEA",
    "Voltas": "VOLTAS",
    # --- W ---
    "Welspun Corp": "WELCORP",
    "Welspun India": "WELSPUNIND",
    "Whirlpool India": "WHIRLPOOL",
    "Wipro": "WIPRO",
    # --- Y ---
    "Yes Bank": "YESBANK",
    # --- Z ---
    "Zee Entertainment": "ZEEL",
    "Zeel": "ZEEL",
    "Zensar Technologies": "ZENSARTECH",
    "Zomato": "ZOMATO",
    "Zydus Lifesciences": "ZYDUSLIFE",
    "Zydus": "ZYDUSLIFE",
}

# Build a list of all unique NSE symbols from the mapping for direct matching
KNOWN_SYMBOLS: List[str] = sorted(set(COMPANY_TO_SYMBOL.values()))

# Sort company names longest-first so "Hindustan Unilever" matches
# before "Hindustan" when scanning headlines
_sorted_company_names: List[Tuple[str, str]] = sorted(
    COMPANY_TO_SYMBOL.items(), key=lambda x: len(x[0]), reverse=True
)

# Pre-compiled regex for direct symbol matching (fallback)
_symbol_pattern = re.compile(
    r"\b(" + "|".join(re.escape(s) for s in KNOWN_SYMBOLS) + r")\b",
    re.IGNORECASE,
)

# Pre-compiled regex for company name matching (primary)
_company_pattern = re.compile(
    r"\b(" + "|".join(re.escape(name) for name, _ in _sorted_company_names) + r")\b",
    re.IGNORECASE,
)


def extract_symbol(headline: str) -> Optional[str]:
    """Extract an NSE stock symbol from a headline using company name mapping.

    Strategy:
      1. Try matching company names first (e.g. 'HDFC Bank' → 'HDFCBANK')
      2. Fall back to direct symbol matching (e.g. 'INFY' → 'INFY')
    """
    # 1. Try company name match
    match = _company_pattern.search(headline)
    if match:
        matched_name = match.group(1)
        # Lookup in mapping (case-insensitive)
        for name, symbol in _sorted_company_names:
            if name.lower() == matched_name.lower():
                return symbol
    # 2. Fallback: direct symbol match
    match = _symbol_pattern.search(headline)
    if match:
        return match.group(1).upper()
    return None


# ---------------------------------------------------------------------------
# Scraper functions
# ---------------------------------------------------------------------------

@retry_api_call(retries=3)
def scrape_moneycontrol() -> List[Dict[str, str]]:
    """Scrape latest headlines from Moneycontrol markets section."""
    url = "https://www.moneycontrol.com/rss/marketreports.xml"
    logger.info(f"Scraping Moneycontrol RSS: {url}")

    feed = feedparser.parse(url)
    headlines: List[Dict[str, str]] = []

    if feed.entries:
        for entry in feed.entries[:30]:
            title = entry.get("title", "").strip()
            if title:
                headlines.append({"headline": title, "source": "moneycontrol"})
    
    # Fallback: scrape the page directly if RSS yields nothing
    if not headlines:
        logger.info("RSS empty – falling back to HTML scrape for Moneycontrol")
        page_url = "https://www.moneycontrol.com/news/business/markets/"
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.select("h2 a, h3 a, li a.card_title"):
            title = tag.get_text(strip=True)
            if title and len(title) > 15:
                headlines.append({"headline": title, "source": "moneycontrol"})

    logger.info(f"Moneycontrol: scraped {len(headlines)} headlines")
    return headlines


@retry_api_call(retries=3)
def scrape_economictimes() -> List[Dict[str, str]]:
    """Scrape latest headlines from Economic Times markets section."""
    url = "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"
    logger.info(f"Scraping Economic Times RSS: {url}")

    feed = feedparser.parse(url)
    headlines: List[Dict[str, str]] = []

    if feed.entries:
        for entry in feed.entries[:30]:
            title = entry.get("title", "").strip()
            if title:
                headlines.append({"headline": title, "source": "economic_times"})

    # Fallback: scrape the web page directly
    if not headlines:
        logger.info("RSS empty – falling back to HTML scrape for Economic Times")
        page_url = "https://economictimes.indiatimes.com/markets"
        resp = requests.get(page_url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup.select("h2 a, h3 a, a.story_title"):
            title = tag.get_text(strip=True)
            if title and len(title) > 15:
                headlines.append({"headline": title, "source": "economic_times"})

    logger.info(f"Economic Times: scraped {len(headlines)} headlines")
    return headlines


# ---------------------------------------------------------------------------
# BSE scraper — DISABLED
# BSE announcements page is JS-rendered and needs Playwright to scrape.
# TODO: Add Playwright-based BSE scraper in a future update.
# ---------------------------------------------------------------------------
# @retry_api_call(retries=3)
# def scrape_bse() -> List[Dict[str, str]]:
#     """Scrape latest announcements from BSE India."""
#     ...


# ---------------------------------------------------------------------------
# Sentiment analysis
# ---------------------------------------------------------------------------

def analyze_sentiment(headline: str) -> Dict[str, float]:
    """
    Run a headline through ProsusAI/finbert and return sentiment scores.

    Returns a dict like:
        {"positive": 0.85, "negative": 0.10, "neutral": 0.05}

    We map:
        positive -> bullish
        negative -> bearish
        neutral  -> neutral
    """
    nlp = get_finbert_pipeline()
    results = nlp(headline)
    # `results` is a list of lists when top_k=None
    scores: Dict[str, float] = {}
    for item in results[0]:
        label = item["label"].lower()  # "positive", "negative", "neutral"
        scores[label] = round(item["score"], 4)
    return scores


# ---------------------------------------------------------------------------
# Store to Supabase
# ---------------------------------------------------------------------------

def store_to_supabase(records: List[Dict[str, Any]]) -> None:
    """
    Upsert headline sentiment records into the `news_sentiment` table.

    Expected columns:
        headline   TEXT
        symbol     TEXT (nullable)
        source     TEXT
        bullish    FLOAT
        bearish    FLOAT
        neutral    FLOAT
        sentiment  TEXT  (dominant label)
        created_at TIMESTAMPTZ
    """
    if not records:
        logger.warning("No records to store.")
        return

    client = get_supabase_client()

    # Ensure the table exists – if not, create it via Supabase SQL editor.
    # For now we attempt the insert and log any errors.
    try:
        response = client.table("news_sentiment").insert(records).execute()
        logger.info(f"Stored {len(records)} records to Supabase news_sentiment table.")
    except Exception as exc:
        logger.error(f"Failed to store to Supabase: {exc}")
        raise


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_scrape_and_score() -> List[Dict[str, Any]]:
    """
    Full pipeline:
      1. Scrape Moneycontrol and Economic Times
      2. Deduplicate by headline text
      3. Extract symbol + run FinBERT
      4. Return list of scored records

    Note: BSE scraping is disabled — needs Playwright. Will add later.
    """
    all_headlines: List[Dict[str, str]] = []

    # --- Scrape active sources (BSE disabled — needs Playwright) ---
    for scraper_fn in [scrape_moneycontrol, scrape_economictimes]:
        try:
            all_headlines.extend(scraper_fn())
        except Exception as exc:
            logger.error(f"Scraper {scraper_fn.__name__} failed entirely: {exc}")

    if not all_headlines:
        logger.error("No headlines scraped from any source.")
        return []

    # Deduplicate
    seen: set = set()
    unique: List[Dict[str, str]] = []
    for h in all_headlines:
        key = h["headline"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(h)

    logger.info(f"Total unique headlines: {len(unique)}")

    # --- Score each headline ---
    scored_records: List[Dict[str, Any]] = []
    now_ts = datetime.now(timezone.utc).isoformat()

    for item in unique:
        headline = item["headline"]
        source = item["source"]

        try:
            scores = analyze_sentiment(headline)
        except Exception as exc:
            logger.warning(f"Sentiment analysis failed for headline: {exc}")
            continue

        bullish = scores.get("positive", 0.0)
        bearish = scores.get("negative", 0.0)
        neutral = scores.get("neutral", 0.0)

        # Dominant sentiment
        dominant = max(scores, key=scores.get)  # type: ignore[arg-type]
        label_map = {"positive": "bullish", "negative": "bearish", "neutral": "neutral"}
        sentiment = label_map.get(dominant, dominant)

        symbol = extract_symbol(headline)

        record: Dict[str, Any] = {
            "headline": headline[:500],  # cap length
            "symbol": symbol,
            "source": source,
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "sentiment": sentiment,
            "created_at": now_ts,
        }
        scored_records.append(record)

    logger.info(f"Scored {len(scored_records)} headlines with FinBERT.")
    return scored_records


def print_sample(records: List[Dict[str, Any]], n: int = 10) -> None:
    """Pretty-print the first *n* scored headlines."""
    sample = records[:n]
    print("\n" + "=" * 90)
    print(f"  {'SAMPLE HEADLINES WITH SENTIMENT SCORES':^86}")
    print("=" * 90)
    for i, rec in enumerate(sample, 1):
        print(f"\n  [{i}] {rec['headline'][:80]}")
        print(f"      Source   : {rec['source']}")
        print(f"      Symbol   : {rec['symbol'] or '—'}")
        print(
            f"      Bullish  : {rec['bullish']:.4f}  |  "
            f"Bearish : {rec['bearish']:.4f}  |  "
            f"Neutral : {rec['neutral']:.4f}"
        )
        print(f"      Verdict  : {rec['sentiment'].upper()}")
    print("\n" + "=" * 90 + "\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Starting news scrape & sentiment scoring pipeline …")

    records = run_scrape_and_score()

    if records:
        print_sample(records, n=10)

        # Store to Supabase
        try:
            store_to_supabase(records)
            print(f"✅  All {len(records)} records stored to Supabase.\n")
        except Exception as exc:
            print(f"⚠️  Supabase insert failed: {exc}")
            print("   (You may need to create the `news_sentiment` table first.)\n")
    else:
        print("❌  No headlines scraped. Check logs above for errors.\n")
