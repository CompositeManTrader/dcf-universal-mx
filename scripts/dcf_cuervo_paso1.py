"""PASO 1: Valuacion CUERVO con DEFAULTS DAMODARAN-style (MX-adapted)."""
import warnings; warnings.filterwarnings('ignore')
import sys; sys.path.insert(0, '.')
from src.dcf_mexico.valuation.dcf_fcff import DCFAssumptions, CompanyBase, project_company
from src.dcf_mexico.valuation.wacc import RF_MX_DEFAULT, ERP_MX_DEFAULT, MARGINAL_TAX_MX
import pandas as pd
pd.set_option('display.width', 250)

print('='*88)
print('PASO 1: Valuacion CUERVO con DEFAULTS DAMODARAN-style (Mexico-adapted)')
print('='*88)

# ============================================================
# A) BASE: actuals CUERVO FY 2025 (de los XBRL parseados)
# ============================================================
print('\n--- BASE FINANCIALS (de los XBRL FY 2025) ---')
base = CompanyBase(
    ticker='CUERVO',
    revenue=43087.4,
    ebit=9664.2,
    interest_expense=1141.6,
    cash=11112.9,
    financial_debt=4824.8 + 870.9,      # debt + lease
    minority_interest=80.0,
    non_operating_assets=0.0,
    shares_outstanding=3591.176e6,
    effective_tax_rate=0.27,
    equity_book=70213.0,
    invested_capital=63924.0,
)
print(f'  Revenue:         {base.revenue:>10,.1f} MDP')
print(f'  EBIT:            {base.ebit:>10,.1f} MDP  (margin {base.ebit/base.revenue*100:.1f}%)')
print(f'  Cash:            {base.cash:>10,.1f} MDP')
print(f'  Total Debt:      {base.financial_debt:>10,.1f} MDP  (incl leases)')
print(f'  Net Debt:        {base.financial_debt - base.cash:>10,.1f} MDP  (NEGATIVO! cash > debt)')
print(f'  Minority:        {base.minority_interest:>10,.1f} MDP')
print(f'  Equity Book:     {base.equity_book:>10,.1f} MDP')
print(f'  Shares:          {base.shares_outstanding/1e6:>10,.2f} M')
print(f'  Effective Tax:   {base.effective_tax_rate*100:>10.1f}%')

# ============================================================
# B) ASSUMPTIONS Damodaran-style
# ============================================================
print('\n--- ASSUMPTIONS DAMODARAN-STYLE ---')
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
    unlevered_beta=0.65,
    terminal_wacc_override=None,
    market_price=20.70,
    forecast_years=10,
    high_growth_years=5,
    override_terminal_roic=False,
    probability_of_failure=0.0,
)
print(f'  Revenue growth Y1:   {ass.revenue_growth_y1*100:>5.1f}%   (Damodaran mature default)')
print(f'  Revenue growth Y2-5: {ass.revenue_growth_high*100:>5.1f}%')
print(f'  Terminal growth:     {ass.terminal_growth*100:>5.1f}%   (cap inflacion MX)')
print(f'  Op margin Y1:        {ass.op_margin_y1*100:>5.2f}%   (= current actual)')
print(f'  Target op margin:    {ass.target_op_margin*100:>5.2f}%   (mantener current, sin moat)')
print(f'  Year of convergence: {ass.year_of_margin_convergence}')
print(f'  Sales-to-Capital:    {ass.sales_to_capital:>5.2f}x   (Beverage Alcoholic Damodaran)')
print(f'  Effective tax:       {ass.effective_tax_base*100:>5.1f}%   -> marginal {ass.marginal_tax_terminal*100:.0f}%')
print(f'  Risk-free MX:        {ass.risk_free*100:>5.2f}%   (M-Bono 10Y)')
print(f'  ERP MX:              {ass.erp*100:>5.2f}%   (US 5% + CRP MX 1.80%)')
print(f'  Beta unlevered:      {ass.unlevered_beta:>5.2f}    (Beverage Alcoholic Damodaran)')

# ============================================================
# C) RUN DCF
# ============================================================
out = project_company(base, ass)

print()
print('='*88)
print('PROYECCION 10 ANOS')
print('='*88)
print(out.projection_table().to_string(index=False))

