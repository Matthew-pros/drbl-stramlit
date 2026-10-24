"""Long-only daily backtest with next-session-open fills, costs and benchmark."""
from __future__ import annotations
import numpy as np
import pandas as pd
from strategy import enrich, mfrm_target


def _stats(returns: pd.Series, equity: pd.Series, trades: int) -> dict:
    returns=returns.dropna()
    if returns.empty: return {}
    yrs=max(len(returns)/252, 1/252)
    cagr=float((equity.iloc[-1]/equity.iloc[0])**(1/yrs)-1) if equity.iloc[0]>0 and equity.iloc[-1]>=0 else np.nan
    dd=equity/equity.cummax()-1
    vol=returns.std(ddof=1)*np.sqrt(252) if len(returns)>1 else np.nan
    sharpe=returns.mean()*252/vol if vol and np.isfinite(vol) else np.nan
    gains=returns[returns>0].sum(); losses=-returns[returns<0].sum()
    return {"CAGR":cagr,"Max drawdown":float(dd.min()),"Sharpe":float(sharpe),"Profit factor":float(gains/losses) if losses>0 else np.inf,"Net profit":float(equity.iloc[-1]/equity.iloc[0]-1),"Trades":int(trades),"Volatility":float(vol) if np.isfinite(vol) else np.nan}


def run_backtest(df: pd.DataFrame, model="MFRM", start=None, initial_cash=100_000,
                 commission_per_share=.005, min_commission=1.0, slippage_bps=2.0,
                 max_exposure=1.5, mfrm_ticker="QQQ") -> tuple[pd.DataFrame,dict]:
    x=enrich(df)
    if start is not None: x=x.loc[pd.Timestamp(start):]
    if len(x)<3: raise ValueError("Pro backtest jsou potřeba alespoň 3 denní svíčky")
    model=model.upper()
    if model=="200MA":
        # Daily close signal is known at close; executed at following open.
        targets=pd.Series([mfrm_target(r,max_exposure) for _,r in x.iterrows()],index=x.index).shift(1).fillna(0)
    elif model=="BASIC200":
        targets=(x.close>x.ma200).astype(float).shift(1).fillna(0)
    elif model=="MFRM":
        targets=pd.Series([mfrm_target(r,max_exposure) for _,r in x.iterrows()],index=x.index).shift(1).fillna(0)
    else: raise ValueError("Backtest model musí být BASIC200 nebo MFRM/200MA")
    cash=float(initial_cash); shares=0.0; prev_equity=float(initial_cash); rows=[]; ntrades=0
    for i,(dt,r) in enumerate(x.iterrows()):
        op=float(r.open); close=float(r.close); desired=float(targets.loc[dt])
        equity_open=cash+shares*op
        desired_shares=desired*equity_open/op
        delta=desired_shares-shares
        if abs(delta)>1e-9:
            px=op*(1+slippage_bps/10000*np.sign(delta))
            commission=max(min_commission,abs(delta)*commission_per_share)
            cash-=delta*px+commission; shares=desired_shares; ntrades+=1
        equity_close=cash+shares*close
        daily_ret=equity_close/prev_equity-1 if prev_equity else 0
        rows.append({"date":dt,"close":close,"ma200":r.ma200,"adx14":r.adx14,"rvol":r.rvol,"atr_ratio":r.atr_ratio,"target_exposure":desired,"shares":shares,"equity":equity_close,"return":daily_ret})
        prev_equity=equity_close
    out=pd.DataFrame(rows).set_index("date")
    bench=(1+x.close.pct_change().fillna(0)).cumprod()*initial_cash
    out["benchmark_equity"]=bench.reindex(out.index)
    metrics=_stats(out["return"],out.equity,ntrades)
    metrics["Benchmark net profit"]=float(out.benchmark_equity.iloc[-1]/initial_cash-1)
    metrics["Benchmark max drawdown"]=float((out.benchmark_equity/out.benchmark_equity.cummax()-1).min())
    metrics["ticker"]=mfrm_ticker
    return out,metrics
