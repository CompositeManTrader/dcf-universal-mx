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


# ===========================================================================
# INCOME - Adjusted EXACTO Bloomberg (CUERVO compatible, generico para CNBV)
# ===========================================================================

# Layout: (display_label, key_in_metrics, kind)
# kind:  header (resaltado azul), subtotal (verde), line (normal),
#        sub (line indentada gris claro), ratio (%), ratio_eps (4 dec),
#        string (raw text), section (separador), spacer (vacio)
BLOOMBERG_INCOME_LAYOUT = [
    ("Revenue",                                "revenue",            "header"),
    ("    Growth (YoY)",                       "growth_yoy",         "ratio"),
    ("    + Sales & Services Revenue",         "revenue",            "sub"),
    ("  - Cost of Revenue",                    "cost_of_revenue",    "line"),
    ("    + Cost of Goods & Services",         "cost_of_revenue",    "sub"),
    ("    + Research & Development",           "rd_in_cogs",         "sub"),
    ("Gross Profit",                           "gross_profit",       "subtotal"),
    ("  + Other Operating Income",             "other_op_income",    "line"),
    ("  - Operating Expenses",                 "op_expenses_total",  "line"),
    ("    + Selling, General & Admin",         "sga_total",          "sub"),
    ("    + Selling & Marketing",              "selling_expenses",   "sub"),
    ("    + General & Administrative",         "ga_expenses",        "sub"),
    ("    + Research & Development",           "rd_in_opex",         "sub"),
    ("    + Other Operating Expense",          "other_op_expense",   "sub"),
    ("Operating Income (Loss)",                "ebit",               "header"),
    ("  - Non-Operating (Income) Loss",        "non_op_loss",        "line"),
    ("    + Interest Expense, Net",            "net_interest",       "sub"),
    ("    + Interest Expense",                 "interest_expense",   "sub"),
    ("    - Interest Income",                  "interest_income",    "sub"),
    ("    + Foreign Exch (Gain) Loss",         "fx_loss",            "sub"),
    ("    + (Income) Loss from Affiliates",    "affiliates_loss",    "sub"),
    ("    + Other Non-Op (Income) Loss",       "other_non_op",       "sub"),
    ("Pretax Income (Loss), Adjusted",         "pretax_adjusted",    "subtotal"),
    ("  - Abnormal Losses (Gains)",            "abnormal_losses",    "line"),
    ("    + Disposal of Assets",               "disposal_assets",    "sub"),
    ("    + Asset Write-Down",                 "asset_writedown",    "sub"),
    ("    + Unrealized Investments",           "unrealized_inv",     "sub"),
    ("Pretax Income (Loss), GAAP",             "pretax_gaap",        "subtotal"),
    ("  - Income Tax Expense (Benefit)",       "tax_expense",        "line"),
    ("    + Current Income Tax",               "current_tax",        "sub"),
    ("    + Deferred Income Tax",              "deferred_tax",       "sub"),
    ("Income (Loss) from Cont Ops",            "income_cont_ops",    "subtotal"),
    ("  - Net Extraordinary Losses (Gains)",   "net_xo",             "line"),
    ("    + Discontinued Operations",          "disc_ops",           "sub"),
    ("    + XO & Accounting Changes",          "acc_changes",        "sub"),
    ("Income (Loss) Incl. MI",                 "ni_incl_mi",         "subtotal"),
    ("  - Minority Interest",                  "minority_interest",  "line"),
    ("Net Income, GAAP",                       "net_income_gaap",    "header"),
    ("  - Preferred Dividends",                "preferred_div",      "line"),
    ("  - Other Adjustments",                  "other_adj",          "line"),
    ("Net Income Avail to Common, GAAP",       "ni_common_gaap",     "header"),
    ("",                                       None,                 "spacer"),
    ("Net Income Avail to Common, Adj",        "ni_common_adj",      "header"),
    ("  Net Abnormal Losses (Gains)",          "net_abnormal",       "line"),
    ("  Net Extraordinary Losses (Gains)",     "net_xo_2",           "line"),
    ("",                                       None,                 "spacer"),
    ("Basic Weighted Avg Shares",              "shares_basic",       "bold_line"),
    ("Basic EPS, GAAP",                        "eps_basic_gaap",     "ratio_eps"),
    ("Basic EPS from Cont Ops, GAAP",          "eps_basic_cont",     "ratio_eps"),
    ("Basic EPS from Cont Ops, Adjusted",      "eps_basic_adj",      "ratio_eps"),
    ("",                                       None,                 "spacer"),
    ("Diluted Weighted Avg Shares",            "shares_diluted",     "bold_line"),
    ("Diluted EPS, GAAP",                      "eps_dil_gaap",       "ratio_eps"),
    ("Diluted EPS from Cont Ops, GAAP",        "eps_dil_cont",       "ratio_eps"),
    ("Diluted EPS from Cont Ops, Adjusted",    "eps_dil_adj",        "ratio_eps"),
    ("",                                       None,                 "spacer"),
    ("Reference Items",                        None,                 "section"),
    ("Accounting Standard",                    "accounting_std",     "string"),
    ("EBITDA",                                 "ebitda",             "line"),
    ("EBITDA Margin (T12M)",                   "ebitda_margin_ttm",  "ratio"),
    ("EBITA",                                  "ebita",              "line"),
    ("EBIT",                                   "ebit",               "line"),
    ("Gross Margin",                           "gross_margin",       "ratio"),
    ("Operating Margin",                       "operating_margin",   "ratio"),
    ("Profit Margin",                          "profit_margin",      "ratio"),
    ("Sales per Employee",                     "sales_per_emp",      "line"),
    ("Dividends per Share",                    "dps",                "ratio_eps"),
    ("Total Cash Common Dividends",            "total_cash_div",     "line"),
    ("Export Sales",                           "export_sales",       "line"),
    ("Depreciation Expense",                   "dep_expense",        "line"),
]


def _safe_get(obj, attr, default=0.0):
    v = getattr(obj, attr, default)
    return default if v is None else v


# ===========================================================================
# RECLASSIFICATION RULES: convierte CNBV "As Reported" -> Bloomberg "Adjusted"
# Cada emisora tiene su propio set de reclasificaciones especificas.
# ===========================================================================

