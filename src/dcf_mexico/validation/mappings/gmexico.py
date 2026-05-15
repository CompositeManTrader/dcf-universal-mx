"""
Mapping GMEXICO Bloomberg "As Reported" -> XBRL parser fields.

Construido a partir de inspeccion de:
  data/bloomberg/Edos_gmexico_anuales.xlsx
    - Hoja 'Income - As Reported' (~163 filas)
    - Hoja 'Bal Sheet - As Reported' (~199 filas)
    - Hoja 'Cash Flow - As Reported' (~70 filas)

GMEXICO reporta en MILLONES de USD (no MXN como CUERVO). El XBRL CNBV
de GMEXICO también está en USD nativos (no en miles, ver nota
USE_ROUNDING_METADATA = False en parser).

VALIDACION FY 2024 (deep dive 2025-05):
  - Match total ~95% line by line vs Bloomberg
  - Revenue cuadra perfecto: $16,169 USD M ambas fuentes
  - LT Debt y ST Borrowings cuadran perfecto al peso
  - Total Assets, Total Equity cuadran ~0.2%

DIFERENCIAS CONOCIDAS (NO son bugs — reclasificaciones estandar):
  1. COGS: BB incluye D&A; CNBV lo separa. Diff ~$140M.
     EBIT y Net Income cuadran al final.
  2. Interest Expense: BB reporta NETO (gross - capitalized interest);
     CNBV reporta GROSS. Diff ~$145M en GMEXICO 2024.
  3. Goodwill vs Total Intangibles: BB junta los dos; CNBV separa.
     - BB "Total Intangible Assets - Net" = CNBV (Goodwill + Other Intang).

Notas de signo:
  - "Equity In Earnings of Affiliate": BB negativo cuando JV genera
    ganancia, CNBV positivo. sign_flip=-1.
  - "Interest Income" BB negativo (mostrado como reduccion), CNBV
    positivo. sign_flip=-1.
  - Capex/Dividends BB negativos (outflows), CNBV positivos. sign_flip=-1.
"""
from ..bloomberg_compare import LineMapping, BloombergMapping


# -----------------------------------------------------------------
# INCOME - As Reported
# -----------------------------------------------------------------
GMEXICO_INCOME_AR = [
    LineMapping(
        bloomberg_label="Total Revenue",
        parser_path="income.revenue",
        notes="Ingresos consolidados 12M (USD M)",
    ),
    LineMapping(
        bloomberg_label="Revenues",
        parser_path="income.revenue",
        notes="Alias alternativo de Revenue",
    ),
    LineMapping(
        bloomberg_label="Cost of Goods Sold",
        parser_path="income.cost_of_sales",
        notes="COGS — Bloomberg incluye D&A aqui; CNBV lo separa. "
              "Diff esperado ~$140M FY24. EBIT cuadra al final.",
    ),
    LineMapping(
        bloomberg_label="Gross Profit",
        parser_path="income.gross_profit",
        notes="Utilidad bruta = Revenue - COGS",
    ),
    LineMapping(
        bloomberg_label="Selling General and Administrative Expenses",
        parser_path="income.operating_expenses",
        notes="SG&A consolidado",
    ),
    LineMapping(
        bloomberg_label="Depreciation and Amortization",
        parser_path="informative.da_12m",
        notes="D&A 12M (de hoja 700003 del XBRL)",
    ),
    LineMapping(
        bloomberg_label="Operating Income",
        parser_path="income.ebit",
        notes="Utilidad de operacion (EBIT)",
    ),
    LineMapping(
        bloomberg_label="Interest Expense",
        parser_path="income.interest_expense",
        notes="Gastos financieros consolidados. BB reporta NETO "
              "(gross - capitalized interest); CNBV reporta GROSS. "
              "Diff esperado ~$145M FY24.",
    ),
    LineMapping(
        bloomberg_label="Interest Income",
        parser_path="income.interest_income",
        notes="Productos financieros (BB lo muestra negativo, CNBV positivo)",
        sign_flip=-1.0,
    ),
    LineMapping(
        bloomberg_label="Foreign Exchange",
        parser_path="income.fx_result",
        notes="Resultado cambiario",
    ),
    LineMapping(
        bloomberg_label="Equity In Earnings of Affiliate/Joint Ventures",
        parser_path="income.associates_result",
        sign_flip=-1.0,
        notes="BB negativo cuando JV es ganancia; CNBV positivo. sign_flip=-1.",
    ),
    LineMapping(
        bloomberg_label="Income Before Income Taxes",
        parser_path="income.pretax_income",
        notes="UAI",
    ),
    LineMapping(
        bloomberg_label="Income Tax Expense (Benefit)",
        parser_path="income.tax_expense",
        notes="Impuestos a la utilidad",
    ),
    LineMapping(
        bloomberg_label="Current Income Tax Expense (Benefit)",
        parser_path="informative.current_tax_acum",
        notes="ISR causado del periodo",
    ),
    LineMapping(
        bloomberg_label="Deferred Income Tax Expense (Benefit)",
        parser_path="informative.deferred_tax_acum",
        notes="ISR diferido del periodo",
    ),
    LineMapping(
        bloomberg_label="Profit After Taxation Before Minority",
        parser_path="income.net_income",
        notes="Utilidad neta total (antes de minoritario)",
    ),
    LineMapping(
        bloomberg_label="Net Income",
        parser_path="income.net_income_controlling",
        notes="NI atribuible a controladora",
    ),
    LineMapping(
        bloomberg_label="Minority/Non Controlling Interest",
        parser_path="income.net_income_minority",
        notes="NI atribuible a minoritarios",
    ),
    # EBITDA - IS: Bloomberg lo presenta como referencia. Nuestro parser
    # no tiene campo directo (EBIT + D&A). Se omite del mapping; el
    # cálculo se hace en _snapshot_metrics como derivado.
]


