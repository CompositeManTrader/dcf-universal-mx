"""
Layouts estilo Bloomberg "Adjusted" / "Standardized" usando los datos del parser.

Cada layout es una lista de (label_bloomberg, getter, kind).

Diferencia clave con financial_panels.py:
  - Aqui los labels y orden siguen Bloomberg "Adjusted/Standardized"
  - Para vista trimestral, getters apuntan a `income_quarter` o usan
    derivadores especiales para Cash Flow (Q acum - Q-1 acum)
  - Para vista anual, getters apuntan a `income` (acumulado YTD del Q4)
"""
from __future__ import annotations

import pandas as pd
from typing import Optional

from .panel import _detect_fx_mult


# ---------------------------------------------------------------------------
# INCOME - Adjusted (estilo Bloomberg)
# ---------------------------------------------------------------------------

def _income_adjusted_lines(use_quarter_data: bool):
    """Devuelve INCOME_LINES adaptado para vista anual o trimestral.

    use_quarter_data=True -> usa res.income_quarter (3 meses puros)
    use_quarter_data=False -> usa res.income (acumulado, full year para Q4)
    """
    src = "income_quarter" if use_quarter_data else "income"

    def _get(field):
        def f(r):
            obj = getattr(r, src, None)
            if obj is None:
                return None
            return getattr(obj, field, None)
        return f

    def _ratio(num_field, den_field):
        def f(r):
            obj = getattr(r, src, None)
            if obj is None: return None
            num = getattr(obj, num_field, 0) or 0
            den = getattr(obj, den_field, 0) or 0
            return (num / den) if den else 0
        return f

    return [
        ("Revenue",                            _get("revenue"),               "header"),
        ("- Cost of Revenue",                  _get("cost_of_sales"),         "line"),
        ("Gross Profit",                       _get("gross_profit"),          "subtotal"),
        ("- Operating Expenses (SG&A)",        _get("operating_expenses"),    "line"),
        ("+ Other Operating Income/(Expense)", _get("other_operating"),       "line"),
        ("Operating Income (EBIT)",            _get("ebit"),                  "header"),
        ("",                                   None,                          "spacer"),
        ("- Interest Expense, Net",            lambda r: (
            (getattr(getattr(r, src, None) or type('X', (), {})(), 'interest_expense', 0) or 0) -
            (getattr(getattr(r, src, None) or type('X', (), {})(), 'interest_income', 0) or 0)
        ),                                                                     "line"),
        ("    + Interest Expense",             _get("interest_expense"),      "line"),
        ("    - Interest Income",              _get("interest_income"),       "line"),
        ("+ Foreign Exchange Gain/(Loss)",     _get("fx_result"),             "line"),
        ("+ Equity in Earnings of Affiliates", _get("associates_result"),     "line"),
        ("Pretax Income (Loss)",               _get("pretax_income"),         "subtotal"),
        ("- Income Tax Expense",               _get("tax_expense"),           "line"),
        ("Net Income (incl. Minority)",        _get("net_income"),            "subtotal"),
        ("- Minority Interest",                _get("net_income_minority"),   "line"),
        ("Net Income to Common (GAAP)",        _get("net_income_controlling"),"header"),
        ("",                                   None,                          "spacer"),
        # Reference items
        ("Reference Items",                    None,                          "section"),
        ("D&A (12M trailing)",                 lambda r: r.informative.da_12m,"line"),
        ("EBITDA (EBIT + D&A 12M)",            lambda r: ((getattr(getattr(r, src), 'ebit', 0) or 0) + (r.informative.da_12m or 0)), "subtotal"),
        ("",                                   None,                          "spacer"),
        ("Gross Margin",                       _ratio("gross_profit", "revenue"),  "ratio"),
        ("Operating Margin",                   _ratio("ebit", "revenue"),     "ratio"),
        ("Profit Margin",                      _ratio("net_income_controlling", "revenue"), "ratio"),
        ("Effective Tax Rate",                 _ratio("tax_expense", "pretax_income"), "ratio"),
    ]


# ---------------------------------------------------------------------------
# BAL SHEET - Standardized (estilo Bloomberg)
# Balance es snapshot, no requiere quarter vs annual distintos
# ---------------------------------------------------------------------------

