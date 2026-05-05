"""
Vistas estilo Bloomberg de los EEFF parseados del XBRL CNBV.

Replica el formato de las 5 hojas core de Bloomberg:
  1. GAAP Highlights         - resumen financial highlights
  2. Income - GAAP           - P&L detallado
  3. Bal Sheet - Standardized - balance general estandar
  4. Cash Flow - Standardized - flujo de efectivo estandar
  5. Enterprise Value         - EV con multiples

Columnas de cada DataFrame:
  - 'Concepto' (con indentacion para sub-items)
  - 'BBG Code' (codigo Bloomberg de referencia)
  - 'FY {year}' (valor MDP)
  - 'Tipo' (header / sub / total / line) para styling

Limitaciones:
  - Solo muestra el periodo reportado en el XBRL (sin historico 13y)
  - Algunos campos Bloomberg que requieren breakdown granular salen como
    '—' cuando el XBRL CNBV no los expone (ej. inventory raw materials)
"""

from typing import Any
import pandas as pd


M = 1_000_000  # convertir pesos a MDP

DASH = "—"
BLOOMBERG_HEADER = "In Millions of MXN"


def _fmt(v: Any) -> Any:
    """Formato Bloomberg: numericos con 1 decimal y separador miles, None -> em-dash."""
    if v is None:
        return DASH
    if isinstance(v, (int, float)):
        if v == 0:
            return 0.0
        return round(v, 4)
    return v


def _row(concept: str, bbg: str, value: Any, kind: str = "line") -> dict:
    return {"Concepto": concept, "BBG Code": bbg, "Valor (MDP)": _fmt(value), "Tipo": kind}


# ----------------------------------------------------------------------------
# 1) GAAP Highlights
# ----------------------------------------------------------------------------
def gaap_highlights(res, market_cap: float | None = None) -> pd.DataFrame:
    inc, bs, cf, info_ = res.income, res.balance, res.cashflow, res.informative
    rows = []
    rows.append(_row("Total Revenues",            "SALES_REV_TURN",         inc.revenue / M,                 "total"))
    rows.append(_row("Operating Income",          "IS_OPER_INC",            inc.ebit / M,                    "total"))
    rows.append(_row("Net Income to Common",      "EARN_FOR_COMMON",        (inc.net_income_controlling or inc.net_income) / M, "total"))
    eps = ((inc.net_income_controlling or inc.net_income) / info_.shares_outstanding) if info_.shares_outstanding else None
    rows.append(_row("Basic EPS, GAAP",           "IS_EPS",                 eps,                              "line"))
    rows.append(_row("Diluted EPS, GAAP",         "IS_DILUTED_EPS",         eps,                              "line"))
    rows.append(_row("  Basic Weighted Avg Sh.",  "IS_AVG_NUM_SH_FOR_EPS",  info_.shares_outstanding / M if info_.shares_outstanding else None, "sub"))
    rows.append(_row("  Diluted Weighted Avg Sh.","IS_SH_FOR_DILUTED_EPS",  info_.shares_outstanding / M if info_.shares_outstanding else None, "sub"))
    rows.append(_row("Cash and Equivalents",      "CASH_AND_MARKETABL_SEC", bs.cash / M,                      "line"))
    rows.append(_row("Total Current Assets",      "BS_CUR_ASSET_REPORT",    bs.total_current_assets / M,      "line"))
    rows.append(_row("Total Assets",              "BS_TOT_ASSET",           bs.total_assets / M,              "total"))
    rows.append(_row("Total Current Liabilities", "BS_CUR_LIAB",            bs.total_current_liabilities / M, "line"))
    rows.append(_row("Total Liabilities",         "BS_TOT_LIAB2",           bs.total_liabilities / M,         "total"))
    rows.append(_row("Total Equity",              "TOTAL_EQUITY",           bs.total_equity / M,              "total"))
    rows.append(_row("  Shares Outstanding",      "BS_SH_OUT",              info_.shares_outstanding / M if info_.shares_outstanding else None, "sub"))
    rows.append(_row("Cash From Operations",      "CF_CASH_FROM_OPER",      cf.cfo / M,                       "line"))
    rows.append(_row("Cash From Investing",       "CF_CASH_FROM_INV_ACT",   cf.cfi / M,                       "line"))
    rows.append(_row("Cash From Financing",       "CF_CASH_FROM_FNC_ACT",   cf.cff / M,                       "line"))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 2) Income Statement - GAAP