def _apply_cuervo_reclass(m: dict, disposal_period: float = 0.0,
                            deferred_tax_period: float = 0.0,
                            current_tax_period: float = 0.0,
                            interest_earned_period: float = 0.0,
                            fx_gain_period: float = 0.0,
                            export_sales_period: float = 0.0) -> dict:
    """Reclasifica metricas CNBV -> formato Bloomberg para CUERVO (BECLE).

    Reglas CUERVO-especificas (verificadas vs Bloomberg Q4 2025):
      1. 'Otros gastos' CNBV -> Bloomberg 'Selling & Marketing'
      2. 'Other Operating Income' = 0 (BB no lo muestra; folda en Other Op Expense)
      3. 'Other Operating Expense' Bloomberg = -Otros_ingresos - Disposal_gain (neto)
      4. 'Interest Expense' Bloomberg = Gastos_financieros + |Ingresos_financieros si<0|
      5. 'Operating Income' Bloomberg = EBIT_CNBV + Disposal_gain
      6. 'Pretax Adjusted' Bloomberg = Pretax_GAAP + Disposal_gain
      7. Tax breakdown: deferred = del periodo (de hoja 800200 derivado);
         current = total_tax - deferred
      8. Net Abnormal Losses (Gains) = Disposal × (1 - effective_tax_rate)
      9. NI Common Adj = NI_GAAP + Net_Abnormal
    """
    selling_cnbv = m.get("selling_expenses", 0) or 0
    ga_cnbv      = m.get("ga_expenses", 0) or 0
    other_inc    = m.get("other_op_income", 0) or 0
    other_exp    = m.get("other_op_expense", 0) or 0
    int_exp_cnbv = m.get("interest_expense", 0) or 0
    int_inc_cnbv = m.get("interest_income", 0) or 0
    ebit_cnbv    = m.get("ebit", 0) or 0
    pretax_gaap  = m.get("pretax_gaap", 0) or 0

    # --- 1: Selling absorbe Otros gastos ---
    selling_bb = selling_cnbv + other_exp                # 481.66 + 2,989.71 = 3,471.37
    sga_bb     = selling_bb + ga_cnbv                     # 3,471.37 + 732.37 = 4,203.74

    # --- 2: Other Op Expense neto = -Otros_ingresos - Disposal_gain ---
    other_op_expense_bb = -other_inc - disposal_period    # -438.20 - 63.27 = -501.47

    op_expenses_total_bb = sga_bb + other_op_expense_bb   # 4,203.74 - 501.47 = 3,702.27

    # --- 4: Operating Income BB = EBIT CNBV + Disposal_gain ---
    ebit_bb = ebit_cnbv + disposal_period                  # 2,349.43 + 63.27 = 2,412.70

    # --- 3a: Interest Expense BB = CNBV gastos_fin + |CNBV ingresos_fin total si negativo| ---
    # Bloomberg sumea TODA la "Otros ingresos financieros" negativa al Interest Expense.
    # Despues separa Interest Income e FX como componentes positivos NUEVOS desde notas.
    # El residual queda en Other Non-Op.
    if int_inc_cnbv < 0:
        int_exp_bb = int_exp_cnbv + abs(int_inc_cnbv)   # 253 + 2,534 = 2,787 ✓
    else:
        int_exp_bb = int_exp_cnbv

    # --- 3b: Interest Income BB = Intereses ganados (notas) ---
    int_inc_bb = interest_earned_period
    net_interest_bb = int_exp_bb - int_inc_bb

    # --- 3c: FX BB = -fx_gain (CNBV positive = utilidad; BB shows negative as gain) ---
    fx_loss_bb = -fx_gain_period

    affiliates  = m.get("affiliates_loss", 0) or 0

    # --- 3d: Other Non-Op = residual para balancear total non_op_loss ---
    # total_non_op_loss = EBIT_CNBV - Pretax_GAAP (constante regardless de disposal reclass)
    ebit_cnbv_orig = m.get("ebit", 0) or 0   # mi parser ya tiene CNBV EBIT
    total_non_op_loss = ebit_cnbv_orig - pretax_gaap
    other_nop_bb = total_non_op_loss - net_interest_bb - fx_loss_bb - affiliates

    non_op_loss_bb = net_interest_bb + fx_loss_bb + affiliates + other_nop_bb

    # --- 5: Pretax Adjusted = Pretax_GAAP + Disposal (porque BB lo saca de Adj) ---
    pretax_adjusted_bb = pretax_gaap + disposal_period    # 1,999.81 + 63.27 = 2,063.08
    abnormal_losses_bb = disposal_period                   # 63.27
    disposal_assets_bb = disposal_period                   # 63.27

    # EBITDA recalc con nuevo EBIT
    da_value = (m.get("ebitda", 0) or 0) - ebit_cnbv      # extraer D&A original
    ebitda_bb = ebit_bb + da_value

    # Margenes recalc con nuevo EBIT
    revenue = m.get("revenue", 0) or 0
    operating_margin_bb = (ebit_bb / revenue) if revenue else 0

    # Net Abnormal Losses (after-tax) y NI Adj
    # Net Abnormal = Disposal × (1 - MARGINAL_tax_rate). Bloomberg usa marginal MX = 30%.
    tax_expense  = m.get("tax_expense", 0) or 0
    pretax_gaap_orig = pretax_gaap
    MARGINAL_TAX_MX = 0.30  # Bloomberg standard para tax-effecting de abnormals
    net_abnormal = disposal_period * (1 - MARGINAL_TAX_MX)
    ni_gaap_val = m.get("net_income_gaap", 0) or 0
    ni_common_gaap_val = m.get("ni_common_gaap", 0) or 0
    ni_common_adj = ni_common_gaap_val + net_abnormal

    # Tax breakdown: usar valores parseados directos (no derivar)
    current_tax = current_tax_period
    deferred_tax = deferred_tax_period

    # Update dict
    m["selling_expenses"]    = selling_bb
    m["sga_total"]           = sga_bb
    m["other_op_income"]     = 0.0      # BB lo deja blank
    m["other_op_expense"]    = other_op_expense_bb
    m["op_expenses_total"]   = op_expenses_total_bb
    m["ebit"]                = ebit_bb
    m["ebita"]               = ebit_bb
    m["interest_expense"]    = int_exp_bb
    m["interest_income"]     = int_inc_bb
    m["net_interest"]        = net_interest_bb
    m["fx_loss"]             = fx_loss_bb
    m["other_non_op"]        = other_nop_bb
    m["non_op_loss"]         = non_op_loss_bb
    m["pretax_adjusted"]     = pretax_adjusted_bb
    m["abnormal_losses"]     = abnormal_losses_bb
    m["disposal_assets"]     = disposal_assets_bb
    m["ebitda"]              = ebitda_bb
    m["operating_margin"]    = operating_margin_bb
    m["current_tax"]         = current_tax
    m["deferred_tax"]        = deferred_tax
    m["net_abnormal"]        = net_abnormal
    m["ni_common_adj"]       = ni_common_adj
    m["export_sales"]        = export_sales_period if export_sales_period else None
    return m


# Registry: ticker -> reclassification function
TICKER_RECLASS_RULES = {
    "CUERVO": _apply_cuervo_reclass,
}