# -----------------------------------------------------------------
# BALANCE SHEET - As Reported
# -----------------------------------------------------------------
GMEXICO_BS_AR = [
    # ===== ACTIVOS CIRCULANTES =====
    LineMapping(
        bloomberg_label="Cash and Equivalents",
        parser_path="balance.cash",
        notes="Efectivo y equivalentes",
    ),
    LineMapping(
        bloomberg_label="Cash Equivalents And Marketable Securities",
        parser_path="balance.cash",
        notes="Cash + MktSec consolidado (mismo campo en CNBV)",
    ),
    LineMapping(
        bloomberg_label="Accounts Receivable - Trade",
        parser_path="balance.accounts_receivable_trade",
        notes="Clientes (trade only)",
    ),
    LineMapping(
        bloomberg_label="Accounts Receivable And Other Receivables",
        parser_path="balance.accounts_receivable",
        notes="Clientes + otras cuentas por cobrar",
    ),
    LineMapping(
        bloomberg_label="Inventories",
        parser_path="balance.inventories",
        notes="Inventarios circulantes",
    ),
    LineMapping(
        bloomberg_label="Other Current Assets",
        parser_path="balance.other_current_assets",
        notes="Otros activos circulantes",
    ),
    LineMapping(
        bloomberg_label="Total Current Assets",
        parser_path="balance.total_current_assets",
        notes="Total activos circulantes",
    ),
    # ===== ACTIVOS NO CIRCULANTES =====
    LineMapping(
        bloomberg_label="Property Plant & Equipment - Net",
        parser_path="balance.ppe",
        notes="PP&E neto (clave para minera, mining assets)",
    ),
    LineMapping(
        bloomberg_label="Goodwill",
        parser_path="balance.goodwill",
        notes="Credito mercantil — BB lo agrega tambien dentro de "
              "'Total Intangible Assets - Net' (que en CNBV es separado).",
    ),
    LineMapping(
        bloomberg_label="Other Intangible Assets",
        parser_path="balance.intangibles",
        notes="Intangibles distintos a goodwill (concesiones mineras, etc.)",
    ),
    LineMapping(
        bloomberg_label="Total Intangible Assets - Net",
        parser_path="balance.intangibles",
        notes="BB junta Goodwill + Other Intang. CNBV los separa: "
              "validar con goodwill + intangibles. Diff esperado ~$100M.",
    ),
    LineMapping(
        bloomberg_label="Investment In Affiliates/Joint Ventures",
        parser_path="balance.investments_in_associates",
        notes="Inversiones en asociadas/JV (no operacional)",
    ),
    LineMapping(
        bloomberg_label="Other Noncurrent Assets",
        parser_path="balance.other_non_current_assets",
        notes="Otros activos no circulantes",
    ),
    LineMapping(
        bloomberg_label="Total Non-Current Assets",
        parser_path="balance.total_non_current_assets",
        notes="Total activos no circulantes",
    ),
    LineMapping(
        bloomberg_label="Total Assets",
        parser_path="balance.total_assets",
        notes="Activos totales",
    ),
    # ===== PASIVOS CIRCULANTES =====
    LineMapping(
        bloomberg_label="Accounts Payable - Trade",
        parser_path="balance.accounts_payable_trade",
        notes="Proveedores trade",
    ),
    LineMapping(
        bloomberg_label="Trade Payable And Other Payables",
        parser_path="balance.accounts_payable",
        notes="Proveedores + otras cuentas por pagar",
    ),
    LineMapping(
        bloomberg_label="Short-Term Borrowings",
        parser_path="balance.short_term_debt",
        notes="Deuda financiera CP",
    ),
    LineMapping(
        bloomberg_label="Current Portion of Long-Term Debt",
        parser_path="balance.short_term_debt",
        notes="Porción corriente de LT debt (mismo campo CNBV)",
    ),
    LineMapping(
        bloomberg_label="Other Current Liabilities",
        parser_path="balance.other_current_liabilities",
        notes="Otros pasivos circulantes",
    ),
    LineMapping(
        bloomberg_label="Total Current Liabilities",
        parser_path="balance.total_current_liabilities",
        notes="Total pasivos CP",
    ),
    # ===== PASIVOS NO CIRCULANTES =====
    LineMapping(
        bloomberg_label="Long Term Debt",
        parser_path="balance.long_term_debt",
        notes="Deuda financiera LP",
    ),
    LineMapping(
        bloomberg_label="Deferred Income Taxes (Liabilities)",
        parser_path="balance.deferred_tax_liabilities",
        notes="ISR diferido pasivo",
    ),
    LineMapping(
        bloomberg_label="Pension/Postretirement Liabilities",
        parser_path="balance.employee_benefits_lt",
        notes="Beneficios al retiro (provision LP)",
    ),
    LineMapping(
        bloomberg_label="Other Noncurrent Liabilities",
        parser_path="balance.other_non_current_liabilities",
        notes="Otros pasivos LP",
    ),
    LineMapping(
        bloomberg_label="Total Noncurrent Liabilities",
        parser_path="balance.total_non_current_liabilities",
        notes="Total pasivos LP",
    ),
    LineMapping(
        bloomberg_label="Total Liabilities",
        parser_path="balance.total_liabilities",
        notes="Total pasivos",
    ),
    # ===== CAPITAL =====
    LineMapping(
        bloomberg_label="Common Stock",
        parser_path="balance.common_stock",
        notes="Capital social",
    ),
    LineMapping(
        bloomberg_label="Additional Paid In Capital",
        parser_path="balance.additional_paid_in_capital",
        notes="Prima en emision",
    ),
    LineMapping(
        bloomberg_label="Retained Earnings (Accumulated Deficit)",
        parser_path="balance.retained_earnings",
        notes="Utilidades acumuladas",
    ),
    LineMapping(
        bloomberg_label="Other Equity",
        parser_path="balance.other_equity_reserves",
        notes="Otros componentes del capital (ORI acumulado)",
    ),
    LineMapping(
        bloomberg_label="Total Shareholders Equity Excluding Minority",
        parser_path="balance.equity_controlling",
        notes="Capital controladora",
    ),
    LineMapping(
        bloomberg_label="Total Shareholders Equity",
        parser_path="balance.total_equity",
        notes="Capital total (incluye minoritarios)",
    ),
    LineMapping(
        bloomberg_label="Minority/Non Controlling Int (Stckhldrs Eqty)",
        parser_path="balance.minority_interest",
        notes="Interes minoritario",
    ),
    LineMapping(
        bloomberg_label="Total Liabilities and Shareholders Equity",
        parser_path="balance.total_assets",
        notes="Check: A = L + E",
    ),
    LineMapping(
        bloomberg_label="Shares Outstanding",
        parser_path="informative.shares_outstanding",
        notes="Acciones en circulación (en absoluto, no millones)",
    ),
]


