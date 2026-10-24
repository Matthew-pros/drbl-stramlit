"""Market data adapter for adjusted daily Yahoo Finance OHLCV."""
from __future__ import annotations
import pandas as pd
import yfinance as yf


def download(tickers, period="10y") -> dict[str,pd.DataFrame]:
    result={}
    for ticker in tickers:
        raw=yf.download(ticker,period=period,interval="1d",auto_adjust=True,progress=False,threads=False)
        if raw is None or raw.empty: raise RuntimeError(f"Yahoo Finance nevrátila data pro {ticker}")
        if isinstance(raw.columns,pd.MultiIndex):
            raw.columns=raw.columns.get_level_values(0)
        raw=raw.rename(columns={c:str(c).lower() for c in raw.columns})
        missing={"open","high","low","close","volume"}-set(raw.columns)
        if missing: raise RuntimeError(f"{ticker}: chybí sloupce {sorted(missing)}")
        result[ticker]=raw[["open","high","low","close","volume"]].dropna(subset=["close"])
    return result