def _compute_income_metrics(snap, annual_only: bool, fx_mult: float,
                              prev_year_snap=None, ticker=None,
                              disposal_period: float = 0.0,
                              deferred_tax_period: float = 0.0,
                              dividends_period_mdp: float = 0.0) -> dict:
    """Calcula TODAS las metricas Bloomberg-style para un periodo.

    snap: PeriodSnapshot del periodo actual.
    annual_only: si True, usa income (acum YTD); si False, income_quarter (3M).
    prev_year_snap: misma quarter, año anterior (para Growth YoY).
    ticker: si presente y hay regla en TICKER_RECLASS_RULES, aplica
            reclasificacion CNBV->Bloomberg al final.
    disposal_period: Disposal of Assets en BB-sign (positivo=gain) para el periodo,
                      ya pre-calculado por el caller (puede requerir derivacion trim).
    """
    res = snap.parsed
    # Source: income_quarter para trim, income para anual; fallback a income
    if (not annual_only) and getattr(res, "income_quarter", None) is not None:
        inc = res.income_quarter
    else:
        inc = res.income

    M = 1_000_000

    def to_mdp(v):
        try:
            return (float(v or 0) * fx_mult) / M
        except (TypeError, ValueError):
            return 0.0

    revenue          = to_mdp(_safe_get(inc, "revenue"))
    cost_of_revenue  = to_mdp(_safe_get(inc, "cost_of_sales"))
    gross_profit     = to_mdp(_safe_get(inc, "gross_profit"))
    selling          = to_mdp(_safe_get(inc, "selling_expenses"))
    ga               = to_mdp(_safe_get(inc, "ga_expenses"))
    sga_total        = selling + ga
    other_op_income  = to_mdp(_safe_get(inc, "other_operating_income"))
    other_op_expense = to_mdp(_safe_get(inc, "other_operating_expense"))
    op_expenses_total= sga_total + other_op_expense
    ebit             = to_mdp(_safe_get(inc, "ebit"))

    interest_exp     = to_mdp(_safe_get(inc, "interest_expense"))
    interest_inc     = to_mdp(_safe_get(inc, "interest_income"))
    net_interest     = interest_exp - interest_inc
    fx_result        = to_mdp(_safe_get(inc, "fx_result"))
    associates       = to_mdp(_safe_get(inc, "associates_result"))
    affiliates_loss  = -associates  # Bloomberg: positivo = loss; CNBV: positivo = gain
    other_non_op     = 0.0   # CNBV no separa explicitamente
    non_op_loss      = net_interest + fx_result + affiliates_loss + other_non_op

    pretax_gaap      = to_mdp(_safe_get(inc, "pretax_income"))
    pretax_adjusted  = pretax_gaap   # sin separacion abnormal
    abnormal         = pretax_gaap - pretax_adjusted   # = 0
    disposal_assets  = 0.0
    asset_writedown  = 0.0
    unrealized_inv   = 0.0

    tax_expense      = to_mdp(_safe_get(inc, "tax_expense"))
    current_tax      = None  # CNBV no separa current vs deferred
    deferred_tax     = None
    income_cont_ops  = pretax_gaap - tax_expense

    net_xo           = 0.0
    disc_ops         = 0.0
    acc_changes      = 0.0

    ni_incl_mi       = to_mdp(_safe_get(inc, "net_income"))
    minority         = to_mdp(_safe_get(inc, "net_income_minority"))
    ni_gaap          = to_mdp(_safe_get(inc, "net_income_controlling"))
    preferred_div    = 0.0
    other_adj        = 0.0
    ni_common_gaap   = ni_gaap - preferred_div - other_adj
    ni_common_adj    = ni_common_gaap   # sin ajuste abnormal

    shares_mn        = res.informative.shares_outstanding / M  # millones de acciones
    eps_basic_gaap   = (ni_common_gaap / shares_mn) if shares_mn else 0.0
    eps_dil_gaap     = eps_basic_gaap   # CUERVO no diluted

    # Growth YoY: revenue actual / revenue mismo Q año anterior
    growth_yoy = None
    if prev_year_snap is not None:
        prev_inc = (prev_year_snap.parsed.income_quarter
                    if (not annual_only and getattr(prev_year_snap.parsed, "income_quarter", None))
                    else prev_year_snap.parsed.income)
        prev_fx = _detect_fx_mult(prev_year_snap, 19.5)  # default rate; suficiente para % YoY
        prev_rev = to_mdp(_safe_get(prev_inc, "revenue")) * (prev_fx / fx_mult)  # ajustar FX
        if prev_rev:
            growth_yoy = revenue / prev_rev - 1.0

    # D&A: trimestral usa da_quarter, anual usa da_12m
    if annual_only:
        da_value = to_mdp(res.informative.da_12m)
        ebitda = ebit + da_value
    else:
        da_q = to_mdp(getattr(res.informative, "da_quarter", 0))
        da_value = da_q
        ebitda = ebit + da_q

    # T12M EBITDA margin (siempre LTM)
    ebitda_12m = to_mdp(res.informative.ebit_12m or 0) + to_mdp(res.informative.da_12m or 0)
    revenue_12m = to_mdp(res.informative.revenue_12m or 0)
    ebitda_margin_ttm = (ebitda_12m / revenue_12m) if revenue_12m else 0.0

    # Margenes del periodo actual
    gross_margin     = (gross_profit / revenue) if revenue else 0.0
    operating_margin = (ebit / revenue) if revenue else 0.0
    profit_margin    = (ni_common_gaap / revenue) if revenue else 0.0

    # Dividends (period actual; el caller puede sobrescribir con dividends_period_mdp ya derivado)
    cf = res.cashflow
    if dividends_period_mdp != 0.0:
        total_cash_div = dividends_period_mdp
    else:
        total_cash_div = to_mdp(abs(_safe_get(cf, "dividends_paid")))
    dps = (total_cash_div / shares_mn) if shares_mn else None

    # Sales per Employee (revenue / num_employees) en MXN unidades
    num_emp = _safe_get(res.informative, "num_employees", 0)
    sales_per_emp = (revenue * 1e6 / num_emp) if num_emp else None

    # Ensamblar dict de salida (luego se aplica reclassification por ticker)
    output = {
        "revenue": revenue, "growth_yoy": growth_yoy, "rd_in_cogs": 0.0,
        "cost_of_revenue": cost_of_revenue, "gross_profit": gross_profit,
        "other_op_income": other_op_income,
        "op_expenses_total": sga_total + other_op_expense,
        "sga_total": sga_total, "selling_expenses": selling, "ga_expenses": ga,
        "rd_in_opex": 0.0, "other_op_expense": other_op_expense, "ebit": ebit,
        "non_op_loss": non_op_loss, "net_interest": net_interest,
        "interest_expense": interest_exp, "interest_income": interest_inc,
        "fx_loss": fx_result, "affiliates_loss": affiliates_loss,
        "other_non_op": other_non_op,
        "pretax_adjusted": pretax_adjusted, "abnormal_losses": abnormal,
        "disposal_assets": disposal_assets, "asset_writedown": asset_writedown,
        "unrealized_inv": unrealized_inv, "pretax_gaap": pretax_gaap,
        "tax_expense": tax_expense, "current_tax": current_tax,
        "deferred_tax": deferred_tax, "income_cont_ops": income_cont_ops,
        "net_xo": net_xo, "disc_ops": disc_ops, "acc_changes": acc_changes,
        "ni_incl_mi": ni_incl_mi, "minority_interest": minority,
        "net_income_gaap": ni_gaap, "preferred_div": preferred_div,
        "other_adj": other_adj, "ni_common_gaap": ni_common_gaap,
        "ni_common_adj": ni_common_adj, "net_abnormal": 0.0, "net_xo_2": 0.0,
        "shares_basic": shares_mn, "eps_basic_gaap": eps_basic_gaap,
        "eps_basic_cont": eps_basic_gaap, "eps_basic_adj": eps_basic_gaap,
        "shares_diluted": shares_mn, "eps_dil_gaap": eps_dil_gaap,
        "eps_dil_cont": eps_dil_gaap, "eps_dil_adj": eps_dil_gaap,
        "accounting_std": "IAS/IFRS", "ebitda": ebitda,
        "ebitda_margin_ttm": ebitda_margin_ttm, "ebita": ebit,
        "gross_margin": gross_margin, "operating_margin": operating_margin,
        "profit_margin": profit_margin, "sales_per_emp": sales_per_emp, "dps": dps,
        "total_cash_div": total_cash_div, "export_sales": None,
        "dep_expense": da_value,
    }
    if ticker and ticker in TICKER_RECLASS_RULES:
        # Resolver valores de notas para el periodo (trim o acum) usando valores ya parseados
        # del Informative del snapshot. annual_only=True usa _acum, sino _quarter.
        if annual_only:
            interest_earned_p = (res.informative.interest_earned_acum * fx_mult) / 1_000_000
            fx_gain_p = (res.informative.fx_gain_acum * fx_mult) / 1_000_000
            current_tax_p = (res.informative.current_tax_acum * fx_mult) / 1_000_000
            export_sales_p = (res.informative.sales_export_acum * fx_mult) / 1_000_000
        else:
            interest_earned_p = (res.informative.interest_earned_quarter * fx_mult) / 1_000_000
            fx_gain_p = (res.informative.fx_gain_quarter * fx_mult) / 1_000_000
            current_tax_p = (res.informative.current_tax_quarter * fx_mult) / 1_000_000
            # Export sales no tiene quarter en CNBV, usar acum como aproximacion
            export_sales_p = (res.informative.sales_export_acum * fx_mult) / 1_000_000

        output = TICKER_RECLASS_RULES[ticker](
            output,
            disposal_period=disposal_period,
            deferred_tax_period=deferred_tax_period,
            current_tax_period=current_tax_p,
            interest_earned_period=interest_earned_p,
            fx_gain_period=fx_gain_p,
            export_sales_period=export_sales_p,
        )
    return output


def _income_adjusted_lines(use_quarter_data: bool):
    """Devuelve INCOME_LINES adaptado para vista anual o trimestral.

    use_quarter_data=True -> intenta res.income_quarter (3 meses puros);
                              fallback a res.income si no existe.
    use_quarter_data=False -> usa res.income (acumulado, full year para Q4)
    """
    def _resolve_obj(r):
        """Devuelve el income object adecuado, con fallback."""
        if use_quarter_data:
            obj = getattr(r, "income_quarter", None)
            if obj is not None:
                return obj
            # Fallback a income (acumulado) si no hay quarter
            return getattr(r, "income", None)
        return getattr(r, "income", None)

    def _get(field):
        def f(r):
            obj = _resolve_obj(r)
            if obj is None:
                return None
            return getattr(obj, field, None)
        return f

    def _ratio(num_field, den_field):
        def f(r):
            obj = _resolve_obj(r)
            if obj is None:
                return None
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
            ((getattr(_resolve_obj(r) or type('X', (), {})(), 'interest_expense', 0) or 0) -
             (getattr(_resolve_obj(r) or type('X', (), {})(), 'interest_income', 0) or 0))
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
        ("EBITDA (EBIT + D&A 12M)",            lambda r: ((getattr(_resolve_obj(r) or type('X', (), {})(), 'ebit', 0) or 0) + (r.informative.da_12m or 0)), "subtotal"),
        ("",                                   None,                          "spacer"),
        ("Gross Margin",                       _ratio("gross_profit", "revenue"),  "ratio"),
        ("Operating Margin",                   _ratio("ebit", "revenue"),     "ratio"),
        ("Profit Margin",                      _ratio("net_income_controlling", "revenue"), "ratio"),
        ("Effective Tax Rate",                 _ratio("tax_expense", "pretax_income"), "ratio"),
    ]


# ===========================================================================
# BAL SHEET - Standardized EXACTO Bloomberg
# Balance es snapshot, no requiere quarter vs annual distintos
# ===========================================================================

