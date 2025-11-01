import os, time, json, math, requests, pandas as pd, numpy as np
from dotenv import load_dotenv
from datetime import datetime, timedelta

load_dotenv()
EODHD_KEY = os.getenv("EODHD_KEY","")
FINNHUB_KEY = os.getenv("FINNHUB_KEY","")
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY","")

HUMAN_EXCHANGE_SUFFIX = {"US": ".US","LSE": ".L","PAR": ".PA","AMS": ".AS","MAD": ".MC"}

def load_universe():
    df = pd.read_csv("tickers.csv")
    for c in ["ticker","company","exchange","sector"]:
        if c not in df.columns: df[c] = ""
    return df

_cache_prices, _cache_funds, _cache_news, _cache_hist = {}, {}, {}, {}

def _cache_get(cache, key, ttl_sec):
    item = cache.get(key)
    if not item: return None
    ts, val = item
    return val if time.time() - ts <= ttl_sec else None

def _cache_set(cache, key, val): cache[key] = (time.time(), val)

def _resolve_eodhd_symbol(ticker, exchange):
    return ticker if "." in ticker else f"{ticker}{HUMAN_EXCHANGE_SUFFIX.get(str(exchange).upper().strip(), '.US')}"

def fetch_prices_batch(tickers, batch_size=10):
    out = {}
    for t in tickers:
        val = _cache_get(_cache_prices, t, 1800)
        if val is not None: out[t] = val; continue
        if not FINNHUB_KEY: out[t] = np.nan; continue
        try:
            r = requests.get("https://finnhub.io/api/v1/quote", params={"symbol": t.split(".")[0], "token": FINNHUB_KEY}, timeout=10)
            if r.status_code == 200:
                price = r.json().get("c", np.nan) or np.nan
                _cache_set(_cache_prices, t, price)
                out[t] = price
            else: out[t] = np.nan
        except Exception: out[t] = np.nan
        time.sleep(0.2)
    return out

def fetch_fundamentals_batch(df_uni, batch_size=10):
    out = {}
    for _, row in df_uni.iterrows():
        t, ex = row["ticker"], row["exchange"]
        cached = _cache_get(_cache_funds, t, 86400)
        if cached is not None: out[t] = cached; continue
        sym = _resolve_eodhd_symbol(t, ex)
        if not EODHD_KEY: out[t] = {}; continue
        try:
            url = f"https://eodhd.com/api/fundamentals/{sym}"
            r = requests.get(url, params={"api_token": EODHD_KEY, "fmt": "json"}, timeout=12)
            if r.status_code == 200:
                j = r.json()
                out[t] = j
                _cache_set(_cache_funds, t, j)
            else: out[t] = {}
        except Exception: out[t] = {}
        time.sleep(0.25)
    return out

def _get_nested(dct, path, default=np.nan):
    cur = dct
    for p in path:
        if not isinstance(cur, dict) or p not in cur: return default
        cur = cur[p]
    return cur

def compute_metrics(df_uni, prices, funds):
    rows = []
    for _, r in df_uni.iterrows():
        t = r["ticker"]
        f = funds.get(t, {}) or {}
        price = prices.get(t, np.nan)
        target = _get_nested(f, ["Highlights","TargetPrice"], np.nan)
        pe     = _get_nested(f, ["Highlights","PERatio"], np.nan)
        roe    = _get_nested(f, ["Highlights","ReturnOnEquityTTM"], np.nan)
        de     = _get_nested(f, ["Highlights","DebtToEquity"], np.nan)
        ev_eb  = _get_nested(f, ["Highlights","EnterpriseValueEbitda"], np.nan)
        mcap   = _get_nested(f, ["Highlights","MarketCapitalization"], np.nan)
        sec    = r["sector"] or _get_nested(f, ["General","Sector"], None)

        mom_3m = _get_nested(f, ["Technicals","Beta3Year"], np.nan)  # placeholder

        if (not math.isnan(price)) and (not math.isnan(target)) and price>0 and target>0:
            disc = (target - price)/price
        else:
            disc = np.nan

        rows.append({
            "ticker": t, "company": r["company"], "exchange": r["exchange"],
            "sector": sec if sec not in (None,"") else "Unknown",
            "price": float(price) if not math.isnan(price) else np.nan,
            "target": float(target) if not math.isnan(target) else np.nan,
            "discount": float(disc) if not math.isnan(disc) else 0.0,
            "discount_pct": float(disc*100) if not math.isnan(disc) else 0.0,
            "pe": float(pe) if not math.isnan(pe) else np.nan,
            "roe": float(roe) if not math.isnan(roe) else np.nan,
            "debt_ebitda": float(ev_eb) if not math.isnan(ev_eb) else np.nan,
            "market_cap_b": float(mcap)/1e9 if not math.isnan(mcap) else np.nan,
            "mom_3m": float(mom_3m) if not math.isnan(mom_3m) else 0.0,
            "mom_3m_pct": float(mom_3m*100) if not math.isnan(mom_3m) else 0.0,
            "next_event": None, "days_to_event": None
        })
    return pd.DataFrame(rows)

def fetch_history(ticker, exchange, days=180):
    key = f"{ticker}|hist|{days}"
    cached = _cache_get(_cache_hist, key, 21600)  # 6h
    if cached is not None: return cached
    if not EODHD_KEY: return None
    try:
        sym = ticker if "." in ticker else f"{ticker}.US"
        end = datetime.utcnow().date()
        start = end - timedelta(days=days*2)
        url = f"https://eodhd.com/api/eod/{sym}"
        r = requests.get(url, params={"api_token": EODHD_KEY, "fmt":"json", "from": start.isoformat(), "to": end.isoformat()}, timeout=12)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, list) and j:
                df = pd.DataFrame(j)[["date","open","high","low","close","volume"]]
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").tail(days)
                _cache_set(_cache_hist, key, df)
                return df
    except Exception: return None
    return None

def fetch_news_for_ticker(ticker, company):
    key = f"{ticker}|news"
    cached = _cache_get(_cache_news, key, 3600)
    if cached is not None: return cached
    out = []
    if NEWSAPI_KEY:
        try:
            frm = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
            q = f"{company} OR {ticker} stock OR shares OR earnings"
            url = "https://newsapi.org/v2/everything"
            params = {"q": q, "language": "en", "sortBy": "publishedAt", "from": frm, "pageSize": 8, "apiKey": NEWSAPI_KEY}
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 200:
                for a in r.json().get("articles", []):
                    out.append({"title": a.get("title"), "url": a.get("url"), "source": a.get("source",{}).get("name",""), "publishedAt": a.get("publishedAt","")})
        except Exception: pass
    if not out and FINNHUB_KEY:
        try:
            to = datetime.utcnow().strftime("%Y-%m-%d")
            frm = (datetime.utcnow() - timedelta(days=14)).strftime("%Y-%m-%d")
            url = "https://finnhub.io/api/v1/company-news"
            r = requests.get(url, params={"symbol": ticker.split(".")[0], "from": frm, "to": to, "token": FINNHUB_KEY}, timeout=10)
            if r.status_code == 200:
                for a in r.json():
                    out.append({"title": a.get("headline"), "url": a.get("url"), "source": a.get("source",""), "publishedAt": a.get("datetime","")})
        except Exception: pass
    _cache_set(_cache_news, key, out)
    return out