# ----------------------------------------------------------------------------
def income_statement_gaap(res) -> pd.DataFrame:
    inc, info_ = res.income, res.informative
    da = info_.da_12m / M if info_.da_12m else None

    rows = []
    rows.append(_row("Revenue",                       "SALES_REV_TURN",         inc.revenue / M,           "total"))
    rows.append(_row("    + Sales & Services Revenue","IS_SALES_AND_SERVICES",  inc.revenue / M,           "sub"))
    rows.append(_row("  - Cost of Revenue",           "IS_COGS_TO_FE_AND_PP_T", inc.cost_of_sales / M,     "line"))
    rows.append(_row("    + Cost of Goods Sold",      "IS_COG_AND_SERVICES_SO", inc.cost_of_sales / M,     "sub"))
    rows.append(_row("    + Depreciation in COGS",    "IS_DA_COST_OF_REVENUE",  None,                       "sub"))
    rows.append(_row("Gross Profit",                  "GROSS_PROFIT",           inc.gross_profit / M,       "total"))
    rows.append(_row("  + Other Operating Income",    "IS_OTHER_OPER_INC",      max(inc.other_operating, 0) / M if inc.other_operating else 0, "sub"))
    rows.append(_row("  - Operating Expenses",        "IS_OPERATING_EXPN",      inc.operating_expenses / M, "line"))
    rows.append(_row("    + SG&A",                    "IS_SGA_EXPENSE",         inc.operating_expenses / M, "sub"))
    rows.append(_row("    + Other Operating Expenses","OTHER_OPERATING_EXP",    max(-inc.other_operating, 0) / M if inc.other_operating else 0, "sub"))
    rows.append(_row("Operating Income (EBIT)",       "IS_OPER_INC",            inc.ebit / M,               "total"))
    rows.append(_row("  - Non-Operating Items, net",  "NONOP_INCOME_LOSS",      None,                        "line"))
    rows.append(_row("    + Interest Expense, net",   "IS_NET_INTEREST_EXP",    (inc.interest_expense - inc.interest_income) / M, "sub"))
    rows.append(_row("    + Interest Expense",        "IS_INT_EXPENSE",         inc.interest_expense / M,    "sub"))
    rows.append(_row("    - Interest Income",         "IS_INT_INC",             inc.interest_income / M,     "sub"))
    rows.append(_row("    + Foreign Exchange Loss",   "IS_FOREIGN_EXCH_LOSS",   inc.fx_result / M if inc.fx_result else None, "sub"))
    rows.append(_row("    + (Income) Loss from Assoc","INCOME_LOSS_FROM_ASSOC", -inc.associates_result / M if inc.associates_result else 0, "sub"))
    rows.append(_row("Pretax Income",                 "PRETAX_INC",             inc.pretax_income / M,       "total"))
    rows.append(_row("  - Income Tax Expense",        "IS_INC_TAX_EXP",         inc.tax_expense / M,         "line"))
    rows.append(_row("Income (Loss) from Continuing", "IS_INC_BEF_XO_ITEM",     inc.net_income / M,          "line"))
    rows.append(_row("  - Net Extraordinary Items",   "XO_GL_NET_OF_TAX",       0,                            "sub"))
    rows.append(_row("Income Including Minority Int", "NI_INCLUDING_MINORITY",  inc.net_income / M,           "line"))
    rows.append(_row("  - Minority Interest",         "MIN_NONCONTROL_INTEREST",inc.net_income_minority / M if inc.net_income_minority else 0, "line"))
    rows.append(_row("Net Income, GAAP",              "NET_INCOME",             (inc.net_income_controlling or inc.net_income) / M, "total"))
    rows.append(_row("Net Income Avail to Common",    "EARN_FOR_COMMON",        (inc.net_income_controlling or inc.net_income) / M, "total"))
    # Ratios
    rows.append(_row("Reference Items",               "",                       None,                         "header"))
    rows.append(_row("EBITDA",                        "EBITDA",                 (inc.ebit / M + (da or 0)),   "line"))
    rows.append(_row("EBIT",                          "EBIT",                   inc.ebit / M,                 "line"))
    rows.append(_row("Gross Margin",                  "GROSS_MARGIN",           inc.gross_margin * 100,       "line"))
    rows.append(_row("Operating Margin",              "OPER_MARGIN",            inc.operating_margin * 100,   "line"))
    rows.append(_row("Profit Margin",                 "PROF_MARGIN",            inc.net_margin * 100,         "line"))
    rows.append(_row("D&A Expense",                   "IS_DEPR_EXP",            da,                            "line"))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 3) Balance Sheet - Standardized
