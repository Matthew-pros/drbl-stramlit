"""Transparent daily signal and sizing rules for DRBL and MFRM strategies."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping
import numpy as np
import pandas as pd

UNIVERSE = {"SPY": ("SPY", "UPRO"), "QQQ": ("QQQ", "TQQQ"), "GLD": ("GLD", None), "IBIT": ("IBIT", None)}


def _col(df: pd.DataFrame, name: str) -> pd.Series:
    cols = {str(c).strip().lower(): c for c in df.columns}
    if name not in cols:
        raise ValueError(f"Data chybí sloupec {name!r}")
    return pd.to_numeric(df[cols[name]], errors="coerce")


def normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize input OHLCV columns and sort/drop invalid rows."""
    out = pd.DataFrame({k: _col(df, k) for k in ("open", "high", "low", "close", "volume")}, index=pd.to_datetime(df.index))
    out = out[~out.index.isna()].sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.dropna(subset=["open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0).all(axis=1)]
    out["volume"] = out["volume"].fillna(0).clip(lower=0)
    if len(out) and (out["high"] < out["low"]).any():
        raise ValueError("Nalezeno OHLCV, kde high < low")
    return out


def wilder_adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX using recursive Wilder smoothing, with standard initial sums."""
    x = normalize_ohlcv(df)
    high, low, close = x.high, x.low, x.close
    up, down = high.diff(), -low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = pd.concat([high-low, (high-close.shift()).abs(), (low-close.shift()).abs()], axis=1).max(axis=1)
    # Wilder smoothed sums: initial n-period sum followed by S[t]=S[t-1]-S[t-1]/n+x[t].
    def smooth(v: pd.Series) -> pd.Series:
        a = v.to_numpy(dtype=float); z = np.full(len(a), np.nan)
        if len(a) <= period: return pd.Series(z, index=v.index)
        z[period] = np.nansum(a[1:period+1])
        for i in range(period+1, len(a)): z[i] = z[i-1] - z[i-1]/period + (0.0 if np.isnan(a[i]) else a[i])
        return pd.Series(z, index=v.index)
    tr_s, p_s, m_s = smooth(tr), smooth(plus_dm), smooth(minus_dm)
    plus_di = 100 * p_s / tr_s.replace(0, np.nan)
    minus_di = 100 * m_s / tr_s.replace(0, np.nan)
    dx = 100 * (plus_di-minus_di).abs() / (plus_di+minus_di).replace(0, np.nan)
    a = dx.to_numpy(dtype=float); out = np.full(len(a), np.nan)
    first = 2*period-1
    if len(a) > first:
        out[first] = np.nanmean(a[period:first+1])
        for i in range(first+1, len(a)):
            out[i] = ((period-1)*out[i-1] + a[i])/period if np.isfinite(a[i]) else out[i-1]
    return pd.Series(out, index=x.index, name=f"ADX{period}")


def enrich(df: pd.DataFrame) -> pd.DataFrame:
    x = normalize_ohlcv(df)
    x["adx14"] = wilder_adx(x, 14)
    x["rvol"] = x.volume.rolling(20, min_periods=20).mean() / x.volume.rolling(200, min_periods=200).mean().replace(0, np.nan)
    tr = pd.concat([x.high-x.low, (x.high-x.close.shift()).abs(), (x.low-x.close.shift()).abs()], axis=1).max(axis=1)
    x["atr14"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    x["atr_ratio"] = x.atr14 / x.atr14.rolling(252, min_periods=60).mean()
    x["ma200"] = x.close.rolling(200, min_periods=200).mean()
    x["lrs100"] = x.close.rolling(100, min_periods=100).apply(lambda a: np.polyfit(np.arange(len(a)), a, 1)[0], raw=True)
    x["lrs_ma"] = x.close.rolling(100, min_periods=100).mean()
    x["lrs_std"] = x.close.rolling(100, min_periods=100).std(ddof=0)
    # Exclude current bar from Donchian bands to avoid look-ahead / impossible same-close breakout.
    x["entry40"] = x.high.shift(1).rolling(40, min_periods=40).max()
    x["exit20"] = x.low.shift(1).rolling(20, min_periods=20).min()
    x["ath"] = x.close.cummax()
    x["drawdown_ath"] = x.close / x.ath - 1
    return x


@dataclass(frozen=True)
class Recommendation:
    model: str
    action: str
    ticker: str | None
    target_usd: float
    reason: str
    date: str
    metrics: dict


def mfrm_target(row: pd.Series, max_exposure: float = 1.5) -> float:
    """MFRM exposure multiple; 0 below 200DMA; above follows stated factor matrix."""
    if not np.isfinite(row.get("ma200", np.nan)) or row.close <= row.ma200:
        return 0.0
    size = 1.0
    adx = row.get("adx14", np.nan)
    if np.isfinite(adx) and adx < 20: size = .5
    elif np.isfinite(adx) and adx > 30: size = 1.2
    ratio = row.get("atr_ratio", np.nan)
    if np.isfinite(ratio) and ratio > 2.5: size *= .7
    rv = row.get("rvol", np.nan)
    if np.isfinite(rv) and rv > 1.8: size *= 1.2
    return min(max_exposure, size)


def rotation_scores(data: Mapping[str, pd.DataFrame], asof=None) -> pd.Series:
    """12-1 month momentum divided by annualized 60-session close volatility."""
    scores = {}
    for ticker in UNIVERSE:
        if ticker not in data: continue
        x = normalize_ohlcv(data[ticker])
        if asof is not None: x = x.loc[:pd.Timestamp(asof)]
        if len(x) < 253: scores[ticker] = np.nan; continue
        c = x.close
        mom = c.iloc[-22] / c.iloc[-252] - 1
        vol = c.pct_change().tail(60).std(ddof=1) * np.sqrt(252)
        scores[ticker] = mom / vol if vol and np.isfinite(vol) else np.nan
    return pd.Series(scores, dtype=float).sort_values(ascending=False)


def choose_rotation(scores: pd.Series, current: str | None, buffer: float = .08) -> str | None:
    valid = scores.dropna()
    if valid.empty: return current
    candidate = str(valid.index[0])
    if current not in valid.index: return candidate
    old, new = float(valid[current]), float(valid[candidate])
    should_switch = new > old * (1+buffer) if old > 0 else new > old + buffer
    return candidate if candidate != current and should_switch else current


def drbl_signal(ticker: str, df: pd.DataFrame) -> tuple[str, str, dict]:
    x = enrich(df)
    if len(x) < 2: return "HOLD", "Nedostatek dat", {}
    r = x.iloc[-1]
    if ticker in ("SPY", "QQQ"):
        entry = bool(np.isfinite(r.entry40) and r.close >= r.entry40)
        exit_ = bool(np.isfinite(r.exit20) and r.close <= r.exit20)
    else:
        entry = bool(np.isfinite(r.lrs100) and r.lrs100 > 0 and r.close > r.lrs_ma + 2*r.lrs_std)
        exit_ = bool(np.isfinite(r.lrs100) and r.lrs100 < 0)
    m = {"close": float(r.close), "adx14": float(r.adx14) if np.isfinite(r.adx14) else np.nan,
         "rvol": float(r.rvol) if np.isfinite(r.rvol) else np.nan,
         "entry": entry, "exit": exit_, "drawdown_ath": float(r.drawdown_ath)}
    if exit_: return "CASH", "Prodejní pravidlo DRBL je aktivní", m
    if entry:
        leveraged = ticker in ("SPY", "QQQ") and r.adx14 > 25 and r.rvol > 1.4
        base, lev = UNIVERSE[ticker]
        return ("LEVERAGED" if leveraged else "BASE", "Vstupní filtr aktivní; ADX/RVOL určují sizing", m)
    return "CASH", "Vstupní filtr není aktivní", m


def recommend(model: str, data: Mapping[str, pd.DataFrame], equity: float, current_asset: str | None = None,
              current_ticker: str | None = None, current_usd: float = 0, init_phase: bool = False,
              commission_per_share: float = .005, slippage_bps: float = 2) -> Recommendation:
    if equity <= 0: raise ValueError("Equity musí být kladná")
    dates = [normalize_ohlcv(v).index[-1] for v in data.values() if len(v)]
    if not dates: raise ValueError("Nejsou dostupná žádná data")
    date = str(max(dates).date())
    model = model.upper()
    if model == "MFRM":
        if "QQQ" not in data: raise ValueError("Pro MFRM jsou zapotřebí data QQQ")
        x = enrich(data["QQQ"]); r = x.iloc[-1]; exposure = mfrm_target(r)
        target = equity * exposure
        action = "BUY/REBALANCE" if target > current_usd * 1.01 else "SELL/CASH" if target < current_usd * .99 else "HOLD"
        return Recommendation("MFRM 200DMA", action, "QQQ" if target else None, target,
            f"Close vs MA200; sizing podle ADX/ATR/RVOL. Expozice {exposure:.0%}.", date,
            {k: float(r[k]) if np.isfinite(r[k]) else np.nan for k in ("close","ma200","adx14","rvol","atr_ratio")})
    if model != "DRBL": raise ValueError("Model musí být DRBL nebo MFRM")
    if init_phase and current_usd <= 0:
        candidates=[]
        for ticker in ("SPY","QQQ"):
            if ticker in data:
                x=enrich(data[ticker]); r=x.iloc[-1]; dd=float(r.drawdown_ath)
                if dd <= -.50: candidates.append((dd,ticker,.20))
                elif dd <= -.30: candidates.append((dd,ticker,.15))
        if candidates:
            dd,ticker,pct=sorted(candidates)[0]
            return Recommendation("DRBL + ALM", "BUY", ticker, equity*pct,
                f"ALM iniciační nákup, drawdown {dd:.1%}; permanentní rezerva min. 15 %.", date,
                {"drawdown_ath":dd,"allocation_pct":pct})
        return Recommendation("DRBL + ALM", "HOLD CASH", None, 0, "ALM čeká na pokles SPY/QQQ o alespoň 30 % od historického maxima.", date,{})
    if not all(t in data for t in UNIVERSE): raise ValueError("DRBL rotace vyžaduje SPY, QQQ, GLD a IBIT")
    scores=rotation_scores(data)
    asset=choose_rotation(scores,current_asset)
    if asset is None: return Recommendation("DRBL", "HOLD CASH", None, 0, "Nelze vypočítat rotační skóre.", date,{})
    signal,reason,m=drbl_signal(asset,data[asset]); base,lev=UNIVERSE[asset]
    if signal == "CASH": ticker=None; target=0
    elif signal == "LEVERAGED": ticker=lev; target=.85*equity
    else: ticker=base; target=.85*equity
    action="HOLD" if ticker==current_ticker and abs(target-current_usd)<=max(10,equity*.01) else ("SELL/CASH" if not ticker else "BUY/REBALANCE")
    return Recommendation("DRBL",action,ticker,target,f"Rotace: {asset}. {reason}",date,{**m,"rotation_scores":scores.to_dict(),"selected_asset":asset})


def make_orders(rec: Recommendation, commission_per_share: float, slippage_bps: float) -> list[dict]:
    """Return target USD and estimated costs; no orders are sent here."""
    return [{"ticker": rec.ticker, "target_position_usd": round(rec.target_usd, 2),
             "estimated_slippage_usd": round(rec.target_usd*slippage_bps/10000, 2),
             "commission_per_share_usd": commission_per_share}] if rec.ticker else []
