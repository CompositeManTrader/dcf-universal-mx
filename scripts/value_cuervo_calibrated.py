"""
Valuacion CUERVO CALIBRADA contra el WIP del analista (TP=21 MXN).

Supuestos finales:
  - Risk-free 9.21%, ERP 6.10% (analista)
  - Beta levered 0.50 (raw historical CUERVO vs IPC, no bottom-up)
  - Terminal WACC 8.50% (analista, fade desde 11.4%)
  - Sales-to-Capital 0.70 (refleja inventario aging de agave; menor que beverage industry 1.71)
  - Target op margin 22% (sostener el actual)
  - Crecimiento Y1-5: 5%, terminal 3%

Replica del analista: 21.74 MXN vs analista 21.00 -> 4% diff (within DCF noise).
"""
from __future__ import annotations

import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import pandas as pd

from dcf_mexico.parse import parse_xbrl
from dcf_mexico.valuation import DCFAssumptions, CompanyBase, project_company, tornado, matrix
from dcf_mexico.valuation.wacc import unlever_beta

XBRL = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
OUT = ROOT / "data" / "valuations" / "CUERVO_DCF_CALIBRATED.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)

MARKET_PRICE = 22.0   # placeholder, reemplazar con cierre de hoy
ANALYST_TP   = 21.0

# 1) Parser
res = parse_xbrl(XBRL)
base = CompanyBase.from_parser_dcf(res.dcf, include_leases_as_debt=True)

# 2) Beta unlevered implicito al beta levered del analista (0.5) al precio del analista (21)
mkt_cap_at_tp = ANALYST_TP * base.shares_outstanding / 1e6
d_to_e_at_tp = base.financial_debt / mkt_cap_at_tp
beta_unlev_calibrated = unlever_beta(0.50, d_to_e_at_tp, tax_rate=0.30)

# 3) Assumptions calibradas
a = DCFAssumptions(
    revenue_growth_high=0.05,
    terminal_growth=0.03,
    target_op_margin=0.22,
    sales_to_capital=0.70,             # calibrado para replicar al analista
    effective_tax_base=0.30,
    marginal_tax_terminal=0.30,
    risk_free=0.0921,
    erp=0.0610,
    unlevered_beta=beta_unlev_calibrated,
    terminal_wacc_override=0.0850,     # analista
    market_price=MARKET_PRICE,
)

# 4) DCF
out = project_company(base, a)

# Print resumen
print(f"\n{'='*70}")
print(f"  CUERVO DCF — CALIBRADO vs analista WIP (TP=21 MXN)")
print(f"{'='*70}")
print(f"  Periodo base:       {res.info.period_end}")
print(f"  Beta unlevered (cal):{beta_unlev_calibrated:.3f}")
print(f"  Beta levered:       {out.wacc_result.levered_beta:.3f}    (analista: 0.50)")
print(f"  Initial WACC:       {out.wacc_result.wacc:.2%}    (analista: 10.05%)")
print(f"  Terminal WACC:      {out.terminal_wacc:.2%}    (analista: 8.50%)")
print(f"")
print(f"  EV:                 {out.enterprise_value:>10,.0f} MDP   (analista: 76,228)")
print(f"  Equity Value:       {out.equity_value:>10,.0f} MDP   (analista: 74,998)")
print(f"  Value per share:    {out.value_per_share:>10,.2f} MXN  (analista TP: 21.00)")
print(f"  Diff vs analista:   {(out.value_per_share/ANALYST_TP - 1)*100:>+10,.1f}%")
print(f"")
print(f"  Market price:       {MARKET_PRICE:>10,.2f} MXN")
print(f"  Upside/(Downside):  {out.upside_pct*100:>+10,.1f}%")
print(f"{'='*70}\n")

# Tornado sobre el caso calibrado
print("TORNADO de sensibilidad:")
torn = tornado(base, a)
print(torn.to_string(index=False))

# Matriz growth x margin
print("\nMATRIZ growth x margin:")
mat = matrix(
    base, a,
    x_driver="revenue_growth_high",
    y_driver="target_op_margin",
    x_values=[0.02, 0.04, 0.05, 0.06, 0.08],
    y_values=[0.18, 0.20, 0.22, 0.24, 0.26],
)
print(mat.to_string())

# Excel
with pd.ExcelWriter(OUT, engine="openpyxl") as w:
    out.summary_table().to_excel(w, sheet_name="DCF Summary", index=False)
    out.projection_table().to_excel(w, sheet_name="Projection 10y", index=False)
    a.to_series().to_frame("Valor").to_excel(w, sheet_name="Assumptions")
    pd.DataFrame([
        {"Concepto": "Analyst TP",     "Valor": 21.00, "Unidad": "MXN"},
        {"Concepto": "Calibrated DCF", "Valor": round(out.value_per_share, 2), "Unidad": "MXN"},
        {"Concepto": "Diferencia",     "Valor": round((out.value_per_share/21 - 1)*100, 2), "Unidad": "%"},
        {"Concepto": "Initial WACC",   "Valor": round(out.wacc_result.wacc*100, 2), "Unidad": "%"},
        {"Concepto": "Terminal WACC",  "Valor": round(out.terminal_wacc*100, 2), "Unidad": "%"},
    ]).to_excel(w, sheet_name="Calibration", index=False)
    torn.to_excel(w, sheet_name="Tornado", index=False)
    mat.to_excel(w, sheet_name="Sensitivity Matrix")

print(f"\n[DONE] {OUT}")
