"""
Mapping FEMSA (Fomento Economico Mexicano) Bloomberg -> XBRL parser fields.

Construido a partir de inspeccion de:
  FA1_dbjmy5g3.xlsx (anual: FY 1991 - FY 2025)
  FA1_wjkhu1ff.xlsx (trimestral: Q1 1996 - presente)
    - Hoja 'Income - GAAP' (~55 filas)
    - Hoja 'Bal Sheet - Standardized' (~105 filas)
    - Hoja 'Cash Flow - Standardized' (~70 filas)

VALIDACION FY 2025 (deep dive 2026-05):
  - MATCH 26/27 lineas Income GAAP (todas <1% diff excepto EBITDA)
  - Revenue, COGS, Gross Profit, SGA breakdown completo, EBIT, Net Interest,
    FX Loss, Affiliates, Tax breakdown, NI — exactos al peso
  - EBITDA diff +6% por D&A ROU/IFRS-16 que BB excluye

Estructura FEMSA (holding diversificado):
  - Proximity Americas (OXXO), Proximity Europe (Valora)
  - Coca-Cola FEMSA (KOF consolidada)
  - Salud, Combustibles, Digital@FEMSA

Diferencias vs AC:
  - SI tiene "Other Revenue" con valor real ($6,564 FY25)
  - NO muestra "Depreciation & Amortization" sub-line en OpEx (BB no la separa)
  - G&A_CNBV NO incluye D&A (= BB G&A directo, no restar D&A)
  - Other Op Income/Expense separados (no calcular neto)
  - Tax breakdown con "Tax Allowance/Credit" extra (~$96)
  - Discontinued Operations significativos (~$-1,574 FY25)
  - num_workers (268,605) >> num_employees (97,021) — total 365,626

Notas de signo:
  - Affiliates BB positivo = loss, CNBV positivo = ganancia. sign_flip=-1.
  - FX BB positivo = loss neto = fx_loss - fx_gain (hoja 800200).
  - Capex/Dividends BB negativos = outflow, CNBV positivos. sign_flip=-1.
"""
from ..bloomberg_compare import LineMapping, BloombergMapping


# -----------------------------------------------------------------
# INCOME - GAAP
# -----------------------------------------------------------------
FEMSA_INCOME_AR = [
    LineMapping(
        bloomberg_label="Revenue",
        parser_path="income.revenue",
        notes="Ingresos consolidados 12M (MDP)",
    ),
    LineMapping(
        bloomberg_label="  - Cost of Revenue",
        parser_path="income.cost_of_sales",
        notes="COGS consolidado",
    ),
    LineMapping(
        bloomberg_label="    + Cost of Goods & Services",
        parser_path="income.cost_of_sales",
        notes="= Cost of Revenue",
    ),
    LineMapping(
        bloomberg_label="Gross Profit",
        parser_path="income.gross_profit",
        notes="Revenue - COGS",
    ),
    LineMapping(
        bloomberg_label="  + Other Operating Income",
        parser_path="income.other_operating_income",
        notes="FEMSA muestra separado (no neto como AC)",
    ),
    LineMapping(
        bloomberg_label="    + Selling & Marketing",
        parser_path="income.selling_expenses",
        notes="Gastos de venta",
    ),
    LineMapping(
        bloomberg_label="    + General & Administrative",
        parser_path="income.ga_expenses",
        notes="Gastos de admin (FEMSA: ga_cnbv NO incluye D&A)",
    ),
    LineMapping(
        bloomberg_label="    + Other Operating Expense",
        parser_path="income.other_operating_expense",
        notes="Otros gastos op (separado)",
    ),
    LineMapping(
        bloomberg_label="Operating Income (Loss)",
        parser_path="income.ebit",
        notes="EBIT",
    ),
    LineMapping(
        bloomberg_label="    + Interest Expense",
        parser_path="informative.interest_devengado_acum",
        notes="Intereses devengados (hoja 800200)",
    ),
    LineMapping(
        bloomberg_label="    - Interest Income",
        parser_path="informative.interest_earned_acum",
        notes="Intereses ganados (hoja 800200)",
    ),
    LineMapping(
        bloomberg_label="    + (Income) Loss from Affiliates",
        parser_path="income.associates_result",
        sign_flip=-1.0,
        notes="BB positivo = loss; CNBV positivo = ganancia. sign_flip=-1.",
    ),
    LineMapping(
        bloomberg_label="Pretax Income",
        parser_path="income.pretax_income",
        notes="UAI",
    ),
    LineMapping(
        bloomberg_label="  - Income Tax Expense (Benefit)",
        parser_path="income.tax_expense",
        notes="Impuestos a la utilidad total",
    ),
    LineMapping(
        bloomberg_label="    + Current Income Tax",
        parser_path="informative.current_tax_acum",
        notes="ISR causado (hoja 800200)",
    ),
    LineMapping(
        bloomberg_label="    + Deferred Income Tax",
        parser_path="informative.deferred_tax_acum",
        notes="ISR diferido (hoja 800200)",
    ),
    LineMapping(
        bloomberg_label="Income (Loss) Incl. MI",
        parser_path="income.net_income",
        notes="NI total (CNBV incluye discontinued; BB lo separa pero suma igual)",
    ),
    LineMapping(
        bloomberg_label="  - Minority Interest",
        parser_path="income.net_income_minority",
        notes="NI minoritarios (KOF principal)",
    ),
    LineMapping(
        bloomberg_label="Net Income, GAAP",
        parser_path="income.net_income_controlling",
        notes="NI controladora",
    ),
    LineMapping(
        bloomberg_label="Net Income Avail to Common, GAAP",
        parser_path="income.net_income_controlling",
        notes="= NI GAAP",
    ),
]