# Layout: (display_label, key_in_metrics, kind)
BLOOMBERG_BS_LAYOUT = [
    ("Total Assets",                              None,                  "section"),
    ("  + Cash, Cash Equivalents & STI",          "cash_sti",            "line"),
    ("    + Cash & Cash Equivalents",             "cash_eq",             "sub"),
    ("    + ST Investments",                      "st_invest",           "sub"),
    ("  + Accounts & Notes Receiv",               "accts_notes_rec",     "line"),
    ("    + Accounts Receivable, Net",            "accts_rec_net",       "sub"),
    ("    + Notes Receivable, Net",               "notes_rec_net",       "sub"),
    ("  + Inventories",                           "inventories_total",   "line"),
    ("    + Raw Materials",                       "inv_raw",             "sub"),
    ("    + Work In Process",                     "inv_wip",             "sub"),
    ("    + Finished Goods",                      "inv_finished",        "sub"),
    ("    + Other Inventory",                     "inv_other",           "sub"),
    ("  + Other ST Assets",                       "other_st_assets",     "line"),
    ("    + Prepaid Expenses",                    "prepaid_exp_full",    "sub"),
    ("    + Assets Held-for-Sale",                "assets_hfs",          "sub"),
    ("    + Taxes Receivable",                    "taxes_rec",           "sub"),
    ("    + Misc ST Assets",                      "misc_st_assets",      "sub"),
    ("Total Current Assets",                      "total_current_assets","subtotal"),
    ("  + Property, Plant & Equip, Net",          "ppe_net",             "line"),
    ("    + Property, Plant & Equip",             "ppe_gross",           "sub"),
    ("    - Accumulated Depreciation",            "accum_depr",          "sub"),
    ("  + LT Investments & Receivables",          "lt_inv_rec",          "line"),
    ("    + LT Investments",                      "lt_invest",           "sub"),
    ("    + LT Receivables",                      "lt_rec",              "sub"),
    ("  + Other LT Assets",                       "other_lt_assets",     "line"),
    ("    + Total Intangible Assets",             "total_intangibles",   "sub"),
    ("    + Goodwill",                            "goodwill",            "sub"),
    ("    + Other Intangible Assets",             "other_intang",        "sub"),
    ("    + Deferred Tax Assets",                 "def_tax_assets",      "sub"),
    ("    + Derivative & Hedging Assets",         "deriv_hedge_assets",  "sub"),
    ("    + Prepaid Pension Costs",               "prepaid_pension",     "sub"),
    ("    + Investments in Affiliates",           "inv_affiliates",      "sub"),
    ("    + Misc LT Assets",                      "misc_lt_assets",      "sub"),
    ("Total Noncurrent Assets",                   "total_noncurrent_assets","subtotal"),
    ("Total Assets",                              "total_assets",        "header"),
    ("",                                          None,                  "spacer"),
    ("Liabilities & Shareholders' Equity",        None,                  "section"),
    ("  + Payables & Accruals",                   "payables_accr",       "line"),
    ("    + Accounts Payable",                    "accts_payable",       "sub"),
    ("    + Other Payables & Accruals",           "other_payables",      "sub"),
    ("  + ST Debt",                               "st_debt_total",       "line"),
    ("    + ST Borrowings",                       "st_borrow",           "sub"),
    ("    + ST Lease Liabilities",                "st_lease_liab",       "sub"),
    ("  + Other ST Liabilities",                  "other_st_liab",       "line"),
    ("    + Deferred Revenue",                    "def_rev_st",          "sub"),
    ("    + Derivatives & Hedging",               "deriv_hedge_st",      "sub"),
    ("    + Misc ST Liabilities",                 "misc_st_liab",        "sub"),
    ("Total Current Liabilities",                 "total_current_liab",  "subtotal"),
    ("  + LT Debt",                               "lt_debt_total",       "line"),
    ("    + LT Borrowings",                       "lt_borrow",           "sub"),
    ("    + LT Lease Liabilities",                "lt_lease_liab",       "sub"),
    ("  + Other LT Liabilities",                  "other_lt_liab",       "line"),
    ("    + Accrued Liabilities",                 "accrued_lt",          "sub"),
    ("    + Pension Liabilities",                 "pension_liab",        "sub"),
    ("    + Pensions",                            "pensions",            "sub"),
    ("    + Other Post-Ret Benefits",             "post_ret",            "sub"),
    ("    + Deferred Revenue",                    "def_rev_lt",          "sub"),
    ("    + Deferred Tax Liabilities",            "def_tax_liab",        "sub"),
    ("    + Derivatives & Hedging",               "deriv_hedge_lt",      "sub"),
    ("    + Misc LT Liabilities",                 "misc_lt_liab",        "sub"),
    ("Total Noncurrent Liabilities",              "total_noncurrent_liab","subtotal"),
    ("Total Liabilities",                         "total_liabilities",   "header"),
    ("  + Preferred Equity and Hybrid Capital",   "preferred_equity",    "line"),
    ("  + Share Capital & APIC",                  "share_cap_apic",      "line"),
    ("    + Common Stock",                        "common_stock",        "sub"),
    ("    + Additional Paid in Capital",          "apic",                "sub"),
    ("  - Treasury Stock",                        "treasury",            "line"),
    ("  + Retained Earnings",                     "retained_earn",       "line"),
    ("  + Other Equity",                          "other_equity",        "line"),
    ("Equity Before Minority Interest",           "equity_before_mi",    "subtotal"),
    ("  + Minority/Non Controlling Interest",     "minority",            "line"),
    ("Total Equity",                              "total_equity",        "header"),
    ("Total Liabilities & Equity",                "total_liab_eq",       "header"),
    ("",                                          None,                  "spacer"),
    ("Reference Items",                           None,                  "section"),
    ("Accounting Standard",                       "accounting_std",      "string"),
    ("Shares Outstanding",                        "shares_out",          "raw"),
    ("Number of Treasury Shares",                 "treasury_shares",     "raw"),
    ("Pension Obligations",                       "pension_obl",         "line"),
    ("Net Debt",                                  "net_debt",            "subtotal"),
    ("Net Debt to Equity",                        "nd_to_equity",        "ratio"),
    ("Tangible Common Equity Ratio",              "tce_ratio",           "ratio"),
    ("Current Ratio",                             "current_ratio",       "ratio_x"),
    ("Cash Conversion Cycle",                    "ccc",                 "raw_days"),
    ("Number of Employees",                       "num_employees",       "raw"),
]


