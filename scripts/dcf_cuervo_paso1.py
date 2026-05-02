"""PASO 1: Valuacion CUERVO con DEFAULTS DAMODARAN-style (MX-adapted).

NOTA: Usa el PARSER de produccion (no hardcoded), garantiza valores correctos:
- Total Debt incluye leases (~20,830 MDP, no 5,696)
- Non-op assets = investments in associates (~1,149 MDP)
"""
import warnings; warnings.filterwarnings('ignore')
import sys; sys.path.insert(0, '.')
from pathlib import Path
from src.dcf_mexico.parse.xbrl_reader import parse_xbrl
from src.dcf_mexico.valuation.dcf_fcff import DCFAssumptions, CompanyBase, project_company
from src.dcf_mexico.valuation.wacc import RF_MX_DEFAULT, ERP_MX_DEFAULT, MARGINAL_TAX_MX
import pandas as pd
pd.set_option('display.width', 250)

print('='*88)
print('PASO 1: Valuacion CUERVO con DEFAULTS DAMODARAN-style (Mexico-adapted)')
print('PARSER PRODUCTION (Total Debt incluye LEASES)')
print('='*88)

# ============================================================
# A) BASE: parser real CUERVO Q4 2025 (NO hardcoded)
# ============================================================
fp = Path('data/raw_xbrl/ifrsxbrl_CUERVO_2025-4.xls')
res = parse_xbrl(fp)
base = CompanyBase.from_parser_dcf(res.dcf, include_leases_as_debt=True)

print('\n--- BASE FINANCIALS (parser production FY 2025) ---')
print(f'  Revenue:         {base.revenue:>10,.1f} MDP')
print(f'  EBIT:            {base.ebit:>10,.1f} MDP  (margin {base.ebit/base.revenue*100:.1f}%)')
print(f'  Cash:            {base.cash:>10,.1f} MDP')
print(f'  Total Debt:      {base.financial_debt:>10,.1f} MDP  (incl leases via IFRS 16)')
print(f'  Net Debt:        {base.financial_debt - base.cash:>10,.1f} MDP  (positivo = empresa apalancada)')
print(f'  Minority:        {base.minority_interest:>10,.1f} MDP')
print(f'  Non-op Assets:   {base.non_operating_assets:>10,.1f} MDP  (investments in associates)')
print(f'  Equity Book:     {base.equity_book:>10,.1f} MDP')
print(f'  Shares:          {base.shares_outstanding/1e6:>10,.2f} M')
print(f'  Effective Tax:   {base.effective_tax_rate*100:>10.1f}%')

# ============================================================
# B) ASSUMPTIONS Damodaran-style (defaults)
# ============================================================
print('\n--- ASSUMPTIONS DAMODARAN-STYLE (defaults sectoriales) ---')
ass = DCFAssumptions(
    country='Mexico',
    industry_us='Beverage (Alcoholic)',
    revenue_growth_y1=0.05,
    revenue_growth_high=0.05,
    terminal_growth=0.035,
    op_margin_y1=base.ebit/base.revenue,
    target_op_margin=0.224,
    year_of_margin_convergence=5,
    sales_to_capital=1.85,
    effective_tax_base=0.27,
    marginal_tax_terminal=MARGINAL_TAX_MX,
    risk_free=RF_MX_DEFAULT,
    erp=ERP_MX_DEFAULT,
    unlevered_beta=0.75,                  # Damodaran Beverage Alcoholic
    terminal_wacc_override=None,
    market_price=20.70,
    forecast_years=10,
    high_growth_years=5,
    override_terminal_roic=False,
    probability_of_failure=0.0,
)
print(f'  Revenue growth Y1:   {ass.revenue_growth_y1*100:>5.1f}%')
print(f'  Revenue growth Y2-5: {ass.revenue_growth_high*100:>5.1f}%')
print(f'  Terminal growth:     {ass.terminal_growth*100:>5.1f}%')
print(f'  Op margin Y1:        {ass.op_margin_y1*100:>5.2f}%')
print(f'  Target op margin:    {ass.target_op_margin*100:>5.2f}%')
print(f'  Sales-to-Capital:    {ass.sales_to_capital:>5.2f}x')
print(f'  Beta unlevered:      {ass.unlevered_beta:>5.2f}')
print(f'  Risk-free MX:        {ass.risk_free*100:>5.2f}%')
print(f'  ERP MX:              {ass.erp*100:>5.2f}%')

# ============================================================
# C) RUN DCF
# ============================================================
out = project_company(base, ass)

print()
print('='*88)
print('BRIDGE EV -> Equity -> Value/Share')
print('='*88)
print(out.bridge_table().to_string(index=False))

print()
print('='*88)
print('VEREDICTO FINAL (con deuda CORRECTA)')
print('='*88)
print(f'  Value per share (DCF):  ${out.value_per_share:>7.2f} MXN')
print(f'  Market price:           ${ass.market_price:>7.2f} MXN')
print(f'  Diferencia:             {out.upside_pct*100:>+7.2f}%')

# Comparacion con bug previo
print()
print('--- Comparacion vs bug previo ---')
print(f'  Antes (debt 5,696 mal):  $18.44 MXN  -> -10.9% (sobrevaluada moderada)')
print(f'  Ahora (debt 20,830 OK):  ${out.value_per_share:.2f} MXN  -> {out.upside_pct*100:+.1f}%')
print(f'  Impacto del bug fix: {(out.value_per_share - 18.44):+.2f} MXN/accion')