# -----------------------------------------------------------------
# BAL SHEET - Standardized (subset clave)
# -----------------------------------------------------------------
FEMSA_BS_AR = [
    LineMapping(
        bloomberg_label="    + Cash & Cash Equivalents",
        parser_path="balance.cash",
        notes="Efectivo y equivalentes",
    ),
    LineMapping(
        bloomberg_label="    + Accounts Receivable, Net",
        parser_path="balance.accounts_receivable",
        notes="Clientes",
    ),
    LineMapping(
        bloomberg_label="    + Inventories",
        parser_path="balance.inventories",
        notes="Inventarios circulantes",
    ),
    LineMapping(
        bloomberg_label="  Total Current Assets",
        parser_path="balance.total_current_assets",
        notes="Total activos circulantes",
    ),
    LineMapping(
        bloomberg_label="    + Property, Plant & Equip, Net",
        parser_path="balance.ppe",
        notes="PP&E neto (incluye ROU IFRS-16; OXXO tiendas)",
    ),
    LineMapping(
        bloomberg_label="      + Goodwill",
        parser_path="balance.goodwill",
        notes="Credito mercantil (adquisiciones Valora, salud, etc.)",
    ),
    LineMapping(
        bloomberg_label="      + Other Intangible Assets",
        parser_path="balance.intangibles",
        notes="Intangibles (marcas OXXO, franquicia Coca-Cola)",
    ),
    LineMapping(
        bloomberg_label="      + Investments in Affiliates",
        parser_path="balance.investments_in_associates",
        notes="Inversiones en asociadas",
    ),
    LineMapping(
        bloomberg_label="  Total Noncurrent Assets",
        parser_path="balance.total_non_current_assets",
        notes="Total activos no circulantes",
    ),
    LineMapping(
        bloomberg_label="  Total Assets",
        parser_path="balance.total_assets",
        notes="Activos totales",
    ),
    LineMapping(
        bloomberg_label="      + Accounts Payable",
        parser_path="balance.accounts_payable_trade",
        notes="Proveedores trade",
    ),
    LineMapping(
        bloomberg_label="      + ST Borrowings",
        parser_path="balance.short_term_debt",
        notes="Deuda financiera CP",
    ),
    LineMapping(
        bloomberg_label="      + ST Lease Liabilities",
        parser_path="balance.short_term_lease",
        notes="Arrendamientos CP (IFRS-16; OXXO tiendas)",
    ),
    LineMapping(
        bloomberg_label="  Total Current Liabilities",
        parser_path="balance.total_current_liabilities",
        notes="Total pasivos CP",
    ),
    LineMapping(
        bloomberg_label="      + LT Borrowings",
        parser_path="balance.long_term_debt",
        notes="Deuda financiera LP",
    ),
    LineMapping(
        bloomberg_label="      + LT Lease Liabilities",
        parser_path="balance.long_term_lease",
        notes="Arrendamientos LP (significant para retail)",
    ),
    LineMapping(
        bloomberg_label="      + Deferred Tax Liabilities",
        parser_path="balance.deferred_tax_liabilities",
        notes="ISR diferido pasivo",
    ),
    LineMapping(
        bloomberg_label="  Total Noncurrent Liabilities",
        parser_path="balance.total_non_current_liabilities",
        notes="Total pasivos LP",
    ),
    LineMapping(
        bloomberg_label="  Total Liabilities",
        parser_path="balance.total_liabilities",
        notes="Total pasivos",
    ),
    LineMapping(
        bloomberg_label="      + Common Stock",
        parser_path="balance.common_stock",
        notes="Capital social",
    ),
    LineMapping(
        bloomberg_label="      + Additional Paid in Capital",
        parser_path="balance.additional_paid_in_capital",
        notes="Prima en emision (puede ser negativa por reducciones)",
    ),
    LineMapping(
        bloomberg_label="    + Retained Earnings",
        parser_path="balance.retained_earnings",
        notes="Utilidades acumuladas",
    ),
    LineMapping(
        bloomberg_label="    + Other Equity",
        parser_path="balance.other_equity_reserves",
        notes="ORI acumulado",
    ),
    LineMapping(
        bloomberg_label="  Equity Before Minority Interest",
        parser_path="balance.equity_controlling",
        notes="Capital controladora",
    ),
    LineMapping(
        bloomberg_label="    + Minority/Non Controlling Interest",
        parser_path="balance.minority_interest",
        notes="Minority KOF principal",
    ),
    LineMapping(
        bloomberg_label="  Total Equity",
        parser_path="balance.total_equity",
        notes="Capital total",
    ),
    LineMapping(
        bloomberg_label="  Total Liabilities & Equity",
        parser_path="balance.total_assets",
        notes="Check: A = L + E",
    ),
    LineMapping(
        bloomberg_label="Shares Outstanding",
        parser_path="informative.shares_outstanding",
        notes="Acciones en circulacion (en absoluto)",
    ),
]


