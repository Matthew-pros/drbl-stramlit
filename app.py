from __future__ import annotations
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from data import download
from strategy import recommend, make_orders, enrich
from backtest import run_backtest

st.set_page_config(page_title="DRBL | Quant Dashboard",page_icon="📈",layout="wide")
st.markdown("""<style>
.block-container{padding-top:1.7rem;max-width:1450px}.hero{padding:1.4rem 1.6rem;border:1px solid #253046;border-radius:18px;background:linear-gradient(120deg,#111827,#18243c);margin-bottom:1.2rem}.hero h1{margin:0;color:#f8fafc;font-size:2rem}.hero p{color:#a9b7ca;margin:.45rem 0 0}.stMetric{background:#111827;border:1px solid #263349;padding:12px;border-radius:12px}
</style>""",unsafe_allow_html=True)
st.markdown('<div class="hero"><h1>DRBL · Portfolio Regime Dashboard</h1><p>Denní signály, backtesty a návrhy cílových pozic · data po uzavření amerického trhu</p></div>',unsafe_allow_html=True)

with st.sidebar:
    st.header("Nastavení")
    model=st.selectbox("Model",["DRBL + iniciační ALM","MFRM · QQQ 200DMA"])
    model_key="DRBL" if model.startswith("DRBL") else "MFRM"
    equity=st.number_input("Hodnota účtu (USD)",min_value=1000.0,value=100000.0,step=5000.0)
    init_phase=st.checkbox("Portfolio je v hotovosti (ALM)",value=True,disabled=model_key!="DRBL")
    current_asset=st.selectbox("Aktuální rotační aktivum",["(není)","SPY","QQQ","GLD","IBIT"],disabled=model_key!="DRBL")
    current_ticker=st.text_input("Aktuálně držený ticker",value="")
    current_usd=st.number_input("Aktuální pozice (USD)",min_value=0.0,value=0.0,step=1000.0)
    st.divider(); st.caption("Nákladové předpoklady pro backtest")
    commission=st.number_input("IBKR komise (USD/akcii)",min_value=0.0,value=.005,step=.001,format="%.3f")
    slippage=st.number_input("Slippage (bps na stranu)",min_value=0.0,value=2.0,step=.5)
    period=st.selectbox("Historie dat",["5y","10y","15y","max"],index=3)
    refresh=st.button("Obnovit data",use_container_width=True)

@st.cache_data(ttl=3600,show_spinner=False)
def load_market(period):
    # TQQQ/UPRO prices are used only for current recommendation ticker mapping; indicators use unlevered assets.
    return download(["SPY","QQQ","GLD","IBIT"],period)

try:
    if refresh: st.cache_data.clear()
    data=load_market(period)
except Exception as exc:
    st.error(f"Nepodařilo se načíst tržní data: {exc}"); st.stop()

st.caption(f"Poslední dostupná svíčka: {max(df.index.max() for df in data.values()).date()} · Zdroj: Yahoo Finance (adjusted OHLCV)")
if model_key=="MFRM":
    rec=recommend("MFRM",data,equity,current_ticker=current_ticker or None,current_usd=current_usd)
else:
    rec=recommend("DRBL",data,equity,current_asset=None if current_asset=="(není)" else current_asset,current_ticker=current_ticker or None,current_usd=current_usd,init_phase=init_phase)

k1,k2,k3,k4=st.columns(4)
k1.metric("Model",rec.model); k2.metric("Doporučení",rec.action); k3.metric("Ticker",rec.ticker or "CASH"); k4.metric("Cílová pozice",f"${rec.target_usd:,.0f}")
st.info(rec.reason)
orders=make_orders(rec,commission,slippage)
if orders:
    st.subheader("Návrh pro exekuci")
    st.dataframe(pd.DataFrame(orders),hide_index=True,use_container_width=True)
    st.warning("Aplikace příkaz automaticky neposílá. Před zadáním ověř ticker, cenu, portfolio a dostupný cash; model používá závěrečná denní data.")

if model_key=="DRBL":
    scores=rec.metrics.get("rotation_scores",{})
    if scores:
        st.subheader("Měsíční skóre rotace (12–1 momentum / volatilita 60D)")
        st.dataframe(pd.DataFrame({"Skóre":scores}).sort_values("Skóre",ascending=False).style.format("{:.3f}"),use_container_width=True)
    a,b=st.columns(2)
    with a: st.metric("ADX (14)",f"{rec.metrics.get('adx14',np.nan):.1f}" if np.isfinite(rec.metrics.get('adx14',np.nan)) else "n/a")
    with b: st.metric("RVOL (20/200)",f"{rec.metrics.get('rvol',np.nan):.2f}" if np.isfinite(rec.metrics.get('rvol',np.nan)) else "n/a")