print()
print('='*88)
print('IMPLIED VARIABLES (S2C, IC, ROIC vs WACC)')
print('='*88)
print(out.implied_table().to_string(index=False))

print()
print('='*88)
print('TERMINAL VALUE (Gordon)')
print('='*88)
print(f'  FCFF Y10:                      {out.fcff[-1]:>10,.1f} MDP')
print(f'  FCFF Y11 (terminal):           {out.terminal_fcff:>10,.1f} MDP')
print(f'  WACC terminal:                 {out.terminal_wacc*100:>10.2f}%')
print(f'  Terminal growth:               {ass.terminal_growth*100:>10.2f}%')
print(f'  Terminal ROIC (= WACC):        {out.terminal_roic*100:>10.2f}%')
print(f'  Terminal Reinv Rate (g/ROIC):  {out.terminal_reinv_rate*100:>10.2f}%')
print(f'  Terminal Value (TV):           {out.terminal_value:>10,.1f} MDP')
print(f'  Discount Factor Y10:           {out.discount_factor[-1]:>10.4f}')
print(f'  PV(Terminal Value):            {out.pv_terminal:>10,.1f} MDP')

print()
print('='*88)
print('BRIDGE: Enterprise Value -> Equity -> Value/Share')
print('='*88)
print(out.bridge_table().to_string(index=False))

print()
print('='*88)
print('WACC DETAIL')
print('='*88)
w = out.wacc_result
print(f'  Beta unlevered:           {w.unlevered_beta:>8.3f}')
print(f'  D/E (target):             {w.debt_to_equity:>8.3f}')
print(f'  Beta levered:             {w.levered_beta:>8.3f}')
print(f'  Cost of Equity (Re):      {w.cost_equity*100:>8.2f}%')
print(f'  Interest Coverage:        {w.interest_coverage:>8.2f}x')
print(f'  Synthetic Rating:         {w.rating:>8s}')
print(f'  Default Spread:           {w.default_spread*100:>8.2f}%')
print(f'  Pretax Cost of Debt:      {w.pretax_cost_debt*100:>8.2f}%')
print(f'  Aftertax Cost of Debt:    {w.aftertax_cost_debt*100:>8.2f}%')
print(f'  Weight Equity:            {w.weight_equity*100:>8.1f}%')
print(f'  Weight Debt:              {w.weight_debt*100:>8.1f}%')
print(f'  WACC:                     {w.wacc*100:>8.2f}%')

# ============================================================
# D) VEREDICTO + CONTRIBUCION TV vs Explicit
# ============================================================
print()
print('='*88)
print('CONTRIBUCION DEL TERMINAL VALUE vs EXPLICIT FORECAST')
print('='*88)
ev = out.enterprise_value
pv_explicit = out.sum_pv_fcff
pv_tv = out.pv_terminal
print(f'  PV Explicit (Y1-10):  {pv_explicit:>10,.1f} MDP   ({pv_explicit/ev*100:>5.1f}% del EV)')
print(f'  PV Terminal:          {pv_tv:>10,.1f} MDP   ({pv_tv/ev*100:>5.1f}% del EV)')
print(f'  EV total:             {ev:>10,.1f} MDP   (100.0%)')
if pv_tv/ev > 0.70:
    print(f'  -> Terminal Value es {pv_tv/ev*100:.0f}% del valor: ALTAMENTE sensible a g_terminal y WACC_terminal')

print()
print('='*88)
print('VEREDICTO FINAL')
print('='*88)
print(f'  Value per share (DCF):  ${out.value_per_share:>7.2f} MXN')
print(f'  Market price:           ${ass.market_price:>7.2f} MXN')
print(f'  Diferencia:             {out.upside_pct*100:>+7.2f}%')
print()
if out.upside_pct > 0.20:
    veredict = 'COMPRA  -- DCF muy por arriba del precio'
elif out.upside_pct > 0.05:
    veredict = 'COMPRA MODERADA'
elif out.upside_pct > -0.05:
    veredict = 'FAIR VALUE -- modelo y mercado coinciden'
elif out.upside_pct > -0.20:
    veredict = 'SOBREVALORADA MODERADA'
else:
    veredict = 'SOBREVALORADA -- DCF muy por debajo del precio'
print(f'  Veredicto: {veredict}')