# -----------------------------------------------------------------
# CASH FLOW - As Reported
# -----------------------------------------------------------------
GMEXICO_CF_AR = [
    LineMapping(
        bloomberg_label="Net Income - CF",
        parser_path="income.net_income",
        notes="NI total (point of departure del CF)",
    ),
    LineMapping(
        bloomberg_label="Profit Before Taxation And Minority Interest",
        parser_path="income.pretax_income",
        notes="UAI (start del CF indirecto en algunas emisoras)",
    ),
    LineMapping(
        bloomberg_label="Depreciation and Amortization",
        parser_path="cashflow.da_in_cf",
        notes="D&A en el CF (puede diferir de info.da_12m)",
    ),
    LineMapping(
        bloomberg_label="Tax Paid",
        parser_path="cashflow.taxes_paid_cfo",
        notes="Impuestos pagados (efectivo)",
    ),
    LineMapping(
        bloomberg_label="Interest Paid",
        parser_path="cashflow.interest_paid_cfo",
        notes="Intereses pagados (CFO)",
    ),
    LineMapping(
        bloomberg_label="Total Cash Flows From Operations",
        parser_path="cashflow.cfo",
        notes="CFO total acumulado 12M",
    ),
    LineMapping(
        bloomberg_label="Capital Expenditures",
        parser_path="cashflow.capex_ppe",
        sign_flip=-1.0,
        notes="CapEx PPE (BB negativo = outflow, CNBV positivo)",
    ),
    LineMapping(
        bloomberg_label="Disposal of Fixed Assets",
        parser_path="cashflow.sales_of_ppe",
        notes="Venta de PP&E (positivo)",
    ),
    LineMapping(
        bloomberg_label="Acquisition of Business",
        parser_path="cashflow.cash_for_obtain_control",
        sign_flip=-1.0,
        notes="Adquisiciones de subsidiarias (BB negativo = outflow)",
    ),
    LineMapping(
        bloomberg_label="Total Cash Flows From Investing",
        parser_path="cashflow.cfi",
        notes="CFI total acumulado",
    ),
    LineMapping(
        bloomberg_label="Dividends Paid",
        parser_path="cashflow.dividends_paid",
        sign_flip=-1.0,
        notes="Dividendos pagados (BB negativo, CNBV positivo)",
    ),
]


GMEXICO_FULL = BloombergMapping(
    ticker="GMEXICO",
    income_ar=GMEXICO_INCOME_AR,
    bs_ar=GMEXICO_BS_AR,
    cf_ar=GMEXICO_CF_AR,
)
