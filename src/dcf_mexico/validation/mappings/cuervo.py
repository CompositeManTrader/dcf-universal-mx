"""
Mapping CUERVO Bloomberg "As Reported" -> XBRL parser fields.

Construido a partir de inspeccion de:
  data/bloomberg/Edos_cuervo_anuales.xlsx
    - Hoja 'Income - As Reported' (110 filas)
    - Hoja 'Bal Sheet - As Reported' (157 filas)
    - Hoja 'Cash Flow - As Reported' (78 filas)

Cada LineMapping vincula un label EXACTO de Bloomberg con la ruta
al campo en mi ParseResult del parser XBRL CNBV.

Notas de signo:
  - Bloomberg muestra "Equity In Earnings of Affiliate" como NEGATIVO cuando
    el JV genera ganancia para CUERVO. CNBV lo muestra POSITIVO. sign_flip=-1.
  - "Interest Income" Bloomberg negativo (-393 = ingreso). CNBV positivo.
  - Capex en CF Bloomberg negativo, en CNBV positivo (label trae prefijo "-").
"""
from ..bloomberg_compare import LineMapping, BloombergMapping


# -----------------------------------------------------------------
# INCOME - As Reported
# -----------------------------------------------------------------
CUERVO_INCOME_AR = [
    LineMapping(
        bloomberg_label="Total Revenue",
        parser_path="income.revenue",
        notes="Ingresos consolidados 12M",
    ),
    LineMapping(
        bloomberg_label="Cost of Goods Sold",
        parser_path="income.cost_of_sales",
        notes="COGS",
    ),
    LineMapping(
        bloomberg_label="Gross Profit",
        parser_path="income.gross_profit",
        notes="Utilidad bruta = Revenue - COGS",
    ),
    LineMapping(
        bloomberg_label="Operating Income",
        parser_path="income.ebit",
        notes="Utilidad de operacion (EBIT)",
    ),
    LineMapping(
        bloomberg_label="Interest Expense",
        parser_path="income.interest_expense",
        notes="Gastos financieros",
    ),
    LineMapping(
        bloomberg_label="Income Tax Expense (Benefit)",
        parser_path="income.tax_expense",
        notes="Impuestos a la utilidad",
    ),
    LineMapping(
        bloomberg_label="Income Before Income Taxes",
        parser_path="income.pretax_income",
        notes="UAI",
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
    LineMapping(
        bloomberg_label="Equity In Earnings of Affiliate/Joint Ventures",
        parser_path="income.associates_result",
        sign_flip=-1.0,
        notes="BB lo muestra negativo cuando JV es ganancia; CNBV positivo. sign_flip=-1.",
    ),
    LineMapping(
        bloomberg_label="Depreciation and Amortization",
        parser_path="informative.da_12m",
        notes="D&A 12M (de hoja 700003 del XBRL)",
    ),
]


# -----------------------------------------------------------------
# BALANCE SHEET - As Reported
# -----------------------------------------------------------------
CUERVO_BS_AR = [
    LineMapping(
        bloomberg_label="Cash and Equivalents",
        parser_path="balance.cash",
        notes="Efectivo y equivalentes",
    ),
    LineMapping(
        bloomberg_label="Inventories",
        parser_path="balance.inventories",
        notes="Inventarios circulantes",
    ),
    LineMapping(
        bloomberg_label="Accounts Receivable And Other Receivables",
        parser_path="balance.accounts_receivable",
        notes="Clientes y otras cuentas por cobrar",
    ),
    LineMapping(
        bloomberg_label="Total Current Assets",
        parser_path="balance.total_current_assets",
        notes="Total activos circulantes",
    ),
    LineMapping(
        bloomberg_label="Property Plant & Equipment - Net",
        parser_path="balance.ppe",
        notes="PP&E neto",
    ),
    LineMapping(
        bloomberg_label="Goodwill",
        parser_path="balance.goodwill",
        notes="Credito mercantil",
    ),
    LineMapping(
        bloomberg_label="Investment In Affiliates/Joint Ventures",
        parser_path="balance.investments_in_associates",
        notes="Inversiones en asociadas/JV",
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
    LineMapping(
        bloomberg_label="Short-Term Borrowings",
        parser_path="balance.short_term_debt",
        notes="Deuda financiera CP",
    ),
    LineMapping(
        bloomberg_label="Trade Payable And Other Payables",
        parser_path="balance.accounts_payable",
        notes="Proveedores",
    ),
    LineMapping(
        bloomberg_label="Total Current Liabilities",
        parser_path="balance.total_current_liabilities",
        notes="Total pasivos CP",
    ),
    LineMapping(
        bloomberg_label="Long Term Debt",
        parser_path="balance.long_term_debt",
        notes="Deuda financiera LP",
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
    LineMapping(
        bloomberg_label="Minority/Non Controlling Int (Stckhldrs Eqty)",
        parser_path="balance.minority_interest",
        notes="Interes minoritario",
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
        bloomberg_label="Total Liabilities and Shareholders Equity",
        parser_path="balance.total_assets",
        notes="Check: A = L + E",
    ),
]


# -----------------------------------------------------------------
# CASH FLOW - As Reported
# -----------------------------------------------------------------
CUERVO_CF_AR = [
    LineMapping(
        bloomberg_label="Net Income - CF",
        parser_path="income.net_income",
        notes="NI total (point of departure del CF)",
    ),
    LineMapping(
        bloomberg_label="Depreciation And Amortization - CF",
        parser_path="informative.da_12m",
        notes="D&A 12M",
    ),
    LineMapping(
        bloomberg_label="Income Tax Expense",
        parser_path="income.tax_expense",
        notes="Impuestos en el CF",
    ),
    LineMapping(
        bloomberg_label="Total Cash Flows From Operations",
        parser_path="cashflow.cfo",
        notes="CFO total acumulado",
    ),
]


CUERVO_FULL = BloombergMapping(
    ticker="CUERVO",
    income_ar=CUERVO_INCOME_AR,
    bs_ar=CUERVO_BS_AR,
    cf_ar=CUERVO_CF_AR,
)
