"""
Calibracion CUERVO contra el target del analista (21 MXN).

Replica los supuestos extraidos del WIP del analista:
  - Risk-free 9.21%, ERP 6.10%
  - Beta levered 0.50 (raw, no bottom-up)
  - Initial WACC 10.05%, Terminal WACC 8.50% (fade explicito)
  - Perpetuity growth 3.00%
  - Tax marginal 30%
"""
from __future__ import annotations

import sys, warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore")

import pandas as pd

from dcf_mexico.parse import parse_xbrl
from dcf_mexico.valuation import DCFAssumptions, CompanyBase, project_company
from dcf_mexico.valuation.wacc import unlever_beta

XBRL = ROOT / "data" / "raw_xbrl" / "ifrsxbrl_CUERVO_2025-4.xls"
res = parse_xbrl(XBRL)
base = CompanyBase.from_parser_dcf(res.dcf, include_leases_as_debt=True)

# Convertir beta levered del analista a unlevered (para alimentar mi modelo)
# β_u = β_L / (1 + (1-t) * D/E)
mkt_cap_at_21 = 21.0 * base.shares_outstanding / 1e6  # MDP
d_to_e_at_21 = base.financial_debt / mkt_cap_at_21
beta_l_analista = 0.50
beta_u_analista = unlever_beta(beta_l_analista, d_to_e_at_21, tax_rate=0.30)
print(f"Beta levered analista: {beta_l_analista:.3f}")
print(f"D/E (a precio 21):     {d_to_e_at_21:.3f}")
print(f"Beta unlevered impl.:  {beta_u_analista:.3f}")

# Supuestos calibrados del analista
a = DCFAssumptions(
    revenue_growth_high=0.05,
    terminal_growth=0.03,
    target_op_margin=0.22,
    sales_to_capital=1.50,
    effective_tax_base=0.30,
    marginal_tax_terminal=0.30,
    risk_free=0.0921,
    erp=0.0610,
    unlevered_beta=beta_u_analista,
    terminal_wacc_override=0.0850,    # Analista
    market_price=22.0,
)

out = project_company(base, a)

print(f"\n--- WACC ---")
print(f"  Levered Beta:        {out.wacc_result.levered_beta:.3f}")
print(f"  Cost of Equity:      {out.wacc_result.cost_equity:.2%}")
print(f"  Pretax Cost of Debt: {out.wacc_result.pretax_cost_debt:.2%}")
print(f"  Initial WACC:        {out.wacc_result.wacc:.2%}   (analista: 10.05%)")
print(f"  Terminal WACC:       {out.terminal_wacc:.2%}   (analista: 8.50%)")

print(f"\n--- Valuacion ---")
print(f"  Sum PV FCFF (10y):    {out.sum_pv_fcff:>10,.1f} MDP")
print(f"  PV Terminal:          {out.pv_terminal:>10,.1f} MDP   (analista: 55,249)")
print(f"  Enterprise Value:     {out.enterprise_value:>10,.1f} MDP   (analista: 76,228)")
print(f"  Equity Value:         {out.equity_value:>10,.1f} MDP   (analista: 74,998)")
print(f"  Value per share MXN:  {out.value_per_share:>10,.2f}      (analista TP: 21.00)")
print(f"  Diferencia vs TP:     {(out.value_per_share/21.0 - 1)*100:>+10,.1f}%")

# Reporte de drivers que ajustar para llegar a 21 exactos
print(f"\n--- Bisect para igualar TP=21 ajustando target_op_margin ---")
from copy import copy
for trial_margin in [0.20, 0.22, 0.24, 0.25, 0.26]:
    a_t = DCFAssumptions(
        revenue_growth_high=0.05,
        terminal_growth=0.03,
        target_op_margin=trial_margin,
        sales_to_capital=1.50,
        effective_tax_base=0.30,
        marginal_tax_terminal=0.30,
        risk_free=0.0921,
        erp=0.0610,
        unlevered_beta=beta_u_analista,
        terminal_wacc_override=0.0850,
        market_price=22.0,
    )
    o = project_company(base, a_t)
    print(f"  margin {trial_margin:.0%} -> value/share {o.value_per_share:>6,.2f}")

print(f"\n--- Bisect ajustando S2C (con margin 22%) ---")
for trial_s2c in [0.4, 0.5, 0.55, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 1.8, 2.2, 3.0]:
    a_t = DCFAssumptions(
        revenue_growth_high=0.05,
        terminal_growth=0.03,
        target_op_margin=0.22,
        sales_to_capital=trial_s2c,
        effective_tax_base=0.30,
        marginal_tax_terminal=0.30,
        risk_free=0.0921,
        erp=0.0610,
        unlevered_beta=beta_u_analista,
        terminal_wacc_override=0.0850,
        market_price=22.0,
    )
    o = project_company(base, a_t)
    print(f"  S2C {trial_s2c:.2f} -> value/share {o.value_per_share:>6,.2f}")

# Combos para 2-D bisect
print(f"\n--- Combos finos (margin x S2C) buscando ~21 MXN ---")
for s2c in [0.5, 0.6, 0.7, 0.8]:
    for mg in [0.18, 0.20, 0.22]:
        a_t = DCFAssumptions(
            revenue_growth_high=0.05,
            terminal_growth=0.03,
            target_op_margin=mg,
            sales_to_capital=s2c,
            effective_tax_base=0.30,
            marginal_tax_terminal=0.30,
            risk_free=0.0921,
            erp=0.0610,
            unlevered_beta=beta_u_analista,
            terminal_wacc_override=0.0850,
            market_price=22.0,
        )
        o = project_company(base, a_t)
        flag = " <-- match" if abs(o.value_per_share - 21.0) < 0.5 else ""
        print(f"  S2C={s2c:.2f}  margin={mg:.0%}  -> {o.value_per_share:>6,.2f}{flag}")