BS_STANDARDIZED_LINES = [
    ("Total Assets",                        None,                                                      "section"),
    ("+ Cash, Cash Equivalents & STI",      lambda r: r.balance.cash,                                  "line"),
    ("+ Accounts & Notes Receivable",       lambda r: r.balance.accounts_receivable,                   "line"),
    ("+ Inventories",                       lambda r: r.balance.inventories,                           "line"),
    ("+ Other ST Assets",                   lambda r: r.balance.other_current_assets,                  "line"),
    ("Total Current Assets",                lambda r: r.balance.total_current_assets,                  "subtotal"),
    ("+ Property, Plant & Equip, Net",      lambda r: r.balance.ppe,                                   "line"),
    ("+ Right-of-Use Assets (IFRS-16)",     lambda r: r.balance.right_of_use_assets,                   "line"),
    ("+ LT Investments / Affiliates",       lambda r: r.balance.investments_in_associates,             "line"),
    ("+ Total Intangible Assets",           lambda r: r.balance.intangibles + r.balance.goodwill,      "line"),
    ("    + Goodwill",                      lambda r: r.balance.goodwill,                              "line"),
    ("    + Other Intangibles",             lambda r: r.balance.intangibles,                           "line"),
    ("+ Deferred Tax Assets",               lambda r: r.balance.deferred_tax_assets,                   "line"),
    ("+ Other LT Assets",                   lambda r: r.balance.other_non_current_assets,              "line"),
    ("Total Noncurrent Assets",             lambda r: r.balance.total_non_current_assets,              "subtotal"),
    ("Total Assets",                        lambda r: r.balance.total_assets,                          "header"),
    ("",                                    None,                                                       "spacer"),
    ("Liabilities & Shareholders' Equity",  None,                                                       "section"),
    ("+ Accounts Payable",                  lambda r: r.balance.accounts_payable,                      "line"),
    ("+ ST Debt",                           lambda r: r.balance.short_term_debt + r.balance.short_term_lease, "line"),
    ("    + ST Borrowings",                 lambda r: r.balance.short_term_debt,                       "line"),
    ("    + ST Lease Liabilities",          lambda r: r.balance.short_term_lease,                      "line"),
    ("+ Other ST Liabilities",              lambda r: r.balance.other_current_liabilities,             "line"),
    ("Total Current Liabilities",           lambda r: r.balance.total_current_liabilities,             "subtotal"),
    ("+ LT Debt",                           lambda r: r.balance.long_term_debt + r.balance.long_term_lease, "line"),
    ("    + LT Borrowings",                 lambda r: r.balance.long_term_debt,                        "line"),
    ("    + LT Lease Liabilities",          lambda r: r.balance.long_term_lease,                       "line"),
    ("+ Deferred Tax Liabilities",          lambda r: r.balance.deferred_tax_liabilities,              "line"),
    ("+ Other LT Liabilities",              lambda r: r.balance.other_non_current_liabilities,         "line"),
    ("Total Noncurrent Liabilities",        lambda r: r.balance.total_non_current_liabilities,         "subtotal"),
    ("Total Liabilities",                   lambda r: r.balance.total_liabilities,                     "header"),
    ("",                                    None,                                                       "spacer"),
    ("Equity Before Minority Interest",     lambda r: r.balance.equity_controlling,                    "line"),
    ("+ Minority/Non Controlling Interest", lambda r: r.balance.minority_interest,                     "line"),
    ("Total Equity",                        lambda r: r.balance.total_equity,                          "header"),
    ("Total Liabilities & Equity",          lambda r: r.balance.total_liabilities + r.balance.total_equity, "header"),
    ("",                                    None,                                                       "spacer"),
    ("Reference Items",                     None,                                                       "section"),
    ("Net Debt",                            lambda r: r.balance.net_debt,                              "subtotal"),
    ("Total Debt incl. Leases",             lambda r: r.balance.total_debt_with_leases,                "subtotal"),
    ("Working Capital",                     lambda r: r.balance.working_capital,                       "subtotal"),
    ("Invested Capital",                    lambda r: r.balance.invested_capital,                      "subtotal"),
    ("Shares Outstanding (mn)",             lambda r: r.informative.shares_outstanding / 1e6,          "raw"),
]


# ---------------------------------------------------------------------------
# CASH FLOW - Standardized (estilo Bloomberg)
# Para trimestral hay que DERIVAR (snapshot Q acum - snapshot Q-1 acum)
# ---------------------------------------------------------------------------