st.divider(); st.header("Backtest · QQQ")
st.caption("Signál ze závěru dne je realizován na open následující seance. Náklady: komise za akcii (min. $1) + slippage na každý obchod. Výsledky z minulosti nezaručují budoucí výnos.")
col1,col2=st.columns([1,3])
with col1:
    bt_model=st.selectbox("Backtest strategie",["MFRM sizing + 200DMA","Základní 200DMA · 100 %"],key="bt_model")
    starting=st.number_input("Počáteční kapitál",min_value=1000.0,value=100000.0,step=5000.0,key="start_cap")
    max_exp=st.slider("Maximální expozice (MFRM)",1.0,1.5,1.5,.05)
try:
    qqq=data["QQQ"]
    bt,metrics=run_backtest(qqq,model="MFRM" if bt_model.startswith("MFRM") else "BASIC200",initial_cash=starting,commission_per_share=commission,slippage_bps=slippage,max_exposure=max_exp)
    with col2:
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=bt.index,y=bt.equity,name="Strategie",line=dict(color="#45d6a1",width=2)))
        fig.add_trace(go.Scatter(x=bt.index,y=bt.benchmark_equity,name="QQQ buy & hold",line=dict(color="#7aa2ff",width=1.7)))
        fig.update_layout(height=360,template="plotly_dark",margin=dict(l=8,r=8,t=10,b=8),yaxis_title="Equity (USD)",legend=dict(orientation="h"))
        st.plotly_chart(fig,use_container_width=True)
    m1,m2,m3,m4,m5=st.columns(5)
    m1.metric("CAGR",f"{metrics['CAGR']:.2%}"); m2.metric("Max DD",f"{metrics['Max drawdown']:.2%}"); m3.metric("Sharpe",f"{metrics['Sharpe']:.2f}"); m4.metric("Profit factor",f"{metrics['Profit factor']:.2f}"); m5.metric("Čistý výnos",f"{metrics['Net profit']:.2%}")
    st.dataframe(pd.DataFrame([metrics]),hide_index=True,use_container_width=True)
    st.download_button("Stáhnout equity křivku CSV",bt.to_csv().encode("utf-8"),"backtest_equity.csv","text/csv")
except Exception as exc:
    st.warning(f"Backtest zatím nelze spočítat: {exc}")

with st.expander("Pravidla a omezení modelu"):
    st.markdown("""
**DRBL + ALM:** ALM pracuje jen se SPY/QQQ a při drawdownu od dosavadního maxima alespoň 30 % investuje 15 % equity, při alespoň 50 % 20 %. Toto je přesné znění vložené specifikace; trvalá 15% rezerva zůstává v cash. Po ALM běží měsíční rotace mezi SPY, QQQ, GLD a IBIT: 12–1 momentum dělené anualizovanou 60denní volatilitou, 8% relativní buffer. V DRBL jsou pro SPY/QQQ 40denní breakout a 20denní exit; u GLD/IBIT 100denní regresní sklon a průraz MA + 2σ. ADX(14) je Wilderův výpočet; 3× ETF se vybírá jen pro SPY/QQQ při ADX > 25 a RVOL > 1.4. GLD/IBIT zůstávají bez páky.

**MFRM 200DMA:** long-only QQQ nad SMA200; sizing 50 % při ADX < 20, 120 % při ADX > 30, úprava ×0.7 při ATR ratio >2.5, úprava ×1.2 při RVOL >1.8, limit 150 %. Pod SMA200 je cílová expozice nula.

Rotace se v živém doporučení vyhodnocuje z posledních dostupných uzavřených denních dat; uživatel zvolí právě držené aktivum. Historický backtest tohoto dashboardu pokrývá MFRM/200DMA a baseline, nikoli plný multi-asset DRBL/ALM, protože ten vyžaduje historické holdings, cashflows a dostupná data IBIT od jeho vzniku. Výsledky závisí na adjustovaných datech Yahoo Finance a zvolených nákladech. Není to automatické provádění obchodů ani investiční doporučení.
""")