# ----------------------------------------------------------------------------
def balance_sheet_standardized(res) -> pd.DataFrame:
    bs, info_ = res.balance, res.informative
    rows = []

    rows.append(_row("Total Assets",                       "",                          None,                              "header"))
    rows.append(_row("  + Cash, Cash Equiv & ST Inv",     "CASH_CASH_EQTY_STI",        bs.cash / M,                       "line"))
    rows.append(_row("    + Cash & Cash Equivalents",     "BS_CASH_NEAR_CASH_ITEM",    bs.cash / M,                       "sub"))
    rows.append(_row("    + ST Investments",              "BS_MKT_SEC_OTHER_STI",      0,                                 "sub"))
    rows.append(_row("  + Accounts & Notes Receivable",   "BS_ACCT_NOTE_RCV",          bs.accounts_receivable / M,        "line"))
    rows.append(_row("    + Accounts Receivable, Net",    "BS_ACCTS_REC_EXCL_NOTES",   bs.accounts_receivable / M,        "sub"))
    rows.append(_row("  + Inventories",                   "BS_INVENTORIES",            bs.inventories / M,                "line"))
    rows.append(_row("  + Other ST Assets",               "OTHER_CURRENT_ASSETS",      bs.other_current_assets / M,       "line"))
    rows.append(_row("Total Current Assets",              "BS_CUR_ASSET_REPORT",       bs.total_current_assets / M,       "total"))
    rows.append(_row("  + Property, Plant & Equipment",   "BS_NET_FIX_ASSET",          bs.ppe / M,                        "line"))
    rows.append(_row("  + Right-of-Use Assets (IFRS 16)", "ROU_ASSETS",                bs.right_of_use_assets / M,        "line"))
    rows.append(_row("  + LT Investments & Associates",   "BS_LT_INVEST",              bs.investments_in_associates / M,  "line"))
    rows.append(_row("  + Other LT Assets",               "BS_OTHER_ASSETS_DEF_CHRG",  None,                              "line"))
    rows.append(_row("    + Total Intangibles",           "BS_DISCLOSED_INTANGIBLES",  (bs.intangibles + bs.goodwill) / M,"sub"))
    rows.append(_row("    + Goodwill",                    "BS_GOODWILL",               bs.goodwill / M,                   "sub"))
    rows.append(_row("    + Other Intangible Assets",     "OTHER_INTANGIBLE_ASSETS",   bs.intangibles / M,                "sub"))
    rows.append(_row("    + Deferred Tax Assets",         "BS_DEFERRED_TAX_ASSETS",    bs.deferred_tax_assets / M,        "sub"))
    rows.append(_row("    + Misc LT Assets",              "OTHER_NONCURRENT_ASSETS",   bs.other_non_current_assets / M,   "sub"))
    rows.append(_row("Total Noncurrent Assets",           "BS_TOT_NON_CUR_ASSETS",     bs.total_non_current_assets / M,   "total"))
    rows.append(_row("Total Assets",                      "BS_TOT_ASSET",              bs.total_assets / M,               "total"))

    rows.append(_row("Liabilities & Shareholders' Equity","",                          None,                              "header"))
    rows.append(_row("  + Payables & Accruals",           "ACCT_PAYABLE_ACCRUALS_DET", bs.accounts_payable / M,           "line"))
    rows.append(_row("    + Accounts Payable",            "BS_ACCT_PAYABLE",           bs.accounts_payable / M,           "sub"))
    rows.append(_row("  + ST Debt",                       "BS_ST_BORROW",              (bs.short_term_debt + bs.short_term_lease) / M, "line"))
    rows.append(_row("    + ST Borrowings",               "SHORT_TERM_DEBT_DETAILED",  bs.short_term_debt / M,            "sub"))
    rows.append(_row("    + ST Lease Liabilities",        "ST_CAPITALIZED_LEASE_OBL",  bs.short_term_lease / M,           "sub"))
    rows.append(_row("  + Other ST Liabilities",          "OTHER_CURRENT_LIABILITIES", bs.other_current_liabilities / M,  "line"))
    rows.append(_row("Total Current Liabilities",         "BS_CUR_LIAB",               bs.total_current_liabilities / M,  "total"))
    rows.append(_row("  + LT Debt",                       "BS_LT_BORROW",              (bs.long_term_debt + bs.long_term_lease) / M, "line"))
    rows.append(_row("    + LT Borrowings",               "LONG_TERM_BORROWINGS",      bs.long_term_debt / M,             "sub"))
    rows.append(_row("    + LT Lease Liabilities",        "LT_CAPITALIZED_LEASE_OBL",  bs.long_term_lease / M,            "sub"))
    rows.append(_row("  + Other LT Liabilities",          "OTHER_NONCUR_LIABS",        None,                              "line"))
    rows.append(_row("    + Deferred Tax Liabilities",    "BS_DEFERRED_TAX_LIABILITY", bs.deferred_tax_liabilities / M,   "sub"))
    rows.append(_row("    + Misc LT Liabilities",         "OTHER_NONCURRENT_LIAB",     bs.other_non_current_liabilities / M, "sub"))
    rows.append(_row("Total Noncurrent Liabilities",      "NON_CUR_LIAB",              bs.total_non_current_liabilities / M, "total"))
    rows.append(_row("Total Liabilities",                 "BS_TOT_LIAB2",              bs.total_liabilities / M,          "total"))
    rows.append(_row("  + Preferred Equity",              "PFD_EQTY_HYBRID_CAP",       0,                                 "line"))
    rows.append(_row("  + Equity Before Minority Int.",   "EQTY_BEF_MINORITY_INT_DET", bs.equity_controlling / M,         "line"))
    rows.append(_row("  + Minority/Non-Controlling Int.", "MINORITY_NONCONTROL_INTER", bs.minority_interest / M,          "line"))
    rows.append(_row("Total Equity",                      "TOTAL_EQUITY",              bs.total_equity / M,               "total"))
    rows.append(_row("Total Liabilities & Equity",        "TOT_LIAB_AND_SH_EQTY",      (bs.total_liabilities + bs.total_equity) / M, "total"))

    # Reference items
    rows.append(_row("Reference Items",                   "",                          None,                              "header"))
    rows.append(_row("Net Debt (incl. Leases)",           "NET_DEBT",                  bs.net_debt / M,                   "line"))
    rows.append(_row("Total Financial Debt",              "SHORT_AND_LONG_TERM_DEBT",  bs.total_financial_debt / M,       "line"))
    rows.append(_row("Total Lease Debt (IFRS 16)",        "TOTAL_LEASE_DEBT",          bs.total_lease_debt / M,           "line"))
    rows.append(_row("Working Capital",                   "BS_WORKING_CAPITAL",        bs.working_capital / M,            "line"))
    rows.append(_row("Invested Capital",                  "INVESTED_CAPITAL",          bs.invested_capital / M,           "line"))
    rows.append(_row("Shares Outstanding (mn)",           "BS_SH_OUT",                 info_.shares_outstanding / M if info_.shares_outstanding else None, "line"))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 4) Cash Flow - Standardized