def _compute_bs_metrics(snap, fx_mult: float, ticker=None,
                          revenue_for_ratios: float = 0.0,
                          cogs_for_ratios: float = 0.0) -> dict:
    """Calcula TODAS las metricas Bloomberg-style del Balance Sheet."""
    res = snap.parsed
    b = res.balance
    inf = res.informative
    M = 1_000_000

    def to_mdp(v):
        try:
            return (float(v or 0) * fx_mult) / M
        except (TypeError, ValueError):
            return 0.0

    # Cash & STI
    cash_eq = to_mdp(b.cash)
    st_invest = 0.0  # CUERVO no tiene; podria parsearse de 800100 si requiere
    cash_sti = cash_eq + st_invest

    # Receivables
    accts_rec_trade = to_mdp(b.accounts_receivable_trade) or to_mdp(b.accounts_receivable)
    notes_rec = 0.0
    accts_notes_rec = accts_rec_trade + notes_rec

    # Inventory
    inv_raw = to_mdp(b.inventory_raw_materials)
    inv_wip = to_mdp(b.inventory_wip)
    inv_finished = to_mdp(b.inventory_finished)
    # "Other Inventory" Bloomberg = Suministros + Repuestos + Bio circulante (CUERVO)
    inv_other = (to_mdp(b.inventory_supplies) + to_mdp(b.inventory_spare_parts)
                  + to_mdp(b.biological_assets_current))
    inventories_total = inv_raw + inv_wip + inv_finished + inv_other

    # Other ST Assets (BB folds Tax Receivable into Prepaid Expenses)
    # BB Prepaid = CNBV "Gastos anticipados" + "Cuentas por cobrar de impuestos"
    prepaid_exp_full = to_mdp(b.prepaid_expenses_st) + to_mdp(b.taxes_recoverable_st)
    assets_hfs = 0.0  # CUERVO no tiene
    taxes_rec = 0.0   # ya foldeado en prepaid
    # Misc ST Assets = Otras cuentas por cobrar + Otros activos financieros + Cuentas por cobrar partes relacionadas
    misc_st_assets = (to_mdp(b.other_receivables_st)
                       + to_mdp(b.other_financial_assets_st)
                       + to_mdp(b.accounts_receivable_related_st))
    other_st_assets = prepaid_exp_full + assets_hfs + taxes_rec + misc_st_assets

    total_current_assets = to_mdp(b.total_current_assets)

    # PPE
    ppe_net_basic = to_mdp(b.ppe)
    rou = to_mdp(b.right_of_use_assets)
    # BB PPE Net incluye ROU (IFRS-16)
    ppe_net = ppe_net_basic + rou
    ppe_gross = ppe_net  # Sin desglose por ahora (CNBV no separa gross fácilmente)
    accum_depr = 0.0

    # LT Investments & Receivables (BB)
    lt_invest = 0.0
    lt_rec = to_mdp(b.accounts_receivable_lt)
    lt_inv_rec = lt_invest + lt_rec

    # Other LT Assets (BB)
    goodwill = to_mdp(b.goodwill)
    other_intang = to_mdp(b.intangibles)
    total_intangibles = goodwill + other_intang
    def_tax_assets = to_mdp(b.deferred_tax_assets)
    deriv_hedge_assets = 0.0
    prepaid_pension = 0.0
    inv_affiliates = to_mdp(b.investments_in_associates)
    # Misc LT Assets = Bio LP + Inventarios LP + Otros activos LP
    misc_lt_assets = (to_mdp(b.biological_assets_noncurrent)
                       + to_mdp(b.inventories_noncurrent)
                       + to_mdp(b.other_non_current_assets))
    other_lt_assets = (total_intangibles + def_tax_assets + deriv_hedge_assets
                        + prepaid_pension + inv_affiliates + misc_lt_assets)

    total_noncurrent_assets = to_mdp(b.total_non_current_assets)
    total_assets = to_mdp(b.total_assets)

    # ===== LIABILITIES =====
    # BB folda "related parties" dentro de "Accounts Payable" (no separa)
    accts_payable = to_mdp(b.accounts_payable_trade) + to_mdp(b.accounts_payable_related_st)
    if not accts_payable:
        accts_payable = to_mdp(b.accounts_payable)
    other_payables = 0.0
    payables_accr = accts_payable + other_payables

    # ST Debt
    st_borrow = to_mdp(b.short_term_debt)   # Otros pasivos financieros CP
    st_lease_liab = to_mdp(b.short_term_lease)
    st_debt_total = st_borrow + st_lease_liab

    # Other ST Liab
    def_rev_st = 0.0
    deriv_hedge_st = 0.0
    misc_st_liab = to_mdp(b.provisions_st)
    other_st_liab = def_rev_st + deriv_hedge_st + misc_st_liab

    total_current_liab = to_mdp(b.total_current_liabilities)

    # LT Debt
    lt_borrow = to_mdp(b.long_term_debt)
    lt_lease_liab = to_mdp(b.long_term_lease)
    lt_debt_total = lt_borrow + lt_lease_liab

    # Other LT Liab
    accrued_lt = 0.0
    pension_liab = 0.0
    pensions = 0.0
    post_ret = 0.0
    def_rev_lt = 0.0
    def_tax_liab = to_mdp(b.deferred_tax_liabilities)
    deriv_hedge_lt = 0.0
    misc_lt_liab = to_mdp(b.provisions_lt)
    other_lt_liab = (accrued_lt + pension_liab + pensions + post_ret + def_rev_lt
                      + def_tax_liab + deriv_hedge_lt + misc_lt_liab)

    total_noncurrent_liab = to_mdp(b.total_non_current_liabilities)
    total_liabilities = to_mdp(b.total_liabilities)

    # ===== EQUITY =====
    preferred_equity = 0.0
    common_stock = to_mdp(b.common_stock)
    apic = to_mdp(b.additional_paid_in_capital)
    share_cap_apic = common_stock + apic
    treasury = to_mdp(b.treasury_stock)
    retained_earn = to_mdp(b.retained_earnings)
    other_equity = to_mdp(b.other_equity_reserves)
    equity_before_mi = to_mdp(b.equity_controlling)
    minority = to_mdp(b.minority_interest)
    total_equity = to_mdp(b.total_equity)
    total_liab_eq = total_liabilities + total_equity

    # ===== REFERENCE ITEMS =====
    net_debt_val = (st_debt_total + lt_debt_total) - cash_eq
    nd_to_eq = (net_debt_val / equity_before_mi * 100) if equity_before_mi else 0
    # TCE = (Equity - Goodwill - Other Intangibles) / (Total Assets - Goodwill - Intangibles)
    tce_num = equity_before_mi - goodwill - other_intang
    tce_den = total_assets - goodwill - other_intang
    tce_ratio = (tce_num / tce_den * 100) if tce_den else 0
    current_ratio = (total_current_assets / total_current_liab) if total_current_liab else 0
    # Cash Conversion Cycle = DSO + DIO - DPO (LTM)
    rev_for_ccc = revenue_for_ratios   # LTM revenue
    cogs_for_ccc = cogs_for_ratios if cogs_for_ratios > 0 else (rev_for_ccc * 0.45)
    if rev_for_ccc > 0 and cogs_for_ccc > 0:
        dso = accts_rec_trade / rev_for_ccc * 365
        dio = inventories_total / cogs_for_ccc * 365
        dpo = accts_payable / cogs_for_ccc * 365
        ccc = dso + dio - dpo
    else:
        ccc = 0

    output = {
        "cash_sti": cash_sti, "cash_eq": cash_eq, "st_invest": st_invest,
        "accts_notes_rec": accts_notes_rec, "accts_rec_net": accts_rec_trade,
        "notes_rec_net": notes_rec,
        "inventories_total": inventories_total, "inv_raw": inv_raw, "inv_wip": inv_wip,
        "inv_finished": inv_finished, "inv_other": inv_other,
        "other_st_assets": other_st_assets, "prepaid_exp_full": prepaid_exp_full,
        "assets_hfs": assets_hfs, "taxes_rec": taxes_rec, "misc_st_assets": misc_st_assets,
        "total_current_assets": total_current_assets,
        "ppe_net": ppe_net, "ppe_gross": ppe_gross, "accum_depr": accum_depr,
        "lt_inv_rec": lt_inv_rec, "lt_invest": lt_invest, "lt_rec": lt_rec,
        "other_lt_assets": other_lt_assets, "total_intangibles": total_intangibles,
        "goodwill": goodwill, "other_intang": other_intang,
        "def_tax_assets": def_tax_assets, "deriv_hedge_assets": deriv_hedge_assets,
        "prepaid_pension": prepaid_pension, "inv_affiliates": inv_affiliates,
        "misc_lt_assets": misc_lt_assets,
        "total_noncurrent_assets": total_noncurrent_assets,
        "total_assets": total_assets,
        "payables_accr": payables_accr, "accts_payable": accts_payable,
        "other_payables": other_payables,
        "st_debt_total": st_debt_total, "st_borrow": st_borrow, "st_lease_liab": st_lease_liab,
        "other_st_liab": other_st_liab, "def_rev_st": def_rev_st,
        "deriv_hedge_st": deriv_hedge_st, "misc_st_liab": misc_st_liab,
        "total_current_liab": total_current_liab,
        "lt_debt_total": lt_debt_total, "lt_borrow": lt_borrow, "lt_lease_liab": lt_lease_liab,
        "other_lt_liab": other_lt_liab, "accrued_lt": accrued_lt,
        "pension_liab": pension_liab, "pensions": pensions, "post_ret": post_ret,
        "def_rev_lt": def_rev_lt, "def_tax_liab": def_tax_liab,
        "deriv_hedge_lt": deriv_hedge_lt, "misc_lt_liab": misc_lt_liab,
        "total_noncurrent_liab": total_noncurrent_liab,
        "total_liabilities": total_liabilities,
        "preferred_equity": preferred_equity, "share_cap_apic": share_cap_apic,
        "common_stock": common_stock, "apic": apic, "treasury": treasury,
        "retained_earn": retained_earn, "other_equity": other_equity,
        "equity_before_mi": equity_before_mi, "minority": minority,
        "total_equity": total_equity, "total_liab_eq": total_liab_eq,
        "accounting_std": "IAS/IFRS",
        "shares_out": inf.shares_outstanding / M,
        "treasury_shares": 0,
        "pension_obl": 0,
        "net_debt": net_debt_val,
        "nd_to_equity": nd_to_eq / 100 if nd_to_eq else 0,  # como decimal
        "tce_ratio": tce_ratio / 100 if tce_ratio else 0,
        "current_ratio": current_ratio,
        "ccc": ccc,
        "num_employees": inf.num_employees,
    }

    return output


# Layout viejo (compat con builders existentes que aun lo usan)
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


# ===========================================================================
# CASH FLOW - Standardized EXACTO Bloomberg
# Para trimestral: derivar Q puro (Q acum - Q-1 acum mismo año) para TODO
# Para anual: usar acum del Q4 / 4D (full year)
# ===========================================================================

BLOOMBERG_CF_LAYOUT = [
    ("Cash from Operating Activities",                  None,                "section"),
    ("  + Net Income",                                  "ni",                "line"),
    ("  + Depreciation & Amortization",                 "da_cf",             "line"),
    ("  + Non-Cash Items",                              "non_cash",          "line"),
    ("    + Other Non-Cash Adj",                        "non_cash",          "sub"),
    ("  + Chg in Non-Cash Work Cap",                    "wc_change",         "line"),
    ("    + (Inc) Dec in Accts Receiv",                 "chg_receivables",   "sub"),
    ("    + (Inc) Dec in Inventories",                  "chg_inventories",   "sub"),
    ("    + Inc (Dec) in Accts Payable",                "chg_payables",      "sub"),
    ("    + Inc (Dec) in Other",                        "chg_other_wc",      "sub"),
    ("  + Net Cash From Disc Ops",                      "disc_ops_oper",     "line"),
    ("Cash from Operating Activities",                  "cfo_total",         "header"),
    ("",                                                None,                "spacer"),
    ("Cash from Investing Activities",                  None,                "section"),
    ("  + Change in Fixed & Intang",                    "chg_fixed_intang",  "line"),
    ("    + Disp in Fixed & Intang",                    "disp_fixed_intang", "sub"),
    ("    + Disp of Fixed Prod Assets",                 "disp_fixed_prod",   "sub"),
    ("    + Disp of Intangible Assets",                 "disp_intang",       "sub"),
    ("    + Acq of Fixed & Intang",                     "acq_fixed_intang",  "sub"),
    ("    + Acq of Fixed Prod Assets",                  "acq_fixed_prod",    "sub"),
    ("    + Acq of Intangible Assets",                  "acq_intang",        "sub"),
    ("  + Net Change in LT Investment",                 "net_chg_lt_inv",    "line"),
    ("    + Dec in LT Investment",                      "dec_lt_inv",        "sub"),
    ("    + Inc in LT Investment",                      "inc_lt_inv",        "sub"),
    ("  + Net Cash From Acq & Div",                     "cash_acq_div",      "line"),
    ("    + Cash from Divestitures",                    "cash_divest",       "sub"),
    ("    + Cash for Acq of Subs",                      "cash_acq_subs",     "sub"),
    ("    + Cash for JVs",                              "cash_jvs",          "sub"),
    ("  + Other Investing Activities",                  "other_invest",      "line"),
    ("  + Net Cash From Disc Ops",                      "disc_ops_inv",      "line"),
    ("Cash from Investing Activities",                  "cfi_total",         "header"),
    ("",                                                None,                "spacer"),
    ("Cash from Financing Activities",                  None,                "section"),
    ("  + Dividends Paid",                              "div_paid",          "line"),
    ("  + Cash From (Repayment) Debt",                  "cash_repay_debt",   "line"),
    ("    + Cash From (Repay) ST Debt",                 "cash_st_debt",      "sub"),
    ("    + Cash From LT Debt",                         "cash_from_lt_debt", "sub"),
    ("    + Repayments of LT Debt",                     "repay_lt_debt",     "sub"),
    ("  + Cash (Repurchase) of Equity",                 "cash_repurch_eq",   "line"),
    ("    + Increase in Capital Stock",                 "incr_cap_stock",    "sub"),
    ("    + Decrease in Capital Stock",                 "decr_cap_stock",    "sub"),
    ("  + Other Financing Activities",                  "other_fin",         "line"),
    ("  + Net Cash From Disc Ops",                      "disc_ops_fin",      "line"),
    ("Cash from Financing Activities",                  "cff_total",         "header"),
    ("",                                                None,                "spacer"),
    ("  Effect of Foreign Exchange Rates",              "fx_effect",         "line"),
    ("",                                                None,                "spacer"),
    ("Net Changes in Cash",                             "net_chg_cash",      "header"),
    ("",                                                None,                "spacer"),
    ("Cash Paid for Taxes",                             "cash_paid_taxes",   "line"),
    ("Cash Paid for Interest",                          "cash_paid_interest","line"),
    ("",                                                None,                "spacer"),
    ("Reference Items",                                 None,                "section"),
    ("EBITDA",                                          "ebitda",            "line"),
    ("Trailing 12M EBITDA Margin",                      "ebitda_margin_ttm", "ratio"),
    ("Interest Received",                               "interest_received", "line"),
    ("Free Cash Flow",                                  "fcf",               "subtotal"),
    ("Free Cash Flow to Firm",                          "fcff",              "subtotal"),
    ("Free Cash Flow to Equity",                        "fcfe",              "subtotal"),
    ("Free Cash Flow per Basic Share",                  "fcf_per_share",     "ratio_eps"),
    ("Price to Free Cash Flow",                         "px_to_fcf",         "ratio_x"),
    ("Cash Flow to Net Income",                         "cf_to_ni",          "ratio_x"),
]


