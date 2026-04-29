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