# ----------------------------------------------------------------------------
def cash_flow_standardized(res) -> pd.DataFrame:
    cf, inc, info_ = res.cashflow, res.income, res.informative
    da = info_.da_12m / M if info_.da_12m else None
    fcf = (cf.cfo - cf.capex_gross) / M
    rows = []

    rows.append(_row("Cash from Operating Activities",     "",                          None,                            "header"))
    rows.append(_row("  + Net Income",                     "CF_NET_INC",                inc.net_income / M,              "line"))
    rows.append(_row("  + Depreciation & Amortization",    "CF_DEPR_AMORT",             da,                              "line"))
    rows.append(_row("  + Non-Cash Items",                 "NON_CASH_ITEMS_DETAILED",   None,                            "line"))
    rows.append(_row("  + Chg in Non-Cash Working Capital","CF_CHNG_NON_CASH_WORK_CAP", None,                            "line"))
    rows.append(_row("Cash from Operating Activities",     "CF_CASH_FROM_OPER",         cf.cfo / M,                      "total"))

    rows.append(_row("Cash from Investing Activities",     "",                          None,                            "header"))
    rows.append(_row("  + Change in Fixed/Intangible Asts","FIXED_INTANG_ASST_NET_INV", -cf.capex_gross / M,             "line"))
    rows.append(_row("    + Acq of Fixed Productive Asts", "ACQUIS_OF_FIXED_INT_ASSETS",-cf.capex_gross / M,             "sub"))
    rows.append(_row("    + Disp of Fixed Productive Ast", "DISPOSAL_OF_FIXED_INT_AST", cf.sales_of_ppe / M,             "sub"))
    rows.append(_row("    + Acq of PPE",                   "CF_PURCHASE_OF_FIXED_AST",  -cf.capex_ppe / M,               "sub"))
    rows.append(_row("    + Acq of Intangibles",           "CF_ACQUISITION_OF_INTANG",  -cf.capex_intangibles / M,       "sub"))
    rows.append(_row("  + Net Cash From Acq/Div.",         "CF_NT_CSH_RCVD_PD_FOR_AC",  -cf.acquisitions / M if cf.acquisitions else 0, "line"))
    rows.append(_row("Cash from Investing Activities",     "CF_CASH_FROM_INV_ACT",      cf.cfi / M,                      "total"))

    rows.append(_row("Cash from Financing Activities",     "",                          None,                            "header"))
    rows.append(_row("  + Dividends Paid",                 "CF_DVD_PAID",               -abs(cf.dividends_paid) / M,     "line"))
    rows.append(_row("  + Cash From (Repayment) of Debt",  "PROC_FR_REPAYMNTS_BORROW",  (cf.debt_issued - cf.debt_repaid) / M, "line"))
    rows.append(_row("    + Proceeds from LT Debt",        "CF_LT_DEBT_PROCEEDS",       cf.debt_issued / M,              "sub"))
    rows.append(_row("    + Repayments of LT Debt",        "CF_LT_DEBT_REPAYMENT",      -cf.debt_repaid / M,             "sub"))
    rows.append(_row("Cash from Financing Activities",     "CFF_ACTIVITIES_DETAILED",   cf.cff / M,                      "total"))

    rows.append(_row("Effect of Foreign Exchange",         "CF_EFFECT_FOREIGN_EXCH",    None,                            "line"))
    rows.append(_row("Net Changes in Cash",                "CF_NET_CHNG_CASH",          cf.net_change_cash / M,          "total"))

    # Reference Items
    rows.append(_row("Reference Items",                    "",                          None,                            "header"))
    rows.append(_row("EBITDA",                             "EBITDA",                    (inc.ebit / M + (da or 0)),      "line"))
    rows.append(_row("Capital Expenditures (Gross)",       "CAPITAL_EXPEND",            -cf.capex_gross / M,             "line"))
    rows.append(_row("Capital Expenditures (Net)",         "CAPEX_NET",                 -cf.capex_net / M,               "line"))
    rows.append(_row("Free Cash Flow",                     "CF_FREE_CASH_FLOW",         fcf,                              "total"))
    rows.append(_row("Free Cash Flow / Share (MXN)",       "FREE_CASH_FLOW_PER_SH",     (fcf * M / info_.shares_outstanding) if info_.shares_outstanding else None, "line"))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 5) Enterprise Value
