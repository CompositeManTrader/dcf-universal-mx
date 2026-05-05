"""
Auto-calculo de inputs DCF a partir del historial parseado.

En lugar de pedir al analista que adivine valores Damodaran-style
(sales_to_capital, terminal_roic, etc), este modulo calcula el valor
HISTORICO real de cada input desde los XBRL parseados.

Devuelve un objeto InputSuggestion con:
- value_suggested: el numero recomendado
- value_breakdown: tabla año a año del calculo
- formula: explicacion textual
- explanation: que significa el numero en plain Spanish
- damodaran_default: valor Damodaran-style (referencia)
- sector_benchmark: opcional, valor de Damodaran industry table

Uso:
    from src.dcf_mexico.analysis.dcf_inputs_auto import compute_all_input_suggestions
    suggestions = compute_all_input_suggestions(series)
    s2c = suggestions['sales_to_capital']
    print(s2c.value_suggested)        # 0.74
    print(s2c.value_breakdown)         # DataFrame año a año
    print(s2c.explanation)             # "Por cada peso..."
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import statistics
import pandas as pd


@dataclass
class InputSuggestion:
    """Una sugerencia de input para el DCF."""
    name: str
    unit: str                         # "x", "%", "MDP", etc.
    value_suggested: float            # Valor recomendado (mediana del histórico, en general)
    value_method: str                 # "Mediana 5y", "Avg 3y", "Q4 trim YoY", etc.
    formula: str                      # Texto: como se calcula
    explanation: str                  # Plain Spanish: que significa
    interpretation: str               # Que valores son buenos/malos
    breakdown: Optional[pd.DataFrame] = None  # Tabla año a año
    damodaran_default: Optional[float] = None
    damodaran_default_note: str = ""
    sector_benchmark: Optional[float] = None
    sector_note: str = ""
    warnings: List[str] = field(default_factory=list)  # Issues detectados


# ==========================================================================
# 1. SALES-TO-CAPITAL ratio historico
# ==========================================================================

def compute_sales_to_capital(series, fx_mult: float = 1.0,
                                use_annual: bool = True) -> InputSuggestion:
    """Calcula Sales-to-Capital año a año desde el historial.

    S2C_t = ΔRevenue_t / (CapEx_t + ΔWorking_Capital_t)
        ΔRevenue_t      = Revenue_t - Revenue_{t-1}
        CapEx_t         = CapEx PPE + CapEx Intangibles  (de cashflow)
        ΔWorking_Cap_t  = WC_t - WC_{t-1}
                          WC_t = AR + Inventory - AP

    Si annual_use=True usa snapshots Q4 acum (FY); si no usa snapshots Q4
    también pero CapEx ajustado.
    """
    snapshots = series.annual if use_annual else series.snapshots

    if len(snapshots) < 2:
        return InputSuggestion(
            name="Sales-to-Capital",
            unit="x",
            value_suggested=1.50,
            value_method="Default Damodaran",
            formula="ΔRevenue / (CapEx + ΔWC)",
            explanation="No hay historia suficiente para calcular. Usando default 1.50.",
            interpretation="N/A",
            warnings=["Insuficiente data: <2 periodos anuales"],
        )

    rows = []
    valid_years = []
    for i in range(1, len(snapshots)):
        cur = snapshots[i]
        prev = snapshots[i - 1]
        cur_p = cur.parsed
        prev_p = prev.parsed

        # Revenue
        rev_cur = (cur_p.income.revenue or 0) * fx_mult
        rev_prev = (prev_p.income.revenue or 0) * fx_mult
        delta_rev = rev_cur - rev_prev

        # CapEx total (PPE + Intangibles, de cashflow acum FY)
        capex_ppe = (cur_p.cashflow.capex_ppe or 0) * fx_mult
        capex_intang = (cur_p.cashflow.capex_intangibles or 0) * fx_mult
        capex_total = capex_ppe + capex_intang

        # Working Capital = AR + Inventory - AP (operativo)
        wc_cur = ((cur_p.balance.accounts_receivable or 0)
                  + (cur_p.balance.inventories or 0)
                  - (cur_p.balance.accounts_payable or 0)) * fx_mult
        wc_prev = ((prev_p.balance.accounts_receivable or 0)
                   + (prev_p.balance.inventories or 0)
                   - (prev_p.balance.accounts_payable or 0)) * fx_mult
        delta_wc = wc_cur - wc_prev

        denom = capex_total + delta_wc

        # Solo calcular S2C si AMBOS numerador y denominador son sensibles
        if denom > 0:
            s2c_calc = delta_rev / denom
            valid = (delta_rev > 0)  # solo años donde revenue creció
        else:
            s2c_calc = None
            valid = False

        rows.append({
            "Year": cur.year,
            "Revenue": round(rev_cur / 1e6, 1),      # MDP
            "ΔRevenue": round(delta_rev / 1e6, 1),
            "CapEx": round(capex_total / 1e6, 1),
            "ΔWC": round(delta_wc / 1e6, 1),
            "Denominator (CapEx+ΔWC)": round(denom / 1e6, 1),
            "S2C": round(s2c_calc, 4) if s2c_calc is not None else "N/A",
            "Válido": "✅" if valid else "⚠️",
        })
        if valid:
            valid_years.append(s2c_calc)

    breakdown = pd.DataFrame(rows)

    # Sugerencia: mediana de años válidos (ignora outliers)
    warnings = []
    if not valid_years:
        suggested = 1.50
        method = "Default Damodaran (sin años válidos)"
        warnings.append("Ningún año tuvo ΔRevenue > 0 y denom > 0")
    elif len(valid_years) == 1:
        suggested = valid_years[0]
        method = f"Único año válido (Y={breakdown[breakdown['Válido']=='✅']['Year'].iloc[0]})"
        warnings.append("Solo 1 año válido — alta varianza posible")
    else:
        suggested = statistics.median(valid_years)
        method = f"Mediana de {len(valid_years)} años válidos"
        # Detectar outliers
        if max(valid_years) / min(valid_years) > 5:
            warnings.append(
                f"Alta varianza: min={min(valid_years):.2f}x max={max(valid_years):.2f}x. "
                "Considera promedio recortado o usar valor sectorial."
            )

    explanation = (
        "**Sales-to-Capital (S2C)** mide cuántos pesos de venta nueva genera cada peso "
        "de capital invertido (CapEx + ΔWC). Es la 'eficiencia de inversión'. "
        "Una empresa con S2C = 2.0x necesita $0.50 de capital para generar $1.00 de venta nueva. "
        "Una con S2C = 0.5x necesita $2.00 de capital — es más capital intensivo."
    )

    interpretation = (
        "**Rangos típicos:**\n"
        "- **>3.0x:** Capital-light (software, retail asset-light)\n"
        "- **1.5-3.0x:** Promedio (consumo, manufactura ligera)\n"
        "- **0.5-1.5x:** Capital-intensive (bebidas premium con aging, manufactura pesada)\n"
        "- **<0.5x:** Muy intensivo (telecom, utilities, oil&gas)\n\n"
        "**Tequila (CUERVO)** suele estar 0.5-1.0x por inventario añejado 3-5 años."
    )

    # Sector benchmark Damodaran "Beverage Alcoholic" (US tablas Jan-2024)
    # Fuente: pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/capex.html
    SECTOR_S2C_BEVERAGE_ALC = 1.85  # US industry avg
    SECTOR_S2C_BEVERAGE_SOFT = 1.77  # KO, PEP

    return InputSuggestion(
        name="Sales-to-Capital (S2C)",
        unit="x",
        value_suggested=round(suggested, 2),
        value_method=method,
        formula="S2C_t = ΔRevenue_t / (CapEx_t + ΔWorking_Capital_t)\n"
                "donde:\n"
                "  ΔRevenue_t = Revenue_t - Revenue_{t-1}\n"
                "  CapEx_t = CapEx_PPE + CapEx_Intangibles\n"
                "  ΔWC_t = WC_t - WC_{t-1};  WC = AR + Inv - AP",
        explanation=explanation,
        interpretation=interpretation,
        breakdown=breakdown,
        damodaran_default=1.50,
        damodaran_default_note="Default genérico Damodaran",
        sector_benchmark=SECTOR_S2C_BEVERAGE_ALC,
        sector_note="Beverage (Alcoholic) — Damodaran US industry avg Jan-2024 = 1.85x",
        warnings=warnings,
    )


# ==========================================================================
# 2. REVENUE GROWTH (Y1 + Y2-Y5)
# ==========================================================================

def compute_revenue_growth(series, fx_mult: float = 1.0) -> Dict[str, InputSuggestion]:
    """Devuelve sugerencias para revenue_growth_y1 y revenue_growth_high (Y2-Y5)."""
    snapshots = series.annual
    if len(snapshots) < 2:
        return {}

    # YoY anual histórico
    rows = []
    yoys = []
    for i in range(1, len(snapshots)):
        cur = snapshots[i]
        prev = snapshots[i - 1]
        rev_cur = (cur.parsed.income.revenue or 0)
        rev_prev = (prev.parsed.income.revenue or 0)
        if rev_prev > 0:
            yoy = (rev_cur - rev_prev) / rev_prev
        else:
            yoy = 0
        rows.append({
            "Year": cur.year,
            "Revenue (MDP)": round(rev_cur * fx_mult / 1e6, 1),
            "Prior Revenue": round(rev_prev * fx_mult / 1e6, 1),
            "YoY Growth": round(yoy, 4),
        })
        yoys.append(yoy)

    breakdown = pd.DataFrame(rows)

    # Y1 = último YoY observado (más reciente)
    y1_growth = yoys[-1] if yoys else 0
    # Y2-Y5 = mediana de los últimos 3-5 años (ex-Y1 si querer)
    if len(yoys) >= 3:
        y2y5_growth = statistics.median(yoys[-min(5, len(yoys)):])
        y2y5_method = f"Mediana últimos {min(5, len(yoys))} años"
    elif len(yoys) >= 1:
        y2y5_growth = sum(yoys) / len(yoys)
        y2y5_method = f"Promedio {len(yoys)} años"
    else:
        y2y5_growth = 0.05
        y2y5_method = "Default 5%"

    sug_y1 = InputSuggestion(
        name="Revenue Growth Y1",
        unit="%",
        value_suggested=round(y1_growth * 100, 2),  # como %
        value_method="Último YoY anual observado",
        formula="Y1_growth = (Rev_curr - Rev_prev) / Rev_prev",
        explanation="Crecimiento de ventas para el PRIMER año del forecast. "
                    "Damodaran lo separa del crecimiento de Y2-Y5 porque el "
                    "primer año suele tener más visibilidad (guidance, momentum reciente).",
        interpretation="Comparar con consensus de analistas y guidance de la empresa. "
                       "Si Y1 > Y2-Y5: empresa en aceleración. Si Y1 < Y2-Y5: contracción temporal "
                       "esperando rebote.",
        breakdown=breakdown,
        damodaran_default=None,
        sector_benchmark=None,
    )

    sug_y2y5 = InputSuggestion(
        name="Revenue Growth Y2-Y5 (compounded)",
        unit="%",
        value_suggested=round(y2y5_growth * 100, 2),
        value_method=y2y5_method,
        formula="Y2-Y5 = mediana(YoY últimos 3-5 años)",
        explanation="Crecimiento ANUAL COMPOUNDED durante años 2 a 5 (high-growth phase). "
                    "Después fade lineal hasta terminal.",
        interpretation="Empresas maduras (KO, CUERVO): 3-7%. Crecimiento (AAPL, MSFT): 8-15%. "
                       "Hyper-growth (NVDA): 20%+. Si supera consensus largo plazo, justificar.",
        breakdown=breakdown,
        damodaran_default=None,
        sector_benchmark=None,
    )

    return {"revenue_growth_y1": sug_y1, "revenue_growth_y2y5": sug_y2y5}


# ==========================================================================
# 3. OPERATING MARGIN (Y1 + target)
# ==========================================================================

def compute_op_margin(series, fx_mult: float = 1.0) -> Dict[str, InputSuggestion]:
    """Sugerencias para op_margin_y1 (current) y target_op_margin (peak histórico o promedio)."""
    snapshots = series.annual
    if not snapshots:
        return {}

    rows = []
    margins = []
    for s in snapshots:
        rev = (s.parsed.income.revenue or 0)
        ebit = (s.parsed.income.ebit or 0)
        if rev > 0:
            m = ebit / rev
            margins.append(m)
        else:
            m = 0
        rows.append({
            "Year": s.year,
            "Revenue (MDP)": round(rev * fx_mult / 1e6, 1),
            "EBIT (MDP)": round(ebit * fx_mult / 1e6, 1),
            "Op Margin": round(m, 4),
        })

    breakdown = pd.DataFrame(rows)

    # Y1 = margin actual (último año)
    current_margin = margins[-1] if margins else 0.20
    # Target = promedio histórico O peak (mejor de ambos: mediana)
    if len(margins) >= 3:
        target_margin = statistics.median(margins)
        target_method = f"Mediana {len(margins)} años (más robusto que promedio)"
    else:
        target_margin = current_margin
        target_method = "Sin historia: usa current"

    sug_y1 = InputSuggestion(
        name="Operating Margin Y1",
        unit="%",
        value_suggested=round(current_margin * 100, 2),
        value_method="Margin del último FY",
        formula="Op_Margin = EBIT / Revenue",
        explanation="Margen operativo actual de la empresa. Normalmente Y1 mantiene "
                    "el margin actual (no es realista predecir mejora inmediata).",
        interpretation="Comparar con sector. Si current_margin << peers: oportunidad de mejora. "
                       "Si >> peers: posible margin compression futura.",
        breakdown=breakdown,
    )

    sug_target = InputSuggestion(
        name="Target Operating Margin (Y_convergence)",
        unit="%",
        value_suggested=round(target_margin * 100, 2),
        value_method=target_method,
        formula="Target = mediana(historia) o peak observado",
        explanation="Margen al que converge la empresa en estado estable (Y5 default). "
                    "Damodaran sugiere el promedio sectorial o el peak histórico de la empresa.",
        interpretation="Si target > current: thesis es de margin expansion (justificar con palancas). "
                       "Si target = current: 'steady state'. Si target < current: contracción esperada.",
        breakdown=breakdown,
    )

    return {"op_margin_y1": sug_y1, "op_margin_target": sug_target}


# ==========================================================================
# 4. EFFECTIVE TAX RATE
# ==========================================================================

def compute_effective_tax_rate(series, fx_mult: float = 1.0) -> InputSuggestion:
    """Tax rate efectiva histórica."""
    snapshots = series.annual
    rows = []
    rates = []
    for s in snapshots:
        pbt = s.parsed.income.pretax_income or 0
        tax = s.parsed.income.tax_expense or 0
        if pbt > 0:
            rate = tax / pbt
            if 0 <= rate <= 0.50:
                rates.append(rate)
        else:
            rate = 0
        rows.append({
            "Year": s.year,
            "PBT (MDP)": round(pbt * fx_mult / 1e6, 1),
            "Tax Expense (MDP)": round(tax * fx_mult / 1e6, 1),
            "Effective Tax %": round(rate, 4),
        })

    breakdown = pd.DataFrame(rows)

    if rates:
        suggested = statistics.median(rates)
        method = f"Mediana {len(rates)} años válidos (excluye outliers <0% o >50%)"
    else:
        suggested = 0.27
        method = "Default Mexico (entre 25-30%)"

    return InputSuggestion(
        name="Effective Tax Rate",
        unit="%",
        value_suggested=round(suggested * 100, 2),
        value_method=method,
        formula="Effective_Tax = Tax_Expense / Pretax_Income",
        explanation="Tasa de impuestos efectiva REAL (no la marginal). En Mexico la marginal "
                    "es 30% pero efectiva varía 25-32% por créditos fiscales y deferred tax.",
        interpretation="Damodaran sugiere usar effective hoy y fade gradual a marginal en Y10 "
                       "(asumiendo que créditos fiscales se agotan).",
        breakdown=breakdown,
        damodaran_default=0.30,
        damodaran_default_note="Marginal MX = 30%",
    )


# ==========================================================================
# 5. PROBABILITY OF FAILURE (heuristica)
# ==========================================================================

def compute_probability_of_failure(series) -> InputSuggestion:
    """Estima probabilidad de quiebra basado en señales del balance.

    Heuristica simple Damodaran-style:
    - Net Debt/EBITDA > 4 + Interest Coverage < 2 → 5-10% prob
    - Net Debt/EBITDA > 6 + Interest Coverage < 1 → 15-25% prob
    - Año con perdida operativa → +2% por año
    - Cash < 1 año de gastos OpEx → +5%
    """
    if not series.annual:
        return InputSuggestion(
            name="Probability of Failure",
            unit="%",
            value_suggested=0.0,
            value_method="Default Damodaran",
            formula="Heurística leverage + coverage",
            explanation="Sin data suficiente.",
            interpretation="0% para empresas sanas",
        )

    last = series.annual[-1]
    inc = last.parsed.income
    bs = last.parsed.balance
    inf = last.parsed.informative

    debt = bs.total_debt_with_leases
    cash = bs.cash or 0
    net_debt = debt - cash
    ebit = inc.ebit or 0
    ebitda = ebit + (inf.da_12m or 0)
    int_exp = abs(inc.interest_expense or 0)

    nd_ebitda = net_debt / ebitda if ebitda > 0 else 99
    coverage = ebit / int_exp if int_exp > 0 else 99

    # Score heuristico
    prob = 0.0
    factors = []
    if nd_ebitda > 6 and coverage < 1:
        prob = 0.20
        factors.append(f"Net Debt/EBITDA = {nd_ebitda:.1f}x (alto) + Coverage = {coverage:.1f}x (bajo)")
    elif nd_ebitda > 4 and coverage < 2:
        prob = 0.05
        factors.append(f"Net Debt/EBITDA = {nd_ebitda:.1f}x + Coverage = {coverage:.1f}x")
    else:
        factors.append(f"Net Debt/EBITDA = {nd_ebitda:.2f}x (saludable)")
        factors.append(f"Interest Coverage = {coverage:.2f}x (saludable)")

    # Penalizar por años con perdida operativa
    losses = sum(1 for s in series.annual if (s.parsed.income.ebit or 0) < 0)
    if losses > 0:
        prob += 0.02 * losses
        factors.append(f"{losses} años con pérdida operativa → +{losses*2}%")

    interp_lines = ["**Comparación contexto:**",
                    "- Empresas IPC mediana: 0-2%",
                    "- Bonos investment grade (BBB+): 0.5-2% por año",
                    "- High Yield (BB/B): 3-8%",
                    "- Distressed (CCC): 15-30%"]

    return InputSuggestion(
        name="Probability of Failure",
        unit="%",
        value_suggested=round(prob * 100, 2),
        value_method="Heurística leverage + coverage + historial pérdidas",
        formula="Score(Net Debt/EBITDA, Interest Coverage, años con loss)",
        explanation="Probabilidad anual de que la empresa quiebre o sea reestructurada. "
                    "Damodaran #3 default = 0% para empresas establecidas.",
        interpretation="\n".join(interp_lines),
        breakdown=pd.DataFrame([{"Factor": f} for f in factors]),
        damodaran_default=0.0,
        damodaran_default_note="0% para empresas maduras",
    )


# ==========================================================================
# API publica: agregar todas las sugerencias
# ==========================================================================

def compute_all_input_suggestions(series, fx_mult: float = 1.0) -> Dict[str, InputSuggestion]:
    """Calcula TODOS los inputs DCF sugeridos desde el historial."""
    suggestions = {}
    suggestions["sales_to_capital"] = compute_sales_to_capital(series, fx_mult)
    suggestions.update(compute_revenue_growth(series, fx_mult))
    suggestions.update(compute_op_margin(series, fx_mult))
    suggestions["effective_tax_rate"] = compute_effective_tax_rate(series, fx_mult)
    suggestions["probability_of_failure"] = compute_probability_of_failure(series)
    return suggestions
