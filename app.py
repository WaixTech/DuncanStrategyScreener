import os, time, math, json, requests, pandas as pd, numpy as np
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv
from scoring import compute_duncan_score
from data_sources import (
    load_universe, fetch_prices_batch, fetch_fundamentals_batch,
    compute_metrics, fetch_news_for_ticker, fetch_history
)

load_dotenv()
st.set_page_config(page_title="Duncan Screener (Plotly)", layout="wide")
st.title("Duncan Screener & Radar — Plotly Edition")

# Sidebar
with st.sidebar:
    st.subheader("Status")
    st.write("Plotly visuals • Lazy News • Batch+Cache")
    st.caption("Prices 30m • Fundamentals 24h • News 60m")
    st.divider()
    hard_refresh = st.button("⚡ Force full data refresh")

df_uni = load_universe()
st.caption(f"Universe size: {len(df_uni)} tickers")

# Controls
colf1, colf2, colf3, colf4 = st.columns([1.6,1,1,1])
with colf1:
    sector = st.selectbox("Sector", options=["All"] + sorted(df_uni["sector"].dropna().unique().tolist()))
with colf2:
    min_score = st.slider("Min Duncan Score", 0, 100, 0, 1)
with colf3:
    hard_pass = st.toggle("Hard rules only", value=False)
with colf4:
    refresh = st.button("🔄 Refresh data")

# Fetch
if refresh or hard_refresh:
    st.info("Fetching prices & fundamentals…")
prices = fetch_prices_batch(df_uni["ticker"].tolist(), batch_size=10)
funds  = fetch_fundamentals_batch(df_uni, batch_size=10)

df = compute_metrics(df_uni, prices, funds)
df["duncan"] = df.apply(compute_duncan_score, axis=1)

# Filter
if sector != "All":
    dfv = df[df["sector"] == sector].copy()
else:
    dfv = df.copy()
if hard_pass:
    dfv = dfv[(dfv["discount"] >= 0.15) & (dfv["pe"].fillna(0) < 40)]
dfv = dfv[dfv["duncan"] >= min_score].copy()

# Category
def cat_row(r):
    hard_ok = (r["discount"] >= 0.15) and (r["pe"] < 40 if not math.isnan(r["pe"]) else False)
    if r["duncan"] >= 70 and hard_ok: return "A"
    if r["duncan"] >= 50 and (hard_ok or r["discount"] >= 0.12): return "B"
    return "C"
dfv["category"] = dfv.apply(cat_row, axis=1)

# Metrics
c1,c2,c3,c4 = st.columns(4)
with c1: st.metric("A", int((dfv["category"]=="A").sum()))
with c2: st.metric("B", int((dfv["category"]=="B").sum()))
with c3: st.metric("C", int((dfv["category"]=="C").sum()))
with c4:
    avg_up = dfv["discount"].dropna().mean()*100 if not dfv.empty else 0
    st.metric("Avg Upside", f"{avg_up:.1f}%")

st.divider()

# Plotly Bubble
if not dfv.empty:
    color_discrete_map = {"A":"#2ca02c", "B":"#1f77b4", "C":"#ff7f0e"}
    fig = px.scatter(
        dfv, x="discount_pct", y="mom_3m_pct",
        size="market_cap_b", color="category",
        color_discrete_map=color_discrete_map,
        hover_name="ticker", hover_data=["company","sector","pe","duncan"],
        title="Discount vs Momentum (size=cap, color=category)",
        labels={"discount_pct":"Upside %","mom_3m_pct":"3m Momentum %","market_cap_b":"Mkt Cap (B)"}
    )
    fig.update_traces(marker=dict(opacity=0.7))
    st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # Treemap by sector
    df_sec = dfv.groupby("sector").agg(cap=("market_cap_b","sum"), score=("duncan","mean")).reset_index()
    if not df_sec.empty:
        tree = px.treemap(df_sec, path=["sector"], values="cap", color="score",
                          color_continuous_scale="Viridis", title="Sector breakdown (size=cap, color=avg score)")
        st.plotly_chart(tree, use_container_width=True)
else:
    st.info("No stocks match the filters.")

st.divider()
st.subheader("Table")
st.dataframe(dfv.sort_values("duncan", ascending=False)[
    ["ticker","company","sector","price","target","discount_pct","pe","mom_3m_pct","duncan"]
].rename(columns={"discount_pct":"discount %","mom_3m_pct":"3m momentum %"}),
use_container_width=True, height=360)

# Details
st.divider()
st.subheader("Stock Details")
sel = st.selectbox("Pick a ticker", options=[""] + dfv["ticker"].tolist())
if sel:
    row = df[df["ticker"]==sel].iloc[0]
    c1,c2,c3,c4,c5 = st.columns(5)
    c1.metric("Price", f"${row['price']:.2f}" if not math.isnan(row['price']) else "—")
    c2.metric("12M Target", f"${row['target']:.2f}" if not math.isnan(row['target']) else "—")
    c3.metric("Upside", f"{row['discount']*100:.1f}%")
    c4.metric("P/E", f"{row['pe']:.1f}" if not math.isnan(row['pe']) else "—")
    c5.metric("Sector", row['sector'])

    lcol, rcol = st.columns([2,1])
    with lcol:
        st.markdown("#### Price history (120 trading days)")
        hist = fetch_history(row["ticker"], row["exchange"], days=180)
        if hist is not None and not hist.empty:
            figc = go.Figure(data=[go.Candlestick(
                x=hist["date"], open=hist["open"], high=hist["high"], low=hist["low"], close=hist["close"]
            )])
            if not math.isnan(row["target"]):
                figc.add_hline(y=row["target"], line=dict(dash="dot"), annotation_text="12M target", annotation_position="top left")
            figc.update_layout(height=420, margin=dict(l=10,r=10,t=30,b=10))
            st.plotly_chart(figc, use_container_width=True)
        else:
            st.caption("No history available.")

        st.markdown("#### News (last 14 days)")
        articles = fetch_news_for_ticker(row["ticker"], row["company"])
        if articles:
            for a in articles[:8]:
                st.markdown(f"- [{a['title']}]({a['url']}) — {a['source']} • {a['publishedAt'][:10]}")
        else:
            st.caption("No headlines in the last 14 days.")

    with rcol:
        st.markdown("#### Duncan Score")
        comp = compute_duncan_score(row, return_components=True)
        gauge = go.Figure(go.Indicator(
            mode="gauge+number",
            value=comp["total"],
            number={'suffix': " / 100"},
            gauge={'axis': {'range': [0, 100]},
                   'bar': {'color': "#1f77b4"},
                   'steps': [
                       {'range': [0, 50], 'color': "#ffe6e0"},
                       {'range': [50, 70], 'color': "#fff6cc"},
                       {'range': [70, 100], 'color': "#e0ffe6"}]},
            title={'text': "Total"}
        ))
        st.plotly_chart(gauge, use_container_width=True, height=260)
        st.markdown("#### Components")
        st.json(comp)