# DRBL · Streamlit Portfolio Regime Dashboard

Český dashboard pro denní vyhodnocení dvou oddělených modelů:

1. **DRBL + ALM** – iniciační nákupní tranše při poklesu od ATH, poté měsíční relativní momentum rotace a denní signál pro základní/3× ETF nebo cash.
2. **MFRM 200DMA** – samostatná long-only QQQ strategie nad 200denním průměrem, s sizingem podle ADX, ATR a RVOL.

Aplikace poskytuje návrh tickeru a cílové pozice USD, graf portfolia, backtest MFRM proti QQQ buy & hold a export equity křivky. **Neodesílá automatické burzovní příkazy.**

## Spuštění

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
streamlit run app.py
```

Data bere z Yahoo Finance přes `yfinance` s `auto_adjust=True`. Počkejte na uzavřenou denní svíčku; během obchodní seance může poslední svíčka být neúplná. Streamlit Cloud může být omezen dostupností Yahoo Finance.

## Pravidla

### DRBL + ALM

- Universe: SPY, QQQ, GLD, IBIT; párové leveraged tickery SPY→UPRO, QQQ→TQQQ. GLD/IBIT bez páky.
- ALM pouze pro SPY/QQQ, pokud portfolio zůstává v hotovosti: drawdown ≥30 % → 15 % equity, ≥50 % → 20 % equity. Rezerva 15 % equity zůstává v hotovosti.
- Rotace: 12–1 momentum `(Close[t-22]/Close[t-252])-1`, děleno annualizovanou 60denní volatilitou. Nové aktivum přebírá vedení při překonání aktuálního skóre o 8 %.
- SPY/QQQ signál: close ≥ maximum předchozích 40 high pro vstup; close ≤ minimum předchozích 20 low pro výstup.
- GLD/IBIT: 100denní OLS slope >0 a close nad MA100 + 2σ pro vstup; slope <0 pro výstup.
- ADX(14) používá Wilderovo vyhlazování. RVOL = průměrný volume 20 dní / průměrný volume 200 dní. Při vstupním signálu a ADX>25 a RVOL>1.4 se SPY/QQQ přepne na 3× ETF; jinak zůstává 1×. IBIT/GLD se nepákovají.
- Provozní alokace 85 % equity při vstupním signálu; při výstupu cash.

### MFRM 200DMA

- Close nad SMA200: výchozí expozice 100 %.
- ADX<20 → 50 %; ADX>30 → 120 %.
- ATR14 / 252denní průměr ATR14 >2.5 → sizing ×0.7.
- RVOL>1.8 → sizing ×1.2; strop 150 %.
- Close pod SMA200 → 0 %.

## Backtest a náklady

Signál z denního close se v backtestu realizuje na následujícím obchodním dni za open, takže se nepoužívá budoucí close pro fill. Slippage se přičítá na každou stranu. Komise je nastavitelná v USD/akcii s minimem $1 za pokyn. Backtest MFRM používá QQQ a je srovnán s buy & hold QQQ. Není zde plný historický backtest DRBL/ALM; k němu je třeba zavést historii holdings, cashflows a pravidla měsíčních rotací bez survivorship/lookahead bias. Minulé výnosy nejsou zárukou budoucích.

## Bezpečnost a limity

- Aplikace pouze navrhuje cílové pozice. IBKR připojení ani automatické zadávání příkazů nejsou implementovány.
- Yahoo Finance není garantovaný zdroj a může vracet zpožděná či revidovaná data.
- 3× ETF mají denní reset páky a výrazné path dependency; výsledky podkladového backtestu nejsou proxy za leveraged ETF.
- Před nasazením ověřte matematiku a výsledky na nezávislém zdroji dat a paper účtu.