def _compute_cf_metrics(snap, fx_mult: float, ticker=None,
                          # Pre-derived period values:
                          ni_period: float = 0.0,
                          da_period: float = 0.0,
                          ebit_period: float = 0.0,
                          tax_expense_period: float = 0.0,
                          ebitda_ttm_margin: float = 0.0,
                          # Pre-derived CF period values (trim or annual):
                          cfo_pre_adj_p: float = 0.0,
                          cfo_p: float = 0.0,
                          chg_inv_p: float = 0.0,
                          chg_recv_p: float = 0.0,
                          chg_other_recv_p: float = 0.0,
                          chg_pay_p: float = 0.0,
                          chg_other_pay_p: float = 0.0,
                          capex_ppe_p: float = 0.0,
                          capex_intang_p: float = 0.0,
                          sales_ppe_p: float = 0.0,
                          sales_intang_p: float = 0.0,
                          loss_control_p: float = 0.0,
                          obtain_control_p: float = 0.0,
                          cfi_p: float = 0.0,
                          debt_issued_p: float = 0.0,
                          debt_repaid_p: float = 0.0,
                          dividends_p: float = 0.0,
                          lease_pmt_p: float = 0.0,
                          int_paid_fin_p: float = 0.0,
                          int_paid_cfo_p: float = 0.0,
                          int_recv_p: float = 0.0,
                          int_recv_cfi_p: float = 0.0,
                          taxes_paid_p: float = 0.0,
                          cff_p: float = 0.0,
                          fx_effect_p: float = 0.0,
                          net_chg_cash_p: float = 0.0,
                          # Para FCF/FCFF/FCFE references:
                          shares: float = 0.0,
                          market_price: float = 0.0,
                          tax_rate: float = 0.30) -> dict:
    """Calcula TODAS las metricas Bloomberg-style del Cash Flow.

    Todos los valores pre-derivados ya vienen en MDP del periodo correcto
    (trim si vista trimestral, anual si vista anual).
    Signos preservan convencion CNBV; la reclassificacion BB se hace abajo.
    """

    # ===== CASH FROM OPERATING =====
    # BB CFO = row 30 (cfo_pre_adj) - antes de interest/tax adjustments
    # WC change components
    chg_other_wc = chg_other_recv_p + chg_other_pay_p
    wc_change = chg_recv_p + chg_inv_p + chg_pay_p + chg_other_wc

    # ===== BB RECLASSIFICATIONS (interest paid/received) =====
    # 1) Interest received en CFO (row 34) suele ser stored signed (CUERVO: -118).
    #    BB lo trata como reference item (Interest Received), NO en CFO.
    #    Para remover su efecto en CFO: restar el valor signed (que ya esta
    #    incluido en cfo_p).
    # 2) Interest paid en Financing (row 75) BB convention = OPERATING outflow.
    #    Mover a CFO: restar de CFO (es outflow), sumar a CFF (revertir la
    #    deduccion que CNBV hizo).
    # 3) Interest received en CFI (row 58) BB lo saca a memo: restar de CFI.
    #
    # Resultado preserva Net Change in Cash (es zero-sum).

    # CFO BB = CNBV_cfo - int_recv_cfo_signed (remover el efecto: cfo ya tiene
    #          incorporado int_recv_cfo signed, asi que restamos el signed)
    #          - int_paid_fin_abs (BB clasifica como operating outflow)
    cfo_bb = (cfo_p if cfo_p else cfo_pre_adj_p) - int_recv_p - abs(int_paid_fin_p)
    cfo_total = cfo_bb
    # Non-Cash residual con BB CFO
    non_cash = cfo_total - ni_period - da_period - wc_change

    # ===== CASH FROM INVESTING =====
    # BB convention: CapEx negativo (outflow), Disposals positivo (inflow)
    # CNBV: capex_ppe stored as positive magnitude (CNBV "-" prefix means outflow)
    acq_fixed_prod = -capex_ppe_p     # BB negative
    acq_intang = -capex_intang_p
    acq_fixed_intang = acq_fixed_prod + acq_intang
    disp_fixed_prod = sales_ppe_p
    disp_intang = sales_intang_p
    disp_fixed_intang = disp_fixed_prod + disp_intang
    chg_fixed_intang = acq_fixed_intang + disp_fixed_intang

    # LT Investment changes (CUERVO no tiene)
    dec_lt_inv = 0.0
    inc_lt_inv = 0.0
    net_chg_lt_inv = dec_lt_inv + inc_lt_inv

    # Acquisitions / Divestitures
    cash_divest = loss_control_p           # CNBV: + Flujos por perdida control
    cash_acq_subs = -obtain_control_p      # CNBV stored positive; BB negative
    cash_jvs = 0.0
    cash_acq_div = cash_divest + cash_acq_subs + cash_jvs

    other_invest = 0.0
    disc_ops_inv = 0.0
    # BB CFI = CNBV CFI - interest_received_in_cfi (BB lo trata como reference)
    cfi_total = cfi_p - int_recv_cfi_p

    # ===== CASH FROM FINANCING =====
    div_paid = -dividends_p                 # CNBV positive magnitude; BB negative
    cash_st_debt = 0.0                       # CUERVO no separa ST debt en CF
    cash_from_lt_debt = debt_issued_p        # CNBV row 69
    repay_lt_debt = -debt_repaid_p          # CNBV stored positive; BB negative
    # BB INCLUYE lease_payments en "Cash From (Repayment) Debt" (no en Other Fin)
    cash_repay_debt = cash_st_debt + cash_from_lt_debt + repay_lt_debt - abs(lease_pmt_p)

    incr_cap_stock = 0.0
    decr_cap_stock = 0.0
    cash_repurch_eq = incr_cap_stock + decr_cap_stock

    # Other Financing = 0 en BB (lease ya esta en cash_repay_debt; interest_paid_fin
    # ya esta en CFO via reclassification)
    other_fin = 0.0
    disc_ops_fin = 0.0
    # BB CFF = CNBV CFF + interest_paid_financing (revertir: BB no clasifica
    # interest paid en financing, lo manda a operating)
    cff_total = cff_p + abs(int_paid_fin_p)

    # ===== EFFECT FX + NET CHANGE =====
    fx_effect = fx_effect_p
    net_chg_cash = net_chg_cash_p
    disc_ops_oper = 0.0

    # ===== CASH PAID (BB shows positive) =====
    # Cash Paid for Interest = magnitudes "reales" de cash interest paid =
    # interest_paid_financing + abs(int_recv_cfo_signed) (CUERVO espeja
    # row 34 negativo como otra forma de "interest paid").
    # No incluir int_paid_cfo (row 33) que parece ser accrued/non-cash adj.
    cash_paid_interest = abs(int_paid_fin_p) + abs(int_recv_p)
    cash_paid_taxes = abs(taxes_paid_p)

    # ===== REFERENCE ITEMS =====
    # EBITDA del periodo
    ebitda_period = ebit_period + da_period
    # Interest Received BB-style: SUMA magnitudes de interest_received_cfo y
    # interest_paid_cfo. CUERVO los usa como pares de cancelacion entre CFO/CFI;
    # BB las roll up como "Interest Received" total magnitude.
    interest_received = abs(int_recv_p) + abs(int_paid_cfo_p)

    # FCF Bloomberg = CFO - CapEx_PPE only (NO incluye intangibles)
    fcf = cfo_total - capex_ppe_p

    # FCFF Bloomberg "pre-tax operating" style:
    # FCFF = EBITDA + Tax Expense - CapEx_total (incluye intangibles)
    # (verified vs CUERVO Q4 2025 trim: 2,680.27 vs BB 2,681.85, diff 0.06%)
    capex_total = capex_ppe_p + capex_intang_p
    fcff = ebitda_period + tax_expense_period - capex_total

    # FCFE Bloomberg = FCF + Cash From (Repayment) Debt
    # (Cash From Debt ya incluye debt_issued, -debt_repaid, y -lease_pmt)
    fcfe = fcf + cash_repay_debt

    # Per share (usar ni_period que aqui es NI_controlling)
    fcf_per_share = (fcf / shares) if shares else 0
    px_to_fcf = (market_price / fcf_per_share) if (market_price and fcf_per_share) else 0
    cf_to_ni = (cfo_total / ni_period) if ni_period else 0

    return {
        "ni": ni_period,
        "da_cf": da_period,
        "non_cash": non_cash,
        "wc_change": wc_change,
        "chg_receivables": chg_recv_p,
        "chg_inventories": chg_inv_p,
        "chg_payables": chg_pay_p,
        "chg_other_wc": chg_other_wc,
        "disc_ops_oper": disc_ops_oper,
        "cfo_total": cfo_total,
        "chg_fixed_intang": chg_fixed_intang,
        "disp_fixed_intang": disp_fixed_intang,
        "disp_fixed_prod": disp_fixed_prod,
        "disp_intang": disp_intang,
        "acq_fixed_intang": acq_fixed_intang,
        "acq_fixed_prod": acq_fixed_prod,
        "acq_intang": acq_intang,
        "net_chg_lt_inv": net_chg_lt_inv,
        "dec_lt_inv": dec_lt_inv,
        "inc_lt_inv": inc_lt_inv,
        "cash_acq_div": cash_acq_div,
        "cash_divest": cash_divest,
        "cash_acq_subs": cash_acq_subs,
        "cash_jvs": cash_jvs,
        "other_invest": other_invest,
        "disc_ops_inv": disc_ops_inv,
        "cfi_total": cfi_total,
        "div_paid": div_paid,
        "cash_repay_debt": cash_repay_debt,
        "cash_st_debt": cash_st_debt,
        "cash_from_lt_debt": cash_from_lt_debt,
        "repay_lt_debt": repay_lt_debt,
        "cash_repurch_eq": cash_repurch_eq,
        "incr_cap_stock": incr_cap_stock,
        "decr_cap_stock": decr_cap_stock,
        "other_fin": other_fin,
        "disc_ops_fin": disc_ops_fin,
        "cff_total": cff_total,
        "fx_effect": fx_effect,
        "net_chg_cash": net_chg_cash,
        "cash_paid_taxes": cash_paid_taxes,
        "cash_paid_interest": cash_paid_interest,
        "ebitda": ebitda_period,
        "ebitda_margin_ttm": ebitda_ttm_margin,
        "interest_received": interest_received,
        "fcf": fcf,
        "fcff": fcff,
        "fcfe": fcfe,
        "fcf_per_share": fcf_per_share,
        "px_to_fcf": px_to_fcf,
        "cf_to_ni": cf_to_ni,
    }