CF_STANDARDIZED_LINES = [
    ("Cash from Operating Activities",      None,                                                       "section"),
    ("+ Net Income",                        lambda r: r.income.net_income,                              "line"),
    ("+ Depreciation & Amortization",       lambda r: r.informative.da_12m,                             "line"),
    ("+ Change in Working Capital (proxy)", lambda r: 0.0,  # no separable de CFO en parser
                                                                                                          "line"),
    ("Cash from Operating Activities",      lambda r: r.cashflow.cfo,                                    "header"),
    ("",                                    None,                                                       "spacer"),
    ("Cash from Investing Activities",      None,                                                       "section"),
    ("+ Acq of Fixed Assets (CapEx PPE)",   lambda r: -r.cashflow.capex_ppe,                            "line"),
    ("+ Acq of Intangible Assets",          lambda r: -r.cashflow.capex_intangibles,                    "line"),
    ("+ Disposal of Fixed Assets",          lambda r: r.cashflow.sales_of_ppe,                          "line"),
    ("+ Acquisitions/Subsidiaries (net)",   lambda r: -r.cashflow.acquisitions,                         "line"),
    ("Cash from Investing Activities",      lambda r: r.cashflow.cfi,                                   "header"),
    ("",                                    None,                                                       "spacer"),
    ("Cash from Financing Activities",      None,                                                       "section"),
    ("+ Dividends Paid",                    lambda r: -r.cashflow.dividends_paid,                       "line"),
    ("+ Cash from (Repay) Debt",            lambda r: r.cashflow.debt_issued - r.cashflow.debt_repaid,  "line"),
    ("    + Debt Issued",                   lambda r: r.cashflow.debt_issued,                            "line"),
    ("    + Debt Repaid",                   lambda r: -r.cashflow.debt_repaid,                          "line"),
    ("Cash from Financing Activities",      lambda r: r.cashflow.cff,                                   "header"),
    ("",                                    None,                                                       "spacer"),
    ("Net Changes in Cash",                 lambda r: r.cashflow.net_change_cash,                       "header"),
    ("",                                    None,                                                       "spacer"),
    ("Reference Items",                     None,                                                       "section"),
    ("EBITDA",                              lambda r: r.income.ebit + r.informative.da_12m,             "line"),
    ("Free Cash Flow (CFO - CapEx)",        lambda r: r.cashflow.cfo - r.cashflow.capex_net,            "subtotal"),
]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

def _safe(getter, parsed):
    try:
        v = getter(parsed)
        return float(v) if v is not None else None
    except Exception:
        return None


def _build_panel_with_view(
    series,
    rows_def: list,
    annual_only: bool,
    fx_rate_usdmxn: float,
    max_periods: Optional[int],
):
    """Builder generico (rows_def es estatico)."""
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]
    if not snaps:
        labels = [l for l, _, _ in rows_def]
        return pd.DataFrame(index=labels), [k for _, _, k in rows_def]

    cols_data = {}
    kinds = [k for _, _, k in rows_def]
    labels = [l for l, _, _ in rows_def]

    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)
        col_vals = []
        for label, getter, kind in rows_def:
            if kind in ("spacer", "section") or getter is None:
                col_vals.append(None)
                continue
            raw = _safe(getter, s.parsed)
            if raw is None:
                col_vals.append(None)
            elif kind == "ratio":
                col_vals.append(raw)
            elif kind == "raw":
                col_vals.append(raw)  # ya es valor final (no MDP)
            else:
                col_vals.append((raw * fx) / 1_000_000)
        cols_data[s.label] = col_vals

    return pd.DataFrame(cols_data, index=labels), kinds


