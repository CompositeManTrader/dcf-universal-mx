"""
Construye paneles historicos estilo Bloomberg para Income / Balance / Cash Flow.

Cada panel es un DataFrame:
  - filas: lineas del estado financiero (Total Revenue, EBIT, NI, etc.)
  - columnas: periodos (FY 2022, FY 2023, ... o Q1 2022, Q2 2022, ...)
  - valores: en MDP (auto-ajustados USD->MXN si la emisora reporta en USD)

Compatible con cualquier ParseResult del parser CNBV.
Las etiquetas siguen el esquema Bloomberg standardizado.
"""

from dataclasses import dataclass
from typing import Callable, Optional

import pandas as pd

from dcf_mexico.historical.panel import _detect_fx_mult


# ---------------------------------------------------------------------------
# Row definitions: (label, getter, kind)
#   kind:
#     "header"   -> bold, fondo verde claro (totales clave)
#     "subtotal" -> bold, fondo gris (subtotales)
#     "line"     -> normal
#     "ratio"    -> formato % (no MDP)
#     "spacer"   -> linea vacia visual
# ---------------------------------------------------------------------------

def _safe(getter, parsed):
    try:
        v = getter(parsed)
        return float(v) if v is not None else None
    except Exception:
        return None


# ----- INCOME STATEMENT ------------------------------------------------
INCOME_LINES = [
    # (label, getter (or None for spacer), kind)
    ("Total Revenue",                       lambda r: r.income.revenue,                                "header"),
    ("Cost of Goods Sold",                  lambda r: r.income.cost_of_sales,                          "line"),
    ("Gross Profit",                        lambda r: r.income.gross_profit,                           "subtotal"),
    ("Operating Expenses (SG&A + Other)",   lambda r: r.income.operating_expenses + r.income.other_operating, "line"),
    ("Operating Income (EBIT)",             lambda r: r.income.ebit,                                   "header"),
    ("D&A (12M)",                           lambda r: r.informative.da_12m,                            "line"),
    ("EBITDA (EBIT + D&A)",                 lambda r: r.income.ebit + r.informative.da_12m,            "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("Interest Income (negativo = ingreso)",lambda r: r.income.interest_income,                        "line"),
    ("Interest Expense",                    lambda r: r.income.interest_expense,                       "line"),
    ("Equity in Earnings of Affiliates/JV", lambda r: r.income.associates_result,                      "line"),
    ("Income Before Taxes",                 lambda r: r.income.pretax_income,                          "subtotal"),
    ("Income Tax Expense",                  lambda r: r.income.tax_expense,                            "line"),
    ("Net Income (Total)",                  lambda r: r.income.net_income,                             "subtotal"),
    ("Minority Interest",                   lambda r: r.income.net_income_minority,                    "line"),
    ("Net Income to Parent",                lambda r: r.income.net_income_controlling,                 "header"),
    ("",                                    None,                                                       "spacer"),
    ("Gross Margin %",                      lambda r: r.income.gross_margin,                           "ratio"),
    ("Operating Margin %",                  lambda r: r.income.operating_margin,                       "ratio"),
    ("EBITDA Margin %",                     lambda r: ((r.income.ebit + r.informative.da_12m) / r.income.revenue) if r.income.revenue else 0, "ratio"),
    ("Net Margin %",                        lambda r: r.income.net_margin,                             "ratio"),
    ("Effective Tax Rate %",                lambda r: r.income.effective_tax_rate,                     "ratio"),
]

# ----- BALANCE SHEET ---------------------------------------------------
BALANCE_LINES = [
    ("Cash and Equivalents",                lambda r: r.balance.cash,                                  "line"),
    ("Accounts Receivable",                 lambda r: r.balance.accounts_receivable,                   "line"),
    ("Inventories",                         lambda r: r.balance.inventories,                           "line"),
    ("Other Current Assets",                lambda r: r.balance.other_current_assets,                  "line"),
    ("Total Current Assets",                lambda r: r.balance.total_current_assets,                  "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("Property, Plant & Equipment",         lambda r: r.balance.ppe,                                   "line"),
    ("Right-of-Use Assets (IFRS-16)",       lambda r: r.balance.right_of_use_assets,                   "line"),
    ("Intangible Assets (ex-Goodwill)",     lambda r: r.balance.intangibles,                           "line"),
    ("Goodwill",                            lambda r: r.balance.goodwill,                              "line"),
    ("Investments in Associates/JV",        lambda r: r.balance.investments_in_associates,             "line"),
    ("Deferred Tax Assets",                 lambda r: r.balance.deferred_tax_assets,                   "line"),
    ("Other Non-Current Assets",            lambda r: r.balance.other_non_current_assets,              "line"),
    ("Total Non-Current Assets",            lambda r: r.balance.total_non_current_assets,              "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("TOTAL ASSETS",                        lambda r: r.balance.total_assets,                          "header"),
    ("",                                    None,                                                       "spacer"),
    ("Accounts Payable",                    lambda r: r.balance.accounts_payable,                      "line"),
    ("Short-Term Debt",                     lambda r: r.balance.short_term_debt,                       "line"),
    ("Short-Term Lease Liab. (IFRS-16)",    lambda r: r.balance.short_term_lease,                      "line"),
    ("Other Current Liabilities",           lambda r: r.balance.other_current_liabilities,             "line"),
    ("Total Current Liabilities",           lambda r: r.balance.total_current_liabilities,             "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("Long-Term Debt",                      lambda r: r.balance.long_term_debt,                        "line"),
    ("Long-Term Lease Liab. (IFRS-16)",     lambda r: r.balance.long_term_lease,                       "line"),
    ("Deferred Tax Liabilities",            lambda r: r.balance.deferred_tax_liabilities,              "line"),
    ("Other Non-Current Liabilities",       lambda r: r.balance.other_non_current_liabilities,         "line"),
    ("Total Non-Current Liabilities",       lambda r: r.balance.total_non_current_liabilities,         "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("TOTAL LIABILITIES",                   lambda r: r.balance.total_liabilities,                     "header"),
    ("",                                    None,                                                       "spacer"),
    ("Equity (Controlling)",                lambda r: r.balance.equity_controlling,                    "line"),
    ("Minority Interest",                   lambda r: r.balance.minority_interest,                     "line"),
    ("TOTAL EQUITY",                        lambda r: r.balance.total_equity,                          "header"),
    ("",                                    None,                                                       "spacer"),
    ("TOTAL LIABILITIES + EQUITY",          lambda r: r.balance.total_liabilities + r.balance.total_equity, "header"),
    ("",                                    None,                                                       "spacer"),
    # Derivados
    ("Total Financial Debt (CP+LP)",        lambda r: r.balance.total_financial_debt,                  "subtotal"),
    ("Total Lease Debt (IFRS-16)",          lambda r: r.balance.total_lease_debt,                      "subtotal"),
    ("Total Debt incl. Leases",             lambda r: r.balance.total_debt_with_leases,                "subtotal"),
    ("Net Debt",                            lambda r: r.balance.net_debt,                              "subtotal"),
    ("Working Capital",                     lambda r: r.balance.working_capital,                       "subtotal"),
    ("Invested Capital",                    lambda r: r.balance.invested_capital,                      "subtotal"),
]

# ----- CASH FLOW -------------------------------------------------------
CASHFLOW_LINES = [
    ("Cash Flow from Operations (CFO)",     lambda r: r.cashflow.cfo,                                  "header"),
    ("",                                    None,                                                       "spacer"),
    ("CapEx - PPE",                         lambda r: r.cashflow.capex_ppe,                            "line"),
    ("CapEx - Intangibles",                 lambda r: r.cashflow.capex_intangibles,                    "line"),
    ("Sales of PPE",                        lambda r: r.cashflow.sales_of_ppe,                         "line"),
    ("Acquisitions",                        lambda r: r.cashflow.acquisitions,                         "line"),
    ("Cash Flow from Investing (CFI)",      lambda r: r.cashflow.cfi,                                  "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("Debt Issued",                         lambda r: r.cashflow.debt_issued,                          "line"),
    ("Debt Repaid",                         lambda r: r.cashflow.debt_repaid,                          "line"),
    ("Dividends Paid",                      lambda r: r.cashflow.dividends_paid,                       "line"),
    ("Cash Flow from Financing (CFF)",      lambda r: r.cashflow.cff,                                  "subtotal"),
    ("",                                    None,                                                       "spacer"),
    ("Net Change in Cash",                  lambda r: r.cashflow.net_change_cash,                      "header"),
    ("",                                    None,                                                       "spacer"),
    # Derivados
    ("CapEx Gross (PPE + Intangibles)",     lambda r: r.cashflow.capex_gross,                          "subtotal"),
    ("CapEx Net (Gross - Sales of PPE)",    lambda r: r.cashflow.capex_net,                            "subtotal"),
    ("FCFF Simple (CFO - CapEx Net)",       lambda r: r.cashflow.cfo - r.cashflow.capex_net,           "header"),
]


# ---------------------------------------------------------------------------
# Builder generico
# ---------------------------------------------------------------------------

def _build_panel(
    series,
    rows_def: list,
    annual_only: bool = False,
    fx_rate_usdmxn: float = 19.5,
    max_periods: Optional[int] = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Devuelve (DataFrame con filas=labels, cols=periodos, valores), kinds_list.

    kinds_list es paralelo al index del DataFrame y contiene el "kind" de cada fila
    (header/subtotal/line/ratio/spacer) para usar en el styling.
    """
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]

    cols_data = {}
    kinds = [k for (_, _, k) in rows_def]
    labels = [l for (l, _, _) in rows_def]

    if not snaps:
        df_empty = pd.DataFrame(index=labels, columns=[])
        return df_empty, kinds

    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)
        col_vals = []
        for label, getter, kind in rows_def:
            if kind == "spacer" or getter is None:
                col_vals.append(None)
                continue
            raw = _safe(getter, s.parsed)
            if raw is None:
                col_vals.append(None)
                continue
            if kind == "ratio":
                col_vals.append(raw)  # ya es ratio
            else:
                col_vals.append((raw * fx) / 1_000_000)  # MDP
        cols_data[s.label] = col_vals

    df = pd.DataFrame(cols_data, index=labels)
    return df, kinds


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def build_income_panel(series, annual_only: bool = False,
                        fx_rate_usdmxn: float = 19.5,
                        max_periods: Optional[int] = None):
    """Income Statement historico. Returns (DataFrame, kinds_list)."""
    return _build_panel(series, INCOME_LINES, annual_only, fx_rate_usdmxn, max_periods)


def build_bs_panel(series, annual_only: bool = False,
                    fx_rate_usdmxn: float = 19.5,
                    max_periods: Optional[int] = None):
    """Balance Sheet historico. Returns (DataFrame, kinds_list)."""
    return _build_panel(series, BALANCE_LINES, annual_only, fx_rate_usdmxn, max_periods)


def build_cf_panel(series, annual_only: bool = False,
                    fx_rate_usdmxn: float = 19.5,
                    max_periods: Optional[int] = None):
    """Cash Flow historico. Returns (DataFrame, kinds_list)."""
    return _build_panel(series, CASHFLOW_LINES, annual_only, fx_rate_usdmxn, max_periods)


def format_panel(df: pd.DataFrame, kinds: list[str]) -> pd.DataFrame:
    """Formatea valores segun kind:
       - 'ratio'     -> % con 2 decimales (ej. 22.43%)
       - 'ratio_eps' -> 4 decimales (ej. 0.3892 para EPS)
       - 'string'   -> texto raw (ej. 'IAS/IFRS')
       - 'spacer'/'section' -> vacio
       - resto      -> MDP con separador miles (ej. 11,076.7)
    """
    if df.empty or df.shape[1] == 0:
        return pd.DataFrame(index=df.index, columns=df.columns, dtype=object)

    fmt_data = {}
    for col in df.columns:
        col_fmt = []
        for i, val in enumerate(df[col]):
            kind = kinds[i] if i < len(kinds) else "line"
            if kind in ("spacer", "section"):
                col_fmt.append("")
            elif val is None or (isinstance(val, float) and pd.isna(val)):
                col_fmt.append("—")
            elif kind == "ratio":
                col_fmt.append(f"{val:.2%}")
            elif kind == "ratio_eps":
                col_fmt.append(f"{val:.4f}")
            elif kind == "ratio_x":
                col_fmt.append(f"{val:.2f}x")
            elif kind == "raw_days":
                col_fmt.append(f"{val:,.1f} days")
            elif kind == "raw":
                col_fmt.append(f"{val:,.1f}")
            elif kind == "string":
                col_fmt.append(str(val))
            else:
                col_fmt.append(f"{val:,.1f}")
        fmt_data[col] = col_fmt
    return pd.DataFrame(fmt_data, index=df.index, dtype=object)
