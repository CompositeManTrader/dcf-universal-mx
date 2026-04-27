"""
Batch runner: corre DCF sobre todas las emisoras configuradas en config/issuers.yaml.

Para cada ticker:
  1. Busca el XBRL en data/raw_xbrl/ (filename: ifrsxbrl_<TICKER>_*.xls)
  2. Si encuentra, parsea + DCF con sector defaults
  3. Si no, marca el ticker como "missing" pero continua

Output: data/valuations/IPC_DCF_summary.xlsx con 1 fila por emisora.
"""
from __future__ import annotations

import sys
import warnings
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import pandas as pd

from dcf_mexico.config import load_issuers
from dcf_mexico.valuation import value_one


def main() -> int:
    market, issuers = load_issuers()
    print(f"\n>>> Batch DCF: {len(issuers)} emisoras configuradas\n")
    print(f"Market defaults: Rf={market.risk_free:.2%}, ERP={market.erp:.2%}, "
          f"terminal_g={market.terminal_growth:.2%}\n")

    rows = []
    for ticker in sorted(issuers.keys()):
        row = value_one(ticker)
        rows.append(asdict(row))
        if row.error:
            print(f"  {ticker:>10}  [SKIP]  {row.error[:60]}")
        else:
            print(f"  {ticker:>10}  [OK]    DCF {row.value_per_share:>7,.2f} MXN  "
                  f"vs mkt {row.market_price:>7,.2f}  upside {row.upside_pct:>+6.1f}%")

    df = pd.DataFrame(rows)

    # Resumen de cobertura
    n_total = len(df)
    n_ok = df["error"].eq("").sum()
    n_fin = df["is_financial"].sum()
    n_missing = (~df["error"].eq("")).sum() - n_fin
    print(f"\n=== Resumen cobertura ===")
    print(f"  Total tickers:   {n_total}")
    print(f"  DCF exitoso:     {n_ok}")
    print(f"  Financieras:     {n_fin}  (excluidas, requieren DDM)")
    print(f"  XBRL faltantes:  {n_missing}")

    # Top picks (mayor upside DCF)
    df_ok = df[df["error"].eq("") & ~df["is_financial"]].copy()
    if not df_ok.empty:
        print(f"\n=== TOP 5 BUYS (mayor upside) ===")
        top_b = df_ok.nlargest(5, "upside_pct")[["ticker", "name", "sector", "value_per_share", "market_price", "upside_pct"]]
        print(top_b.to_string(index=False))

        print(f"\n=== TOP 5 SELLS (mayor downside) ===")
        top_s = df_ok.nsmallest(5, "upside_pct")[["ticker", "name", "sector", "value_per_share", "market_price", "upside_pct"]]
        print(top_s.to_string(index=False))

    # Excel output
    out = ROOT / "data" / "valuations" / "IPC_DCF_summary.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="All Issuers", index=False)
        if not df_ok.empty:
            df_ok.sort_values("upside_pct", ascending=False).to_excel(w, sheet_name="Ranked by Upside", index=False)
            df_ok.groupby("sector").agg(
                n=("ticker", "count"),
                avg_upside_pct=("upside_pct", "mean"),
                avg_wacc=("wacc", "mean"),
            ).to_excel(w, sheet_name="By Sector")

    print(f"\n[DONE] {out}")
    return 0 if n_missing == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
