"""
Mapping AC (Arca Continental) Bloomberg -> XBRL parser fields.

Construido a partir de inspeccion de:
  FA1_53ov03jw.xlsx (anual: FY 1999 - FY 2025)
  FA1_mknymiy4.xlsx (trimestral: Q4 2018 - presente)
    - Hoja 'Income - GAAP' (~50 filas)
    - Hoja 'Bal Sheet - Standardized' (~100 filas)
    - Hoja 'Cash Flow - Standardized' (~70 filas)

VALIDACION FY 2025 (deep dive 2025-05):
  - MATCH PERFECTO 28/28 lineas Income GAAP (diff = 0.00)
  - Revenue, EBIT, Net Income, EBITDA, Tax breakdown — todos exactos
  - Reportada en MXN. Embotelladora Coca-Cola con sub-lines D&A en OpEx
    (no en COGS como mineras).

Notas estructurales AC (vs CUERVO/GMEXICO):
  - D&A va en OpEx (no en COGS). FY25: 10,208 MDP en OpEx.
  - CNBV `ga_expenses` INCLUYE D&A. BB_G&A = ga_cnbv - da_value.
  - Other Op Income/Expense BB = NETO de CNBV (puede ir a Income o Expense).
  - Sub-line "Selling & Marketing" explicita ($65,809 vs G&A $1,521).
  - SIN bloque "Pretax Adjusted" + Abnormal Losses (igual que GMEXICO).

Notas de signo:
  - "Equity in Earnings of Affiliates": BB negativo cuando JV gana, CNBV
    positivo. sign_flip=-1 (ya en mapping de Income).
  - FX: BB FX Loss = fx_loss_acum - fx_gain_acum (neto, signo loss-positive).
  - Capex BB negativo (outflow), CNBV positivo. sign_flip=-1 en CF.
  - Dividends BB negativos, CNBV positivos. sign_flip=-1.
"""
from ..bloomberg_compare import LineMapping, BloombergMapping


# -----------------------------------------------------------------
# INCOME - GAAP
# -----------------------------------------------------------------
AC_INCOME_AR = [
    LineMapping(
        bloomberg_label="Revenue",
        parser_path="income.revenue",
        notes="Ingresos consolidados 12M (MDP)",
    ),
    LineMapping(
        bloomberg_label="    + Sales & Services Revenue",
        parser_path="income.revenue",
        notes="= Revenue (no desglose adicional)",
    ),
    LineMapping(
        bloomberg_label="  - Cost of Revenue",
        parser_path="income.cost_of_sales",
        notes="COGS consolidado (sin D&A para AC; D&A va en OpEx)",
    ),
    LineMapping(
        bloomberg_label="    + Cost of Goods & Services",
        parser_path="income.cost_of_sales",
        notes="= Cost of Revenue (sin D&A)",
    ),
    LineMapping(
        bloomberg_label="Gross Profit",
        parser_path="income.gross_profit",
        notes="Revenue - COGS",
    ),
    LineMapping(
        bloomberg_label="    + Selling & Marketing",
        parser_path="income.selling_expenses",
        notes="Gastos de venta (CNBV)",
    ),
    LineMapping(
        bloomberg_label="Operating Income (Loss)",
        parser_path="income.ebit",
        notes="Utilidad de operacion",
    ),
    LineMapping(
        bloomberg_label="    + Interest Expense",
        parser_path="informative.interest_devengado_acum",
        notes="Intereses devengados (hoja 800200) — BB usa este, no inc.interest_expense",
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
        notes="BB negativo = ganancia; CNBV positivo. sign_flip=-1.",
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
        notes="NI total antes de minoritarios",
    ),
    LineMapping(
        bloomberg_label="  - Minority Interest",
        parser_path="income.net_income_minority",
        notes="NI minoritarios",
    ),
    LineMapping(
        bloomberg_label="Net Income, GAAP",
        parser_path="income.net_income_controlling",
        notes="NI atribuible a controladora",
    ),
    LineMapping(
        bloomberg_label="Net Income Avail to Common, GAAP",
        parser_path="income.net_income_controlling",
        notes="= Net Income GAAP (no preferred dividends en AC)",
    ),
]