# -----------------------------------------------------------------
# CASH FLOW - Standardized (subset clave)
# -----------------------------------------------------------------
FEMSA_CF_AR = [
    LineMapping(
        bloomberg_label="    + Net Income",
        parser_path="income.net_income",
        notes="NI total (start del CF indirecto)",
    ),
    LineMapping(
        bloomberg_label="    + Depreciation & Amortization",
        parser_path="cashflow.da_in_cf",
        notes="D&A en CF (FY25 BB: 44,138; nuestro: similar)",
    ),
    LineMapping(
        bloomberg_label="  Cash from Operating Activities",
        parser_path="cashflow.cfo",
        notes="CFO total acumulado 12M",
    ),
    LineMapping(
        bloomberg_label="      + Acq of Fixed Prod Assets",
        parser_path="cashflow.capex_ppe",
        sign_flip=-1.0,
        notes="CapEx PP&E (BB negativo = outflow)",
    ),
    LineMapping(
        bloomberg_label="      + Acq of Intangible Assets",
        parser_path="cashflow.capex_intangibles",
        sign_flip=-1.0,
        notes="CapEx intangibles",
    ),
    LineMapping(
        bloomberg_label="      + Disp of Fixed Prod Assets",
        parser_path="cashflow.sales_of_ppe",
        notes="Venta de PP&E",
    ),
    LineMapping(
        bloomberg_label="  Cash from Investing Activities",
        parser_path="cashflow.cfi",
        notes="CFI total",
    ),
    LineMapping(
        bloomberg_label="    + Dividends Paid",
        parser_path="cashflow.dividends_paid",
        sign_flip=-1.0,
        notes="Dividendos pagados (BB negativo)",
    ),
    LineMapping(
        bloomberg_label="  Cash from Financing Activities",
        parser_path="cashflow.cff",
        notes="CFF total",
    ),
    LineMapping(
        bloomberg_label="  Net Changes in Cash",
        parser_path="cashflow.net_change_cash",
        notes="Cambio neto en efectivo del periodo",
    ),
]


FEMSA_FULL = BloombergMapping(
    ticker="FEMSA",
    income_ar=FEMSA_INCOME_AR,
    bs_ar=FEMSA_BS_AR,
    cf_ar=FEMSA_CF_AR,
)
