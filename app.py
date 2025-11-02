import os
import time
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Duncan Screener", layout="wide")

FINNHUB_KEY = st.secrets.get("FINNHUB_KEY", "")

if not FINNHUB_KEY:
    st.error("Missing FINNHUB_KEY in Streamlit Secrets.")
    st.stop()

try:
    tickers_df = pd.read_csv("tickers.csv")
except Exception as e:
    st.error(f"Cannot read tickers.csv: {e}")
    st.stop()

if "ticker" not in tickers_df.columns:
    st.error("Missing 'ticker' column in tickers.csv.")
    st.stop()

tickers = tickers_df["ticker"].astype(str).str.strip().dropna().unique().tolist()

def get_quote(symbol, token):
    url = "https://finnhub.io/api/v1/quote"
    params = {"symbol": symbol, "token": token}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json() or {}
        return {
            "price": data.get("c"),
            "prev_close": data.get("pc"),
            "change_pct": data.get("dp")
        }
    except Exception:
        return {"price": None, "prev_close": None, "change_pct": None}

rows = []
for t in tickers:
    q = get_quote(t, FINNHUB_KEY)
    price = q["price"]
    change_pct = q["change_pct"]
    if price is None:
        target_12m = None
        discount_pct = None
    else:
        target_12m = round(price * 1.15, 2)
        discount_pct = round((target_12m - price) / target_12m * 100, 2)
    mom_3m_pct = change_pct if isinstance(change_pct, (int, float)) else 0.0
    score = 0.0
    if isinstance(discount_pct, (int, float)):
        score += max(0.0, min(discount_pct, 40.0))
    score += max(0.0, min(mom_3m_pct if mom_3m_pct else 0.0, 15.0))
    score += 5.0
    score = round(score, 1)
    if score >= 70:
        category = "A"
    elif score >= 50:
        category = "B"
    else:
        category = "C"
    rows.append({
        "ticker": t,
        "price": price,
        "target_12m": target_12m,
        "discount_pct": discount_pct,
        "mom_3m_pct": mom_3m_pct,
        "duncan_score": score,
        "category": category
    })
    time.sleep(0.15)

df = pd.DataFrame(rows)
for col in ["price", "target_12m", "discount_pct", "mom_3m_pct", "duncan_score"]:
    df[col] = pd.to_numeric(df[col], errors="coerce")

st.title("Duncan Screener")

min_score = st.slider("Min Duncan Score", 0, 100, 0)
fdf = df[df["duncan_score"] >= min_score].copy()

a_count = (fdf["category"] == "A").sum()
b_count = (fdf["category"] == "B").sum()
c_count = (fdf["category"] == "C").sum()
avg_upside = ((fdf["target_12m"] - fdf["price"]) / fdf["price"] * 100).mean()

st.metric("A", a_count)
st.metric("B", b_count)
st.metric("C", c_count)
st.metric("Avg Upside", f"{0.0 if pd.isna(avg_upside) else round(avg_upside,1)}%")

plot_df = fdf.dropna(subset=["discount_pct", "mom_3m_pct"]).copy()
# --- Adattisztítás a Plotly diagram előtt ---
for col in ["discount_pct", "mom_3m_pct"]:
    plot_df[col] = pd.to_numeric(plot_df[col], errors="coerce").fillna(0.0)
# -------------------------------------------
if not plot_df.empty:
    fig = px.scatter(
        plot_df,
        x="discount_pct",
        y="mom_3m_pct",
        color="duncan_score",
        hover_name="ticker",
        labels={
            "discount_pct": "Target discount (%)",
            "mom_3m_pct": "Momentum proxy (%)",
            "duncan_score": "Duncan Score"
        }
    )
    fig.update_layout(height=420, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Nincs elég adat a buborékdiagramhoz.")

show_cols = ["ticker", "price", "target_12m", "discount_pct", "mom_3m_pct", "duncan_score", "category"]
st.dataframe(fdf[show_cols].sort_values("duncan_score", ascending=False), use_container_width=True)
