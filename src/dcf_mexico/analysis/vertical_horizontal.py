"""
Analisis Vertical y Horizontal de Estados Financieros con detección
automática de red flags y mejoras.

ANALISIS VERTICAL: cada linea como % de un total
- Income Statement: % de Revenue
- Balance Sheet: % de Total Assets
- Cash Flow: % de Revenue (o de CFO segun categoria)

ANALISIS HORIZONTAL: cambios YoY o periodo a periodo
- Cambio absoluto (en MDP)
- Cambio % (vs periodo prior)
- Significancia (alta/media/baja basada en magnitud)

DETECCION AUTOMATICA:
- Red flags 🔴: cambios negativos significativos
- Improvements 🟢: cambios positivos significativos
- Watch 🟡: cambios moderados que requieren monitoreo

Uso:
    from src.dcf_mexico.analysis import (
        vertical_income, vertical_balance, vertical_cashflow,
        horizontal_analysis, detect_changes,
    )
    v_inc = vertical_income(curr_snap, fx_mult=1.0)
    h = horizontal_analysis(curr_snap, prior_snap)
    flags = detect_changes(curr_snap, prior_snap)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Tuple
import pandas as pd


# ============================================================================
# Tipos
# ============================================================================

class Significance(Enum):
    HIGH = "🔴 ALTA"
    MEDIUM = "🟡 MEDIA"
    LOW = "🟢 BAJA"


class Direction(Enum):
    IMPROVEMENT = "🟢 MEJORA"
    DETERIORATION = "🔴 DETERIORO"
    NEUTRAL = "⚪ NEUTRAL"
    WATCH = "🟡 MONITOREAR"


@dataclass
class FinancialChange:
    """Un cambio detectado entre 2 periodos."""
    metric: str
    category: str             # Profitability/Liquidity/Leverage/Efficiency/Quality/Growth
    current: float
    prior: float
    change_abs: float
    change_pct: float
    unit: str                 # %, MDP, x, days
    significance: Significance
    direction: Direction
    risk_flag: bool           # True si es red flag
    is_improvement: bool      # True si es mejora
    narrative: str            # explicación legible
    interpretation: str       # qué significa


# ============================================================================
# ANALISIS VERTICAL
# ============================================================================

def vertical_income(snap, fx_mult: float = 1.0) -> pd.DataFrame:
    """Income Statement como % de Revenue.

    Cada línea muestra: valor MDP, % de Revenue.
    """
    inc = snap.parsed.income
    inf = snap.parsed.informative
    rev = (inc.revenue or 0) * fx_mult / 1e6
    if rev <= 0:
        return pd.DataFrame()

    da = (inf.da_12m or 0) * fx_mult / 1e6
    ebitda = (inc.ebit or 0) * fx_mult / 1e6 + da

    items = [
        ("Revenue",                          inc.revenue),
        ("(-) COGS",                         -inc.cost_of_sales if inc.cost_of_sales else 0),
        ("Gross Profit",                     inc.gross_profit),
        ("(-) Selling Expenses",             -inc.selling_expenses if inc.selling_expenses else 0),
        ("(-) G&A Expenses",                 -inc.ga_expenses if inc.ga_expenses else 0),
        ("(+) Other Operating Income",       inc.other_operating_income),
        ("(-) Other Operating Expense",      -inc.other_operating_expense if inc.other_operating_expense else 0),
        ("EBIT",                             inc.ebit),
        ("(+) D&A (memo)",                   inf.da_12m),
        ("EBITDA (memo)",                    None),  # placeholder
        ("(+) Interest Income",              inc.interest_income),
        ("(-) Interest Expense",             -inc.interest_expense if inc.interest_expense else 0),
        ("(+) FX Result",                    inc.fx_result),
        ("(+) Associates Result",            inc.associates_result),
        ("Pretax Income",                    inc.pretax_income),
        ("(-) Tax Expense",                  -inc.tax_expense if inc.tax_expense else 0),
        ("Net Income",                       inc.net_income),
        ("(-) Minority Interest",            -inc.net_income_minority if inc.net_income_minority else 0),
        ("Net Income Controlling",           inc.net_income_controlling),
    ]

    rows = []
    for label, val in items:
        if val is None:  # EBITDA memo
            v_mdp = ebitda
        else:
            v_mdp = (val or 0) * fx_mult / 1e6
        pct = v_mdp / rev * 100 if rev > 0 else 0
        rows.append({
            "Concepto": label,
            "MDP": round(v_mdp, 1),
            "% Revenue": f"{pct:+.2f}%",
        })
    return pd.DataFrame(rows)


def vertical_balance(snap, fx_mult: float = 1.0) -> pd.DataFrame:
    """Balance Sheet como % de Total Assets."""
    bs = snap.parsed.balance
    ta = (bs.total_assets or 0) * fx_mult / 1e6
    if ta <= 0:
        return pd.DataFrame()

    items = [
        # ACTIVOS
        ("=== ACTIVOS CIRCULANTES ===", None),
        ("Cash & Equivalents",           bs.cash),
        ("Accounts Receivable",          bs.accounts_receivable),
        ("Inventories",                  bs.inventories),
        ("Other Current Assets",         bs.other_current_assets),
        ("TOTAL CURRENT ASSETS",         bs.total_current_assets),
        ("=== ACTIVOS NO CIRCULANTES ===", None),
        ("PPE Net",                      bs.ppe),
        ("Intangibles",                  bs.intangibles),
        ("Goodwill",                     bs.goodwill),
        ("Right-of-Use Assets (IFRS 16)",bs.right_of_use_assets),
        ("Investments in Associates",    bs.investments_in_associates),
        ("Deferred Tax Assets",          bs.deferred_tax_assets),
        ("Other Non-Current Assets",     bs.other_non_current_assets),
        ("TOTAL NON-CURRENT ASSETS",     bs.total_non_current_assets),
        ("TOTAL ASSETS",                 bs.total_assets),
        # PASIVOS
        ("=== PASIVOS CIRCULANTES ===",  None),
        ("Short-Term Debt",              bs.short_term_debt),
        ("Short-Term Lease (IFRS 16)",   bs.short_term_lease),
        ("Accounts Payable",             bs.accounts_payable),
        ("Other Current Liabilities",    bs.other_current_liabilities),
        ("TOTAL CURRENT LIABILITIES",    bs.total_current_liabilities),
        ("=== PASIVOS NO CIRCULANTES ===", None),
        ("Long-Term Debt",               bs.long_term_debt),
        ("Long-Term Lease (IFRS 16)",    bs.long_term_lease),
        ("Deferred Tax Liabilities",     bs.deferred_tax_liabilities),
        ("Other Non-Current Liabilities",bs.other_non_current_liabilities),
        ("TOTAL NON-CURRENT LIABILITIES",bs.total_non_current_liabilities),
        ("TOTAL LIABILITIES",            bs.total_liabilities),
        # CAPITAL
        ("=== CAPITAL ===",              None),
        ("Equity Controlling",           bs.equity_controlling),
        ("Minority Interest",            bs.minority_interest),
        ("TOTAL EQUITY",                 bs.total_equity),
        ("=== TOTAL PASIVOS + CAPITAL ===", None),
        ("Check (= TOTAL ASSETS)",       (bs.total_liabilities or 0) + (bs.total_equity or 0)),
    ]

    rows = []
    for label, val in items:
        if val is None:
            rows.append({"Concepto": label, "MDP": "—", "% Total Assets": "—"})
            continue
        v_mdp = (val or 0) * fx_mult / 1e6
        pct = v_mdp / ta * 100 if ta > 0 else 0
        rows.append({
            "Concepto": label,
            "MDP": round(v_mdp, 1),
            "% Total Assets": f"{pct:.2f}%",
        })
    return pd.DataFrame(rows)


def vertical_cashflow(snap, fx_mult: float = 1.0) -> pd.DataFrame:
    """Cash Flow Statement con cada línea como % de Revenue."""
    cf = snap.parsed.cashflow
    inc = snap.parsed.income
    rev = (inc.revenue or 0) * fx_mult / 1e6
    if rev <= 0:
        return pd.DataFrame()

    items = [
        ("=== OPERATING ===", None),
        ("Cash from Operations (CFO)",  cf.cfo),
        ("(-) CapEx PPE",                -cf.capex_ppe if cf.capex_ppe else 0),
        ("(-) CapEx Intangibles",        -cf.capex_intangibles if cf.capex_intangibles else 0),
        ("Free Cash Flow (CFO - CapEx)", (cf.cfo or 0) - (cf.capex_ppe or 0) - (cf.capex_intangibles or 0)),
        ("=== INVESTING ===", None),
        ("(+) Sales of PPE",             cf.sales_of_ppe),
        ("(-) Acquisitions",             -cf.cash_for_obtain_control if cf.cash_for_obtain_control else 0),
        ("(+) Loss of control",          cf.cash_from_loss_of_control),
        ("Cash from Investing (CFI)",    cf.cfi),
        ("=== FINANCING ===", None),
        ("(+) Debt Issued",              cf.debt_issued),
        ("(-) Debt Repaid",              -cf.debt_repaid if cf.debt_repaid else 0),
        ("(-) Dividends Paid",           -cf.dividends_paid if cf.dividends_paid else 0),
        ("(-) Lease Payments",           -cf.lease_payments_cf if cf.lease_payments_cf else 0),
        ("Cash from Financing (CFF)",    cf.cff),
        ("=== SUMMARY ===", None),
        ("Net Change in Cash",           cf.net_change_cash),
        ("FX Effect on Cash",            cf.fx_effect_on_cash),
    ]

    rows = []
    for label, val in items:
        if val is None:
            rows.append({"Concepto": label, "MDP": "—", "% Revenue": "—"})
            continue
        v_mdp = (val or 0) * fx_mult / 1e6
        pct = v_mdp / rev * 100 if rev > 0 else 0
        rows.append({
            "Concepto": label,
            "MDP": round(v_mdp, 1),
            "% Revenue": f"{pct:+.2f}%",
        })
    return pd.DataFrame(rows)


# ============================================================================
# ANALISIS HORIZONTAL
# ============================================================================

def horizontal_income(curr_snap, prior_snap, fx_mult: float = 1.0) -> pd.DataFrame:
    """Cambios YoY en Income Statement."""
    if not prior_snap:
        return pd.DataFrame()

    c_inc, p_inc = curr_snap.parsed.income, prior_snap.parsed.income
    c_inf, p_inf = curr_snap.parsed.informative, prior_snap.parsed.informative

    items = [
        ("Revenue",                  c_inc.revenue,            p_inc.revenue),
        ("Cost of Sales",            c_inc.cost_of_sales,      p_inc.cost_of_sales),
        ("Gross Profit",             c_inc.gross_profit,       p_inc.gross_profit),
        ("Operating Expenses",       c_inc.operating_expenses, p_inc.operating_expenses),
        ("EBIT",                     c_inc.ebit,               p_inc.ebit),
        ("D&A (TTM)",                c_inf.da_12m,             p_inf.da_12m),
        ("EBITDA",                   (c_inc.ebit or 0) + (c_inf.da_12m or 0),
                                      (p_inc.ebit or 0) + (p_inf.da_12m or 0)),
        ("Interest Expense",         c_inc.interest_expense,   p_inc.interest_expense),
        ("Pretax Income",            c_inc.pretax_income,      p_inc.pretax_income),
        ("Tax Expense",              c_inc.tax_expense,        p_inc.tax_expense),
        ("Net Income",               c_inc.net_income,         p_inc.net_income),
        ("NI Controlling",           c_inc.net_income_controlling, p_inc.net_income_controlling),
    ]
    return _build_horizontal_df(items, fx_mult)


def horizontal_balance(curr_snap, prior_snap, fx_mult: float = 1.0) -> pd.DataFrame:
    """Cambios YoY en Balance Sheet."""
    if not prior_snap:
        return pd.DataFrame()
    c_bs, p_bs = curr_snap.parsed.balance, prior_snap.parsed.balance

    items = [
        ("Cash",                          c_bs.cash, p_bs.cash),
        ("Accounts Receivable",           c_bs.accounts_receivable, p_bs.accounts_receivable),
        ("Inventories",                   c_bs.inventories, p_bs.inventories),
        ("Total Current Assets",          c_bs.total_current_assets, p_bs.total_current_assets),
        ("PPE Net",                       c_bs.ppe, p_bs.ppe),
        ("Intangibles + Goodwill",        (c_bs.intangibles or 0) + (c_bs.goodwill or 0),
                                          (p_bs.intangibles or 0) + (p_bs.goodwill or 0)),
        ("Total Assets",                  c_bs.total_assets, p_bs.total_assets),
        ("Accounts Payable",              c_bs.accounts_payable, p_bs.accounts_payable),
        ("Total Current Liabilities",     c_bs.total_current_liabilities, p_bs.total_current_liabilities),
        ("Long-Term Debt",                c_bs.long_term_debt, p_bs.long_term_debt),
        ("Total Debt + Leases",           c_bs.total_debt_with_leases, p_bs.total_debt_with_leases),
        ("Total Liabilities",             c_bs.total_liabilities, p_bs.total_liabilities),
        ("Equity Controlling",            c_bs.equity_controlling, p_bs.equity_controlling),
        ("Total Equity",                  c_bs.total_equity, p_bs.total_equity),
    ]
    return _build_horizontal_df(items, fx_mult)


def horizontal_cashflow(curr_snap, prior_snap, fx_mult: float = 1.0) -> pd.DataFrame:
    """Cambios YoY en Cash Flow."""
    if not prior_snap:
        return pd.DataFrame()
    c_cf, p_cf = curr_snap.parsed.cashflow, prior_snap.parsed.cashflow

    fcf_c = (c_cf.cfo or 0) - (c_cf.capex_ppe or 0)
    fcf_p = (p_cf.cfo or 0) - (p_cf.capex_ppe or 0)

    items = [
        ("Cash from Operations",          c_cf.cfo, p_cf.cfo),
        ("CapEx PPE",                     c_cf.capex_ppe, p_cf.capex_ppe),
        ("Free Cash Flow",                fcf_c, fcf_p),
        ("Cash from Investing",           c_cf.cfi, p_cf.cfi),
        ("Debt Issued",                   c_cf.debt_issued, p_cf.debt_issued),
        ("Debt Repaid",                   c_cf.debt_repaid, p_cf.debt_repaid),
        ("Dividends Paid",                c_cf.dividends_paid, p_cf.dividends_paid),
        ("Cash from Financing",           c_cf.cff, p_cf.cff),
        ("Net Change in Cash",            c_cf.net_change_cash, p_cf.net_change_cash),
    ]
    return _build_horizontal_df(items, fx_mult)


def _build_horizontal_df(items, fx_mult: float) -> pd.DataFrame:
    rows = []
    for label, c_val, p_val in items:
        c = (c_val or 0) * fx_mult / 1e6
        p = (p_val or 0) * fx_mult / 1e6
        delta = c - p
        pct = (delta / abs(p) * 100) if abs(p) > 0.01 else 0

        # Direction emoji
        if abs(pct) < 1:
            sign = "⚪"
        elif pct > 0:
            sign = "🟢" if pct < 50 else "🚀"
        else:
            sign = "🔴" if pct < -10 else "🟡"

        rows.append({
            "Concepto": label,
            "Actual (MDP)": round(c, 1),
            "Prior (MDP)": round(p, 1),
            "Δ MDP": round(delta, 1),
            "Δ % YoY": f"{sign} {pct:+.1f}%",
        })
    return pd.DataFrame(rows)


# ============================================================================
# DETECCION DE RED FLAGS Y MEJORAS
# ============================================================================

def detect_changes(curr_snap, prior_snap, fx_mult: float = 1.0) -> List[FinancialChange]:
    """Detecta automáticamente cambios significativos.

    Reglas Damodaran/Buffett-style para identificar:
    - Red flags (deterioros importantes)
    - Improvements (mejoras estructurales)
    - Watch items (cambios moderados)
    """
    if not prior_snap:
        return []

    c_inc, p_inc = curr_snap.parsed.income, prior_snap.parsed.income
    c_bs, p_bs   = curr_snap.parsed.balance, prior_snap.parsed.balance
    c_cf, p_cf   = curr_snap.parsed.cashflow, prior_snap.parsed.cashflow
    c_inf, p_inf = curr_snap.parsed.informative, prior_snap.parsed.informative

    changes = []

    def add(metric, category, c, p, unit, narrative, interpretation,
            direction, risk_flag=False, sig=None):
        if abs(p) < 0.01 and abs(c) < 0.01:
            return
        delta = c - p
        pct = (delta / abs(p) * 100) if abs(p) > 0.01 else 0
        if sig is None:
            abs_pct = abs(pct)
            sig = (Significance.HIGH if abs_pct > 25 else
                   Significance.MEDIUM if abs_pct > 10 else
                   Significance.LOW)
        changes.append(FinancialChange(
            metric=metric, category=category,
            current=round(c, 4), prior=round(p, 4),
            change_abs=round(delta, 4), change_pct=round(pct, 2),
            unit=unit, significance=sig,
            direction=direction, risk_flag=risk_flag,
            is_improvement=(direction == Direction.IMPROVEMENT),
            narrative=narrative, interpretation=interpretation,
        ))

    # ===== PROFITABILITY MARGINS =====
    if c_inc.revenue and p_inc.revenue:
        c_gm = (c_inc.gross_profit or 0) / c_inc.revenue * 100
        p_gm = (p_inc.gross_profit or 0) / p_inc.revenue * 100
        delta_bps = (c_gm - p_gm) * 100
        if abs(delta_bps) > 100:
            risk = delta_bps < -200
            improvement = delta_bps > 200
            add("Gross Margin", "Profitability", c_gm, p_gm, "%",
                f"Margen bruto {'mejora' if delta_bps > 0 else 'cae'} "
                f"{abs(delta_bps):.0f}bps (de {p_gm:.1f}% a {c_gm:.1f}%)",
                ("Pricing power + cost discipline" if delta_bps > 0
                 else "Pricing pressure o cost inflation - investigar drivers"),
                Direction.IMPROVEMENT if delta_bps > 0 else Direction.DETERIORATION,
                risk_flag=risk,
                sig=Significance.HIGH if abs(delta_bps) > 300 else Significance.MEDIUM)

        c_om = (c_inc.ebit or 0) / c_inc.revenue * 100
        p_om = (p_inc.ebit or 0) / p_inc.revenue * 100
        delta_bps = (c_om - p_om) * 100
        if abs(delta_bps) > 100:
            risk = delta_bps < -200
            add("Operating Margin", "Profitability", c_om, p_om, "%",
                f"Margen operativo {'mejora' if delta_bps > 0 else 'cae'} "
                f"{abs(delta_bps):.0f}bps (de {p_om:.1f}% a {c_om:.1f}%)",
                ("Operating leverage positivo" if delta_bps > 0
                 else "Operating deleveraging - presión en margenes"),
                Direction.IMPROVEMENT if delta_bps > 0 else Direction.DETERIORATION,
                risk_flag=risk,
                sig=Significance.HIGH if abs(delta_bps) > 300 else Significance.MEDIUM)

        c_nm = (c_inc.net_income or 0) / c_inc.revenue * 100
        p_nm = (p_inc.net_income or 0) / p_inc.revenue * 100
        delta_bps = (c_nm - p_nm) * 100
        if abs(delta_bps) > 100:
            add("Net Margin", "Profitability", c_nm, p_nm, "%",
                f"Margen neto {'mejora' if delta_bps > 0 else 'cae'} "
                f"{abs(delta_bps):.0f}bps",
                "",
                Direction.IMPROVEMENT if delta_bps > 0 else Direction.DETERIORATION)

    # ===== REVENUE GROWTH =====
    if c_inc.revenue and p_inc.revenue:
        rev_growth = (c_inc.revenue - p_inc.revenue) / p_inc.revenue * 100
        if abs(rev_growth) > 1:
            improvement = rev_growth > 5
            risk = rev_growth < -5
            add("Revenue Growth YoY", "Growth",
                c_inc.revenue / 1e6, p_inc.revenue / 1e6, "MDP",
                f"Revenue {'crece' if rev_growth > 0 else 'cae'} {abs(rev_growth):.1f}% YoY",
                ("Demanda creciente / share gains / pricing"
                 if rev_growth > 5 else
                 "Contracción - investigar volumen vs precio"
                 if rev_growth < -3 else
                 "Crecimiento moderado / estable"),
                Direction.IMPROVEMENT if rev_growth > 5 else
                Direction.DETERIORATION if rev_growth < -3 else
                Direction.NEUTRAL,
                risk_flag=risk)

    # ===== WORKING CAPITAL EFFICIENCY =====
    cogs_curr = c_inc.cost_of_sales or 0
    cogs_prior = p_inc.cost_of_sales or 0

    if cogs_curr > 0 and (c_bs.inventories or 0) > 0:
        c_dio = (c_bs.inventories or 0) / cogs_curr * 365
        p_dio = (p_bs.inventories or 0) / cogs_prior * 365 if cogs_prior > 0 else c_dio
        delta_dio = c_dio - p_dio
        if abs(delta_dio) > 10:
            risk = delta_dio > 30
            add("Days Inventory (DIO)", "Efficiency", c_dio, p_dio, "days",
                f"DIO {'sube' if delta_dio > 0 else 'baja'} {abs(delta_dio):.0f} días "
                f"(de {p_dio:.0f} a {c_dio:.0f})",
                ("Acumulación de inventario - demanda débil o overstock"
                 if delta_dio > 30 else
                 "Mejor rotación - eficiencia operativa"
                 if delta_dio < -30 else
                 "Cambio moderado en niveles de inventario"),
                Direction.DETERIORATION if delta_dio > 0 else Direction.IMPROVEMENT,
                risk_flag=risk)

    if c_inc.revenue and (c_bs.accounts_receivable or 0) > 0:
        c_dso = (c_bs.accounts_receivable or 0) / c_inc.revenue * 365
        p_dso = ((p_bs.accounts_receivable or 0) / p_inc.revenue * 365
                 if p_inc.revenue > 0 else c_dso)
        delta_dso = c_dso - p_dso
        if abs(delta_dso) > 10:
            risk = delta_dso > 20
            add("Days Sales Outstanding (DSO)", "Efficiency",
                c_dso, p_dso, "days",
                f"DSO {'sube' if delta_dso > 0 else 'baja'} {abs(delta_dso):.0f} días "
                f"(de {p_dso:.0f} a {c_dso:.0f})",
                ("Cobranza más lenta - posible deterioro de clientes o "
                 "cambio de mix B2B"
                 if delta_dso > 20 else
                 "Mejor cobranza - disciplina credit-collections"),
                Direction.DETERIORATION if delta_dso > 0 else Direction.IMPROVEMENT,
                risk_flag=risk)

    # ===== LEVERAGE =====
    c_debt = c_bs.total_debt_with_leases
    p_debt = p_bs.total_debt_with_leases
    if c_debt and p_debt:
        debt_growth = (c_debt - p_debt) / p_debt * 100
        if abs(debt_growth) > 10:
            risk = debt_growth > 30
            add("Total Debt (incl leases)", "Leverage",
                c_debt / 1e6, p_debt / 1e6, "MDP",
                f"Deuda total {'crece' if debt_growth > 0 else 'cae'} "
                f"{abs(debt_growth):.0f}% YoY",
                ("Re-apalancamiento agresivo - ¿para crecimiento o stress?"
                 if debt_growth > 30 else
                 "Deleveraging - mejora capacidad de pago"
                 if debt_growth < -10 else
                 "Cambio moderado en estructura"),
                Direction.DETERIORATION if debt_growth > 30 else
                Direction.IMPROVEMENT if debt_growth < -10 else
                Direction.NEUTRAL,
                risk_flag=risk)

    # Net Debt / EBITDA
    c_ebitda = (c_inc.ebit or 0) + (c_inf.da_12m or 0)
    p_ebitda = (p_inc.ebit or 0) + (p_inf.da_12m or 0)
    c_net_debt = (c_bs.total_debt_with_leases or 0) - (c_bs.cash or 0)
    p_net_debt = (p_bs.total_debt_with_leases or 0) - (p_bs.cash or 0)
    if c_ebitda > 0 and p_ebitda > 0:
        c_nd_eb = c_net_debt / c_ebitda
        p_nd_eb = p_net_debt / p_ebitda
        delta = c_nd_eb - p_nd_eb
        if abs(delta) > 0.3:
            risk = delta > 0.5 and c_nd_eb > 3
            add("Net Debt / EBITDA", "Leverage", c_nd_eb, p_nd_eb, "x",
                f"ND/EBITDA {'sube' if delta > 0 else 'baja'} "
                f"{abs(delta):.2f}x (de {p_nd_eb:.2f}x a {c_nd_eb:.2f}x)",
                ("Apalancamiento creciente - watch coverage" if delta > 0
                 else "Empresa fortaleciendo balance"),
                Direction.DETERIORATION if delta > 0 else Direction.IMPROVEMENT,
                risk_flag=risk)

    # Interest Coverage
    c_int = abs(c_inc.interest_expense or 0)
    p_int = abs(p_inc.interest_expense or 0)
    if c_int > 0 and p_int > 0 and c_inc.ebit and p_inc.ebit:
        c_cov = c_inc.ebit / c_int
        p_cov = p_inc.ebit / p_int
        delta = c_cov - p_cov
        if abs(delta) > 1:
            risk = c_cov < 2.5
            add("Interest Coverage (EBIT)", "Leverage", c_cov, p_cov, "x",
                f"Coverage {'mejora' if delta > 0 else 'cae'} de {p_cov:.1f}x a {c_cov:.1f}x",
                ("Investment grade comfort" if c_cov > 5
                 else "Watch - coverage justo"
                 if c_cov < 3 else "Ratio adequate"),
                Direction.IMPROVEMENT if delta > 0 else Direction.DETERIORATION,
                risk_flag=risk)

    # ===== CASH FLOW QUALITY =====
    c_cfo = c_cf.cfo or 0
    p_cfo = p_cf.cfo or 0
    c_ni = c_inc.net_income or 0
    p_ni = p_inc.net_income or 0

    if c_ni > 0 and p_ni > 0:
        c_q = c_cfo / c_ni
        p_q = p_cfo / p_ni
        delta = c_q - p_q
        if abs(delta) > 0.2:
            risk = c_q < 0.5
            add("CFO / Net Income (Quality)", "Quality",
                c_q, p_q, "x",
                f"Calidad de utilidad {'mejora' if delta > 0 else 'cae'} "
                f"de {p_q:.2f}x a {c_q:.2f}x",
                ("Excelente: utilidad respaldada por cash"
                 if c_q > 1.2 else
                 "RED FLAG: utilidad contable >> cash, accruals altos"
                 if c_q < 0.5 else
                 "Calidad razonable"),
                Direction.IMPROVEMENT if delta > 0 else Direction.DETERIORATION,
                risk_flag=risk)

    # FCF
    c_fcf = c_cfo - (c_cf.capex_ppe or 0)
    p_fcf = p_cfo - (p_cf.capex_ppe or 0)
    if abs(p_fcf) > 0.01:
        fcf_growth = (c_fcf - p_fcf) / abs(p_fcf) * 100
        if abs(fcf_growth) > 15:
            add("Free Cash Flow", "Quality",
                c_fcf / 1e6, p_fcf / 1e6, "MDP",
                f"FCF {'crece' if fcf_growth > 0 else 'cae'} "
                f"{abs(fcf_growth):.0f}% YoY",
                ("Mejor generacion de cash libre" if fcf_growth > 0
                 else "Deterioro en cash generation - investigar drivers"),
                Direction.IMPROVEMENT if fcf_growth > 0 else Direction.DETERIORATION,
                risk_flag=(fcf_growth < -30))

    # ===== ROIC =====
    c_inv_cap = (c_bs.equity_controlling or 0) + (c_bs.total_debt_with_leases or 0) - (c_bs.cash or 0)
    p_inv_cap = (p_bs.equity_controlling or 0) + (p_bs.total_debt_with_leases or 0) - (p_bs.cash or 0)
    if c_inv_cap > 0 and p_inv_cap > 0 and c_inc.ebit and p_inc.ebit:
        c_tax = c_inc.tax_expense / c_inc.pretax_income if c_inc.pretax_income > 0 else 0.30
        p_tax = p_inc.tax_expense / p_inc.pretax_income if p_inc.pretax_income > 0 else 0.30
        c_roic = (c_inc.ebit * (1 - c_tax)) / c_inv_cap * 100
        p_roic = (p_inc.ebit * (1 - p_tax)) / p_inv_cap * 100
        delta = c_roic - p_roic
        if abs(delta) > 1:
            improvement = delta > 2
            add("ROIC", "Profitability", c_roic, p_roic, "%",
                f"ROIC {'mejora' if delta > 0 else 'cae'} {abs(delta):.1f}pp "
                f"(de {p_roic:.1f}% a {c_roic:.1f}%)",
                ("Capital allocation efectivo - crea valor"
                 if c_roic > 12 and improvement else
                 "Retornos cayendo - investigar capital allocation"
                 if delta < -2 else
                 "Cambio menor"),
                Direction.IMPROVEMENT if delta > 0 else Direction.DETERIORATION,
                risk_flag=(delta < -3))

    return changes


def categorize_changes(changes: List[FinancialChange]) -> Dict[str, List[FinancialChange]]:
    """Agrupa changes por dirección + significancia."""
    return {
        "red_flags":     [c for c in changes if c.risk_flag],
        "improvements":  [c for c in changes if c.is_improvement and c.significance != Significance.LOW],
        "watch":         [c for c in changes if c.direction == Direction.WATCH],
        "all_high_sig":  [c for c in changes if c.significance == Significance.HIGH],
    }


def changes_to_table(changes: List[FinancialChange]) -> pd.DataFrame:
    """Convierte la lista a DataFrame para display."""
    if not changes:
        return pd.DataFrame()
    rows = []
    for c in changes:
        rows.append({
            "Métrica":          c.metric,
            "Categoría":        c.category,
            "Actual":           f"{c.current:.2f} {c.unit}" if c.unit in ("%", "x") else f"{c.current:,.1f}",
            "Prior":            f"{c.prior:.2f} {c.unit}" if c.unit in ("%", "x") else f"{c.prior:,.1f}",
            "Δ %":              f"{c.change_pct:+.1f}%",
            "Significancia":    c.significance.value,
            "Dirección":        c.direction.value,
            "Narrativa":        c.narrative,
            "Interpretación":   c.interpretation,
        })
    return pd.DataFrame(rows)
