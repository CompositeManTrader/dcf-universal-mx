"""Extrae margenes y S2C actuales de cada emisora para calibrar defaults."""
import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import pandas as pd
from dcf_mexico.parse import parse_xbrl
from dcf_mexico.config import load_issuers, load_sectors, find_xbrl

_, issuers = load_issuers()
sectors = load_sectors()

rows = []
for ticker, issuer in sorted(issuers.items()):
    fp = find_xbrl(ticker)
    if fp is None:
        continue
    try:
        res = parse_xbrl(fp)
        sector = sectors.get(issuer.sector)
        rev = res.dcf.revenue                    # MDP
        ebit = res.dcf.ebit                      # MDP
        invested_cap = res.dcf.invested_capital  # MDP
        op_margin = ebit / rev if rev else 0
        s2c_actual = rev / invested_cap if invested_cap else 0
        rev_growth = res.dcf.revenue_growth
        rows.append({
            "ticker": ticker,
            "sector": issuer.sector,
            "sector_name": sector.name if sector else "?",
            "revenue_mdp": round(rev, 1),
            "ebit_mdp": round(ebit, 1),
            "op_margin_actual": round(op_margin, 4),
            "op_margin_sector_default": sector.target_op_margin if sector else 0,
            "s2c_actual": round(s2c_actual, 3),
            "s2c_sector_default": sector.sales_to_capital if sector else 0,
            "rev_growth_12m": round(rev_growth, 4),
        })
    except Exception as e:
        rows.append({"ticker": ticker, "sector": issuer.sector, "sector_name": "ERR", "error": str(e)[:50]})

df = pd.DataFrame(rows)
print(df.to_string(index=False))

# Resumen por sector
print("\n=== Promedios actuales por sector ===")
agg = df.groupby("sector").agg(
    n=("ticker", "count"),
    avg_margin_actual=("op_margin_actual", "mean"),
    avg_margin_default=("op_margin_sector_default", "mean"),
    avg_s2c_actual=("s2c_actual", "mean"),
    avg_s2c_default=("s2c_sector_default", "mean"),
).round(3)
print(agg.to_string())
