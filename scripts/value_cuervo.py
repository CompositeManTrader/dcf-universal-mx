"""
Valuacion DCF end-to-end de CUERVO usando el parser + motor Damodaran MX.

Output:
  - Print del WACC, proyeccion 10y, terminal, equity value/share
  - Tornado de sensibilidad
  - Matriz growth x margin
  - Excel: data/valuations/CUERVO_DCF.xlsx con todas las pestanias
"""
from __future__ import annotations

import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import pandas as pd

from dcf_mexico.parse import parse_xbrl
from dcf_mexico.valuation import (
    DCFAssumptions,
    CompanyBase,
    project_company,
    tornado,
    matrix,
)
from dcf_mexico.valuation.dcf_fcff import CompanyBase  # explicit


XBRL = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
OUT = ROOT / "data" / "valuations" / "CUERVO_DCF.xlsx"
OUT.parent.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------------
# 1) Parsear XBRL
# -------------------------------------------------------------------
print(f"\n>>> Paso 1: parseo XBRL {XBRL.name}")
res = parse_xbrl(XBRL)
print(f"  Ticker: {res.info.ticker}  Periodo: {res.info.period_end}")
print(f"  Revenue: {res.income.revenue/1e6:,.1f} MDP  EBIT: {res.income.ebit/1e6:,.1f} MDP")
print(f"  Validacion: {'OK' if res.validation.ok else 'CON ISSUES'}")

# -------------------------------------------------------------------
# 2) Construir base
# -------------------------------------------------------------------
base = CompanyBase.from_parser_dcf(res.dcf, include_leases_as_debt=True)
print(f"\n>>> Paso 2: snapshot base (MDP)")
print(f"  Revenue 12M:        {base.revenue:>10,.1f}")
print(f"  EBIT 12M:           {base.ebit:>10,.1f}  (margin {base.ebit/base.revenue:.2%})")
print(f"  Interest expense:   {base.interest_expense:>10,.1f}")
print(f"  Cash:               {base.cash:>10,.1f}")
print(f"  Total Debt+Lease:   {base.financial_debt:>10,.1f}")
print(f"  Effective tax rate: {base.effective_tax_rate:.2%}")
print(f"  Shares (mn):        {base.shares_outstanding/1e6:>10,.2f}")

# -------------------------------------------------------------------
# 3) Definir supuestos (drivers del analista)
# -------------------------------------------------------------------
# CUERVO: spirits / beverages -> Damodaran "Beverage (Alcoholic)" Global:
#   unlevered beta ~0.78, S2C ~1.1, target margin ~22%
# Mercado MX 2026: M-BONO 10Y ~9.5%, ERP MX ~6.8%, marginal tax 30%

# Precio actual CUERVO.MX (poner el ultimo de cierre, ej. 28-30 MXN abr-26)
MARKET_PRICE_MXN = 22.0  # placeholder - actualizar con cotizacion real

a = DCFAssumptions(
    revenue_growth_high=0.05,        # 5% / año Y1-Y5 (consenso analista para spirits MX)
    terminal_growth=0.035,            # ~ inflacion MX largo plazo
    target_op_margin=0.22,            # CUERVO actual 22.4%, sostener
    # S2C: CUERVO actual ~0.54 (deprimido por aging de agave en inventario).
    # Damodaran Beverage Alcoholic Global = 1.71. Tomamos 1.50 como termino medio.
    sales_to_capital=1.50,
    effective_tax_base=base.effective_tax_rate,
    marginal_tax_terminal=0.30,
    risk_free=0.0950,
    erp=0.0680,
    unlevered_beta=0.78,              # Damodaran Beverage Alcoholic Global
    market_price=MARKET_PRICE_MXN,
)
print(f"\n>>> Paso 3: assumptions")
print(f"  Revenue growth Y1-5: {a.revenue_growth_high:.2%}")
print(f"  Terminal growth:     {a.terminal_growth:.2%}")
print(f"  Target op margin:    {a.target_op_margin:.2%}")
print(f"  Sales/Capital:       {a.sales_to_capital:.2f}")
print(f"  Risk free MX:        {a.risk_free:.2%}")
print(f"  ERP MX:              {a.erp:.2%}")
print(f"  Unlevered beta:      {a.unlevered_beta:.2f}")
print(f"  Market price (MXN):  {a.market_price:.2f}")

# -------------------------------------------------------------------
# 4) Proyectar y valuar
# -------------------------------------------------------------------
out = project_company(base, a)

print(f"\n>>> Paso 4: WACC")
print(f"  D/E:                 {out.wacc_result.debt_to_equity:.2f}")
print(f"  Levered Beta:        {out.wacc_result.levered_beta:.3f}")
print(f"  Cost of Equity:      {out.wacc_result.cost_equity:.2%}")
print(f"  Synthetic Rating:    {out.wacc_result.rating}")
print(f"  Pretax Cost of Debt: {out.wacc_result.pretax_cost_debt:.2%}")
print(f"  Initial WACC:        {out.wacc_result.wacc:.2%}")
print(f"  Terminal WACC:       {out.terminal_wacc:.2%}")

print(f"\n>>> Paso 5: proyeccion 10y")
print(out.projection_table().to_string(index=False))

print(f"\n>>> Paso 6: valuacion")
print(out.summary_table().to_string(index=False))

# -------------------------------------------------------------------
# 7) Sensibilidad: tornado
# -------------------------------------------------------------------
print(f"\n>>> Paso 7: tornado de sensibilidad")
torn = tornado(base, a)
print(torn.to_string(index=False))

# -------------------------------------------------------------------
# 8) Matriz growth x margin
# -------------------------------------------------------------------
print(f"\n>>> Paso 8: matriz growth x margin (value/share MXN)")
mat = matrix(
    base, a,
    x_driver="revenue_growth_high",
    y_driver="target_op_margin",
    x_values=[0.02, 0.04, 0.05, 0.06, 0.08, 0.10],
    y_values=[0.18, 0.20, 0.22, 0.24, 0.26],
)
print(mat.to_string())

# -------------------------------------------------------------------
# 9) Excel output
# -------------------------------------------------------------------
print(f"\n>>> Paso 9: guardando Excel {OUT}")
with pd.ExcelWriter(OUT, engine="openpyxl") as w:
    out.summary_table().to_excel(w, sheet_name="DCF Summary", index=False)
    out.projection_table().to_excel(w, sheet_name="Projection 10y", index=False)
    a.to_series().to_frame("Valor").to_excel(w, sheet_name="Assumptions")
    pd.Series({
        "Revenue 12M":          base.revenue,
        "EBIT 12M":             base.ebit,
        "Interest expense":     base.interest_expense,
        "Cash":                 base.cash,
        "Debt + Leases":        base.financial_debt,
        "Minority interest":    base.minority_interest,
        "Non-op assets":        base.non_operating_assets,
        "Shares":               base.shares_outstanding,
        "Effective tax rate":   base.effective_tax_rate,
    }).to_frame("Valor (MDP)").to_excel(w, sheet_name="Base")
    torn.to_excel(w, sheet_name="Tornado", index=False)
    mat.to_excel(w, sheet_name="Sensitivity Matrix")

print(f"\n[DONE] Excel: {OUT}")