def _derive_cf_pure_quarter(series, max_periods=None):
    """Genera snapshots con CF derivado (Q acum - Q-1 acum del mismo año).

    Q1: acum_Q1 (ya es solo Q1)
    Q2: acum_Q2 - acum_Q1
    Q3: acum_Q3 - acum_Q2
    Q4: acum_Q4 - acum_Q3

    Retorna lista de (snapshot, derived_cashflow_dict).
    """
    derived = []
    snaps = series.snapshots
    by_year_q = {}
    for s in snaps:
        by_year_q.setdefault(s.year, {})[s.quarter] = s

    if max_periods:
        snaps = snaps[-max_periods:]

    for s in snaps:
        # Buscar el trimestre anterior del mismo año
        prev_q_map = {"2": "1", "3": "2", "4": "3", "4D": "3"}
        prev_q = prev_q_map.get(s.quarter)
        cf_curr = s.parsed.cashflow

        if prev_q is None or s.year not in by_year_q or prev_q not in by_year_q[s.year]:
            # No hay anterior -> usar acumulado tal cual (Q1 o sin previo)
            derived.append((s, cf_curr))
            continue

        prev_cf = by_year_q[s.year][prev_q].parsed.cashflow
        # Crear un dict-like con valores derivados
        from types import SimpleNamespace
        derived_cf = SimpleNamespace(
            cfo=cf_curr.cfo - prev_cf.cfo,
            capex_ppe=cf_curr.capex_ppe - prev_cf.capex_ppe,
            capex_intangibles=cf_curr.capex_intangibles - prev_cf.capex_intangibles,
            sales_of_ppe=cf_curr.sales_of_ppe - prev_cf.sales_of_ppe,
            acquisitions=cf_curr.acquisitions - prev_cf.acquisitions,
            cfi=cf_curr.cfi - prev_cf.cfi,
            debt_issued=cf_curr.debt_issued - prev_cf.debt_issued,
            debt_repaid=cf_curr.debt_repaid - prev_cf.debt_repaid,
            dividends_paid=cf_curr.dividends_paid - prev_cf.dividends_paid,
            cff=cf_curr.cff - prev_cf.cff,
            net_change_cash=cf_curr.net_change_cash - prev_cf.net_change_cash,
            capex_gross=cf_curr.capex_gross - prev_cf.capex_gross,
            capex_net=cf_curr.capex_net - prev_cf.capex_net,
        )
        derived.append((s, derived_cf))
    return derived


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------

def build_income_adjusted_panel(series, annual_only=False,
                                  fx_rate_usdmxn=19.5, max_periods=None):
    """Income Statement estilo Bloomberg Adjusted.

    Si annual_only=True usa income (acumulado del Q4 = full year).
    Si annual_only=False usa income_quarter (3 meses puros).
    """
    rows_def = _income_adjusted_lines(use_quarter_data=not annual_only)
    return _build_panel_with_view(series, rows_def, annual_only,
                                    fx_rate_usdmxn, max_periods)


def build_bs_standardized_panel(series, annual_only=False,
                                  fx_rate_usdmxn=19.5, max_periods=None):
    """Balance Sheet estilo Bloomberg Standardized."""
    return _build_panel_with_view(series, BS_STANDARDIZED_LINES, annual_only,
                                    fx_rate_usdmxn, max_periods)


def build_cf_standardized_panel(series, annual_only=False,
                                  fx_rate_usdmxn=19.5, max_periods=None):
    """Cash Flow estilo Bloomberg Standardized.

    Si annual_only=True: usa CF acumulado (Q4 = full year) directo.
    Si annual_only=False: deriva CF puro trimestral (Q acum - Q-1 acum).
    """
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]
    if not snaps:
        labels = [l for l, _, _ in CF_STANDARDIZED_LINES]
        return pd.DataFrame(index=labels), [k for _, _, k in CF_STANDARDIZED_LINES]

    if annual_only:
        return _build_panel_with_view(series, CF_STANDARDIZED_LINES,
                                        annual_only, fx_rate_usdmxn, max_periods)

    # Vista trimestral: derivar valores
    derived = _derive_cf_pure_quarter(series, max_periods)
    cols_data = {}
    kinds = [k for _, _, k in CF_STANDARDIZED_LINES]
    labels = [l for l, _, _ in CF_STANDARDIZED_LINES]

    for snap, derived_cf in derived:
        fx = _detect_fx_mult(snap, fx_rate_usdmxn)
        # Construir parser-like con el cashflow derivado pero income_quarter para income
        from types import SimpleNamespace
        # Necesitamos: r.income.net_income (usa el quarter), r.informative.da_12m,
        # r.cashflow.* (usar derived)
        proxy = SimpleNamespace(
            income=snap.parsed.income_quarter or snap.parsed.income,
            informative=snap.parsed.informative,
            cashflow=derived_cf,
            balance=snap.parsed.balance,
        )
        col_vals = []
        for label, getter, kind in CF_STANDARDIZED_LINES:
            if kind in ("spacer", "section") or getter is None:
                col_vals.append(None)
                continue
            raw = _safe(getter, proxy)
            if raw is None:
                col_vals.append(None)
            elif kind in ("ratio", "raw"):
                col_vals.append(raw)
            else:
                col_vals.append((raw * fx) / 1_000_000)
        cols_data[snap.label] = col_vals

    return pd.DataFrame(cols_data, index=labels), kinds