# ----------------------------------------------------------------------------
def enterprise_value_table(res, market_price: float, shares_outstanding: float | None = None) -> pd.DataFrame:
    """Calcula EV bridge y multiplos comunes. Asume market_price en MXN."""
    bs, inc, info_, cf = res.balance, res.income, res.informative, res.cashflow
    sh = (shares_outstanding or info_.shares_outstanding) / M if (shares_outstanding or info_.shares_outstanding) else None
    market_cap = market_price * sh if sh else None
    cash = bs.cash / M
    debt = bs.total_debt_with_leases / M
    minority = bs.minority_interest / M
    ev = (market_cap - cash + debt + minority) if market_cap is not None else None

    da = info_.da_12m / M if info_.da_12m else None
    ebitda = inc.ebit / M + (da or 0)
    fcf = (cf.cfo - cf.capex_gross) / M

    rows = []
    rows.append(_row("Market Capitalization",        "HISTORICAL_MARKET_CAP", market_cap,      "line"))
    rows.append(_row("  - Cash & Equivalents",       "CASH_AND_MARKETABL_SEC",cash,            "sub"))
    rows.append(_row("  + Preferred & Other Claims", "PFD_EQTY_MINORTY_INT",  minority,        "sub"))
    rows.append(_row("  + Total Debt",               "SHORT_AND_LONG_TERM_DEBT", debt,         "sub"))
    rows.append(_row("Enterprise Value",             "ENTERPRISE_VALUE",      ev,              "total"))
    rows.append(_row("",                              "",                      None,            "header"))
    rows.append(_row("Total Debt / Total Capital",   "TOT_DEBT_TO_TOT_CAP",   (debt / (debt + (market_cap or 0)) * 100) if market_cap else None, "line"))
    rows.append(_row("Total Debt / EV",              "TOTAL_DEBT_TO_EV",      (debt / ev * 100) if ev else None, "line"))
    rows.append(_row("",                              "",                      None,            "header"))
    rows.append(_row("EV / Sales",                   "EV_TO_T12M_SALES",      (ev / (inc.revenue / M)) if ev and inc.revenue else None, "line"))
    rows.append(_row("EV / EBITDA",                  "EV_TO_T12M_EBITDA",     (ev / ebitda) if ev and ebitda else None, "line"))
    rows.append(_row("EV / EBIT",                    "EV_TO_T12M_EBIT",       (ev / (inc.ebit / M)) if ev and inc.ebit else None, "line"))
    rows.append(_row("EV / Cash Flow from Op.",      "EV_TO_T12M_CASH_FLOW",  (ev / (cf.cfo / M)) if ev and cf.cfo else None, "line"))
    rows.append(_row("EV / Free Cash Flow",          "EV_TO_T12M_FREE_CASH",  (ev / fcf) if ev and fcf else None, "line"))
    rows.append(_row("EV / Share (MXN)",             "EV_TO_SH_OUT",          (ev / sh) if ev and sh else None, "line"))
    rows.append(_row("",                              "",                      None,            "header"))
    rows.append(_row("Reference: EBITDA (12M)",      "TRAIL_12M_EBITDA",      ebitda,          "line"))
    rows.append(_row("Reference: EBIT (12M)",        "TRAIL_12M_OPER_INC",    inc.ebit / M,    "line"))
    rows.append(_row("Reference: Sales (12M)",       "TRAIL_12M_NET_SALES",   inc.revenue / M, "line"))
    rows.append(_row("Reference: Free Cash Flow",    "TRAIL_12M_FREE_CASH",   fcf,             "line"))
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# Master builder
# ----------------------------------------------------------------------------
def build_all_sheets(res, market_price: float | None = None) -> dict[str, pd.DataFrame]:
    """Construye las 5 hojas Bloomberg-style. Devuelve dict {sheet_name: df}."""
    return {
        "GAAP Highlights":           gaap_highlights(res),
        "Income - GAAP":             income_statement_gaap(res),
        "Bal Sheet - Standardized":  balance_sheet_standardized(res),
        "Cash Flow - Standardized":  cash_flow_standardized(res),
        "Enterprise Value":          enterprise_value_table(res, market_price or 0.0),
    }