# Layout viejo (compatibilidad; ya no se usa)
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
                                  fx_rate_usdmxn=19.5, max_periods=None,
                                  ticker=None):
    """Income Statement EXACTO estilo Bloomberg Adjusted.

    Si annual_only=True usa income (acumulado del Q4 = full year).
    Si annual_only=False usa income_quarter (3 meses puros).
    Si `ticker` esta en TICKER_RECLASS_RULES, aplica reclassification CNBV->BB.
    """
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]

    # Auto-detectar ticker si no se pasa
    if ticker is None:
        ticker = series.ticker

    labels = [l for l, _, _ in BLOOMBERG_INCOME_LAYOUT]
    kinds  = [k for _, _, k in BLOOMBERG_INCOME_LAYOUT]

    if not snaps:
        return pd.DataFrame(index=labels), kinds

    # Index para Growth YoY: same quarter, prev year
    by_year_q = {(s.year, s.quarter): s for s in series.snapshots}

    # Helper generico: deriva un campo del periodo (trim puro o anual)
    # acum_path: ej. ('cashflow', 'disposal_loss_gain') o ('informative', 'deferred_tax_acum')
    def _derive_period(s_curr, fx, acum_path):
        obj = s_curr.parsed
        for p in acum_path[:-1]:
            obj = getattr(obj, p, None)
            if obj is None:
                return 0.0
        cf_acum = getattr(obj, acum_path[-1], 0) or 0
        if annual_only:
            return cf_acum * fx / 1_000_000
        prev_q_map = {"2": "1", "3": "2", "4": "3", "4D": "3"}
        prev_q = prev_q_map.get(s_curr.quarter)
        if prev_q is None:
            return cf_acum * fx / 1_000_000   # Q1
        prev_snap_same_yr = by_year_q.get((s_curr.year, prev_q))
        if prev_snap_same_yr is None:
            return cf_acum * fx / 1_000_000
        # Navegar al campo en prev snap
        prev_obj = prev_snap_same_yr.parsed
        for p in acum_path[:-1]:
            prev_obj = getattr(prev_obj, p, None)
            if prev_obj is None:
                return cf_acum * fx / 1_000_000
        prev_acum = getattr(prev_obj, acum_path[-1], 0) or 0
        return (cf_acum - prev_acum) * fx / 1_000_000

    # CNBV "+ (-) Pérdida (utilidad) por disposicion": positivo = LOSS (add-back en CF).
    # Bloomberg "Disposal of Assets" positivo = LOSS abnormal. MISMO SIGNO.
    def _disposal_for_period(s_curr, fx):
        return _derive_period(s_curr, fx, ("cashflow", "disposal_loss_gain"))

    # Deferred tax del periodo (de hoja 800200)
    def _deferred_tax_for_period(s_curr, fx):
        return _derive_period(s_curr, fx, ("informative", "deferred_tax_acum"))

    # Dividendos del periodo (de CF dividends_paid)
    def _dividends_for_period(s_curr, fx):
        d = _derive_period(s_curr, fx, ("cashflow", "dividends_paid"))
        return abs(d)   # CNBV tiene signo variable; Bloomberg lo muestra en magnitud

    cols_data = {}
    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)
        prev_snap = by_year_q.get((s.year - 1, s.quarter))
        disposal = _disposal_for_period(s, fx)
        deferred_tax = _deferred_tax_for_period(s, fx)
        dividends   = _dividends_for_period(s, fx)
        metrics = _compute_income_metrics(
            s, annual_only, fx, prev_snap, ticker=ticker,
            disposal_period=disposal,
            deferred_tax_period=deferred_tax,
            dividends_period_mdp=dividends,
        )

        col_vals = []
        for label, key, kind in BLOOMBERG_INCOME_LAYOUT:
            if key is None or kind in ("spacer", "section"):
                col_vals.append(None)
            else:
                col_vals.append(metrics.get(key))
        cols_data[s.label] = col_vals

    df = pd.DataFrame(cols_data, index=labels)
    return df, kinds


def build_bs_standardized_panel(series, annual_only=False,
                                  fx_rate_usdmxn=19.5, max_periods=None,
                                  ticker=None):
    """Balance Sheet EXACTO estilo Bloomberg Standardized."""
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]

    if ticker is None:
        ticker = series.ticker

    labels = [l for l, _, _ in BLOOMBERG_BS_LAYOUT]
    kinds  = [k for _, _, k in BLOOMBERG_BS_LAYOUT]

    if not snaps:
        return pd.DataFrame(index=labels), kinds

    cols_data = {}
    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)
        # LTM revenue + COGS para CCC (income.cost_of_sales = acumulado del periodo)
        ltm_rev = (s.parsed.informative.revenue_12m or 0) * fx / 1_000_000
        # Para COGS LTM: si es Q4 / 4D usa income.cost_of_sales (full year acum)
        # Para Q1-Q3 idealmente derivar LTM, por ahora aproximamos con acum * 4/N
        cogs_acum = (s.parsed.income.cost_of_sales or 0) * fx / 1_000_000
        if s.quarter in ("4", "4D"):
            ltm_cogs = cogs_acum
        else:
            # Q1=acum_Q1*4, Q2=acum*2, Q3=acum*4/3 — aproximacion simple
            mult_map = {"1": 4.0, "2": 2.0, "3": 4/3}
            ltm_cogs = cogs_acum * mult_map.get(s.quarter, 1.0)
        metrics = _compute_bs_metrics(s, fx, ticker=ticker,
                                        revenue_for_ratios=ltm_rev,
                                        cogs_for_ratios=ltm_cogs)

        col_vals = []
        for label, key, kind in BLOOMBERG_BS_LAYOUT:
            if key is None or kind in ("spacer", "section"):
                col_vals.append(None)
            else:
                col_vals.append(metrics.get(key))
        cols_data[s.label] = col_vals

    df = pd.DataFrame(cols_data, index=labels)
    return df, kinds