# -----------------------------------------------------------------
# BAL SHEET - Standardized (subset clave)
# -----------------------------------------------------------------
AC_BS_AR = [
    LineMapping(
        bloomberg_label="    + Cash & Cash Equivalents",
        parser_path="balance.cash",
        notes="Efectivo y equivalentes",
    ),
    LineMapping(
        bloomberg_label="    + Accounts Receivable, Net",
        parser_path="balance.accounts_receivable",
        notes="Clientes (incluye trade y otras)",
    ),
    LineMapping(
        bloomberg_label="    + Inventories",
        parser_path="balance.inventories",
        notes="Inventarios circulantes (suma de raw + WIP + finished + other)",
    ),
    LineMapping(
        bloomberg_label="  Total Current Assets",
        parser_path="balance.total_current_assets",
        notes="Total activos circulantes",
    ),
    LineMapping(
        bloomberg_label="    + Property, Plant & Equip, Net",
        parser_path="balance.ppe",
        notes="PP&E neto (incluye ROU bajo IFRS-16)",
    ),
    LineMapping(
        bloomberg_label="      + Goodwill",
        parser_path="balance.goodwill",
        notes="Credito mercantil",
    ),
    LineMapping(
        bloomberg_label="      + Other Intangible Assets",
        parser_path="balance.intangibles",
        notes="Intangibles distintos a goodwill (marcas, contratos)",
    ),
    LineMapping(
        bloomberg_label="      + Investments in Affiliates",
        parser_path="balance.investments_in_associates",
        notes="Inversiones en asociadas (Bepensa, etc.)",
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
        notes="Pasivos por arrendamientos CP (IFRS-16)",
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
        notes="Pasivos por arrendamientos LP (IFRS-16)",
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
        notes="Prima en emision",
    ),
    LineMapping(
        bloomberg_label="    + Retained Earnings",
        parser_path="balance.retained_earnings",
        notes="Utilidades acumuladas",
    ),
    LineMapping(
        bloomberg_label="    + Other Equity",
        parser_path="balance.other_equity_reserves",
        notes="ORI acumulado y otros componentes",
    ),
    LineMapping(
        bloomberg_label="  Equity Before Minority Interest",
        parser_path="balance.equity_controlling",
        notes="Capital controladora",
    ),
    LineMapping(
        bloomberg_label="    + Minority/Non Controlling Interest",
        parser_path="balance.minority_interest",
        notes="Interes minoritario (KOF, etc.)",
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
        notes="Acciones en circulacion (en absoluto, no millones)",
    ),
]


# -----------------------------------------------------------------
# CASH FLOW - Standardized (subset clave)
# -----------------------------------------------------------------
AC_CF_AR = [
    LineMapping(
        bloomberg_label="    + Net Income",
        parser_path="income.net_income",
        notes="NI total (incluye minoritarios) — punto de partida del CF",
    ),
    LineMapping(
        bloomberg_label="    + Depreciation & Amortization",
        parser_path="cashflow.da_in_cf",
        notes="D&A en CF (puede diferir de informative.da_12m)",
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
        notes="CapEx PP&E (BB negativo = outflow, CNBV positivo)",
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
        bloomberg_label="    + Net Cash From Acq & Div",
        parser_path="cashflow.cash_for_obtain_control",
        sign_flip=-1.0,
        notes="Adquisiciones de subsidiarias (BB negativo)",
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


AC_FULL = BloombergMapping(
    ticker="AC",
    income_ar=AC_INCOME_AR,
    bs_ar=AC_BS_AR,
    cf_ar=AC_CF_AR,
)