def build_cf_standardized_panel(series, annual_only=False,
                                  fx_rate_usdmxn=19.5, max_periods=None,
                                  ticker=None):
    """Cash Flow EXACTO estilo Bloomberg Standardized.

    Si annual_only=True usa CF acumulado del Q4/4D (full year).
    Si annual_only=False deriva CF puro trimestral (Q acum - Q-1 acum mismo año).

    Para income/D&A:
      - annual: income (acum YTD del Q4) + informative.da_12m
      - trim:   income_quarter (3M puro) + informative.da_quarter
    """
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]

    if ticker is None:
        ticker = series.ticker

    labels = [l for l, _, _ in BLOOMBERG_CF_LAYOUT]
    kinds  = [k for _, _, k in BLOOMBERG_CF_LAYOUT]

    if not snaps:
        return pd.DataFrame(index=labels), kinds

    # Index para deriving Q puro: por (year, quarter)
    by_year_q = {(s.year, s.quarter): s for s in series.snapshots}

    # Helper generico: deriva un campo CF/info del periodo (trim puro o anual)
    def _derive_period(s_curr, fx, acum_path):
        obj = s_curr.parsed
        for p in acum_path[:-1]:
            obj = getattr(obj, p, None)
            if obj is None:
                return 0.0
        cf_acum = getattr(obj, acum_path[-1], 0) or 0
        if annual_only:
            return cf_acum * fx / 1_000_000
        prev_q_map = {"2": "1", "3": "2", "4": "3", "4D": "3"}
        prev_q = prev_q_map.get(s_curr.quarter)
        if prev_q is None:
            return cf_acum * fx / 1_000_000   # Q1
        prev_snap = by_year_q.get((s_curr.year, prev_q))
        if prev_snap is None:
            return cf_acum * fx / 1_000_000
        prev_obj = prev_snap.parsed
        for p in acum_path[:-1]:
            prev_obj = getattr(prev_obj, p, None)
            if prev_obj is None:
                return cf_acum * fx / 1_000_000
        prev_acum = getattr(prev_obj, acum_path[-1], 0) or 0
        return (cf_acum - prev_acum) * fx / 1_000_000

    cols_data = {}
    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)

        # NI controlling / EBIT / D&A / Tax Expense del periodo
        # BB usa Net Income CONTROLLING (excluye minority interest).
        if annual_only:
            inc = s.parsed.income
            ni_ctrl = inc.net_income_controlling or inc.net_income or 0
            ni_period = ni_ctrl * fx / 1_000_000
            ebit_period = (inc.ebit or 0) * fx / 1_000_000
            tax_exp_p = (inc.tax_expense or 0) * fx / 1_000_000
            da_period = (s.parsed.informative.da_12m or 0) * fx / 1_000_000
        else:
            inc_q = getattr(s.parsed, "income_quarter", None) or s.parsed.income
            ni_ctrl = inc_q.net_income_controlling or inc_q.net_income or 0
            ni_period = ni_ctrl * fx / 1_000_000
            ebit_period = (inc_q.ebit or 0) * fx / 1_000_000
            tax_exp_p = (inc_q.tax_expense or 0) * fx / 1_000_000
            # da_quarter del periodo, fallback a derivar de da_12m
            da_q = getattr(s.parsed.informative, "da_quarter", 0) or 0
            if da_q:
                da_period = da_q * fx / 1_000_000
            else:
                da_period = _derive_period(s, fx, ("cashflow", "da_in_cf"))

        # EBITDA TTM margin (ya viene en informative)
        rev_12m = (s.parsed.informative.revenue_12m or 0) * fx / 1_000_000
        ebit_12m = (s.parsed.informative.ebit_12m or 0) * fx / 1_000_000
        da_12m = (s.parsed.informative.da_12m or 0) * fx / 1_000_000
        ebitda_12m = ebit_12m + da_12m
        # BB muestra TTM EBITDA Margin como porcentaje (×100)
        ebitda_ttm_margin = (ebitda_12m / rev_12m * 100) if rev_12m else 0

        # CF period values (todos derivados de acum)
        cfo_pre_adj_p = _derive_period(s, fx, ("cashflow", "cfo_pre_adj"))
        cfo_p         = _derive_period(s, fx, ("cashflow", "cfo"))
        chg_inv_p     = _derive_period(s, fx, ("cashflow", "chg_inventories"))
        chg_recv_p    = _derive_period(s, fx, ("cashflow", "chg_receivables"))
        chg_other_recv_p = _derive_period(s, fx, ("cashflow", "chg_other_receivables"))
        chg_pay_p     = _derive_period(s, fx, ("cashflow", "chg_payables"))
        chg_other_pay_p = _derive_period(s, fx, ("cashflow", "chg_other_payables"))

        capex_ppe_p   = _derive_period(s, fx, ("cashflow", "capex_ppe"))
        capex_intang_p = _derive_period(s, fx, ("cashflow", "capex_intangibles"))
        sales_ppe_p   = _derive_period(s, fx, ("cashflow", "sales_of_ppe"))
        sales_intang_p = _derive_period(s, fx, ("cashflow", "sales_of_intangibles"))
        loss_control_p = _derive_period(s, fx, ("cashflow", "cash_from_loss_of_control"))
        obtain_control_p = _derive_period(s, fx, ("cashflow", "cash_for_obtain_control"))
        cfi_p         = _derive_period(s, fx, ("cashflow", "cfi"))

        debt_issued_p = _derive_period(s, fx, ("cashflow", "debt_issued"))
        debt_repaid_p = _derive_period(s, fx, ("cashflow", "debt_repaid"))
        dividends_p   = _derive_period(s, fx, ("cashflow", "dividends_paid"))
        lease_pmt_p   = _derive_period(s, fx, ("cashflow", "lease_payments_cf"))
        int_paid_fin_p = _derive_period(s, fx, ("cashflow", "interest_paid_financing"))
        cff_p         = _derive_period(s, fx, ("cashflow", "cff"))

        int_paid_cfo_p = _derive_period(s, fx, ("cashflow", "interest_paid_cfo"))
        int_recv_p    = _derive_period(s, fx, ("cashflow", "interest_received_cfo"))
        int_recv_cfi_p = _derive_period(s, fx, ("cashflow", "interest_received_in_cfi"))
        taxes_paid_p  = _derive_period(s, fx, ("cashflow", "taxes_paid_cfo"))

        fx_effect_p   = _derive_period(s, fx, ("cashflow", "fx_effect_on_cash"))
        net_chg_cash_p = _derive_period(s, fx, ("cashflow", "net_change_cash"))

        # Shares y precio (para per-share metrics)
        shares = (s.parsed.informative.shares_outstanding or 0) / 1_000_000  # ya en unidades; pasar a M
        market_price = 0.0   # No tenemos precio en parser; placeholder

        metrics = _compute_cf_metrics(
            s, fx, ticker=ticker,
            ni_period=ni_period,
            da_period=da_period,
            ebit_period=ebit_period,
            tax_expense_period=tax_exp_p,
            ebitda_ttm_margin=ebitda_ttm_margin,
            cfo_pre_adj_p=cfo_pre_adj_p,
            cfo_p=cfo_p,
            chg_inv_p=chg_inv_p,
            chg_recv_p=chg_recv_p,
            chg_other_recv_p=chg_other_recv_p,
            chg_pay_p=chg_pay_p,
            chg_other_pay_p=chg_other_pay_p,
            capex_ppe_p=capex_ppe_p,
            capex_intang_p=capex_intang_p,
            sales_ppe_p=sales_ppe_p,
            sales_intang_p=sales_intang_p,
            loss_control_p=loss_control_p,
            obtain_control_p=obtain_control_p,
            cfi_p=cfi_p,
            debt_issued_p=debt_issued_p,
            debt_repaid_p=debt_repaid_p,
            dividends_p=dividends_p,
            lease_pmt_p=lease_pmt_p,
            int_paid_fin_p=int_paid_fin_p,
            int_paid_cfo_p=int_paid_cfo_p,
            int_recv_p=int_recv_p,
            int_recv_cfi_p=int_recv_cfi_p,
            taxes_paid_p=taxes_paid_p,
            cff_p=cff_p,
            fx_effect_p=fx_effect_p,
            net_chg_cash_p=net_chg_cash_p,
            shares=shares,
            market_price=market_price,
            tax_rate=0.30,
        )

        col_vals = []
        for label, key, kind in BLOOMBERG_CF_LAYOUT:
            if key is None or kind in ("spacer", "section"):
                col_vals.append(None)
            else:
                col_vals.append(metrics.get(key))
        cols_data[s.label] = col_vals

    df = pd.DataFrame(cols_data, index=labels)
    return df, kinds
