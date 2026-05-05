"""
Auto-validador de inputs DCF (la 'lección Damodaran' automatizada).

Para CADA input del DCF:
1. Calcula HISTORICO de la empresa (de los XBRL parseados)
2. Compara contra BENCHMARK SECTORIAL (Damodaran tables)
3. Asigna QUALITY SCORE al input del usuario (verde/amarillo/rojo)
4. Genera RANGOS Bear/Base/Bull justificados
5. Genera NARRATIVA estructurada con evidencia

Uso:
    from src.dcf_mexico.analysis import validate_all_inputs, ScenarioSet

    validations = validate_all_inputs(series, ticker='CUERVO',
                                        user_inputs={'revenue_growth_y1': 0.05, ...})
    for v in validations:
        print(v.name, v.quality_score, v.rationale)
        print(v.bear_value, v.base_value, v.bull_value)

    scenarios = generate_scenarios(series, 'CUERVO', user_drivers)
    print(scenarios.bear_value_share, scenarios.base_value_share, scenarios.bull_value_share)
    print(scenarios.weighted_expected_value)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from enum import Enum
import statistics
import pandas as pd

from .sector_benchmarks import get_sector, SectorBenchmark
from .dcf_inputs_auto import (
    compute_sales_to_capital,
    compute_revenue_growth,
    compute_op_margin,
    compute_effective_tax_rate,
)


class QualityScore(Enum):
    """Score de calidad del input vs histórico + sector."""
    EXCELLENT = "✅ Excellent"          # Muy bien justificado por hist+sector
    DEFENSIBLE = "✅ Defensible"        # Dentro de rangos razonables
    AGGRESSIVE = "🟡 Aggressive"        # Optimista pero no irracional
    OPTIMISTIC = "🔴 Optimistic"        # Muy por arriba de hist+sector
    PESSIMISTIC = "🔴 Pessimistic"      # Muy por debajo de hist+sector
    NO_DATA = "⚪ No Data"              # No hay como validar


@dataclass
class InputValidation:
    """Validacion completa de un input DCF."""
    name: str                          # "Revenue Growth Y1", etc.
    unit: str                          # "%", "x", etc.

    # User input (lo que el usuario escogio)
    user_value: Optional[float]

    # Reference values
    historical_value: Optional[float]      # mediana / promedio histórico
    historical_method: str                 # "mediana 4y", "ultimo YoY"
    sector_value: Optional[float]          # benchmark sectorial Damodaran
    sector_method: str                     # "p25-p75 sector"

    # 3-scenario suggestions (auto-generated)
    bear_value: float
    base_value: float
    bull_value: float

    # Quality assessment
    quality_score: QualityScore
    rationale: str                         # Narrativa estructurada
    warnings: List[str] = field(default_factory=list)

    # Breakdowns
    historical_breakdown: Optional[pd.DataFrame] = None


# ============================================================================
# Helpers
# ============================================================================

def _classify_user_input(user: Optional[float], hist: Optional[float],
                         sector: Optional[float], lower: float, upper: float) -> QualityScore:
    """Clasifica el input del usuario en quality score."""
    if user is None:
        return QualityScore.NO_DATA
    if hist is None and sector is None:
        return QualityScore.NO_DATA

    # Comparacion vs rango razonable [lower, upper] (definido por hist & sector)
    if user < lower * 0.7:
        return QualityScore.PESSIMISTIC
    if user > upper * 1.3:
        return QualityScore.OPTIMISTIC
    if user < lower:
        return QualityScore.AGGRESSIVE  # algo bajo
    if user > upper:
        return QualityScore.AGGRESSIVE
    # Dentro del rango
    if hist is not None and abs(user - hist) / max(abs(hist), 0.01) < 0.10:
        return QualityScore.EXCELLENT
    return QualityScore.DEFENSIBLE


# ============================================================================
# Validadores por input
# ============================================================================

def _validate_revenue_growth_y1(series, ticker: str,
                                  user_value: Optional[float] = None) -> InputValidation:
    """Revenue Growth Y1 (% decimal)."""
    sector = get_sector(ticker)
    growth_data = compute_revenue_growth(series)
    hist_y1_sug = growth_data.get('revenue_growth_y1') if growth_data else None
    hist_value = hist_y1_sug.value_suggested / 100 if hist_y1_sug else None  # convertir a decimal

    sector_value = sector.revenue_growth_high_period if sector else None

    # Rangos: bear = mín(hist, sector_p25), bull = máx(hist, sector_p75)
    if sector:
        sector_low = sector.revenue_growth_secular * 0.5    # half de secular
        sector_high = sector.revenue_growth_high_period * 1.4
    else:
        sector_low = sector_high = None

    # Calcular Bear/Base/Bull
    if hist_value is not None and sector_value is not None:
        bear = min(hist_value, (sector_low or 0) - 0.01)
        bull = max(sector.revenue_growth_high_period * 1.2, 0.07)
        base = (hist_value + sector_value) / 2
    elif hist_value is not None:
        bear = hist_value - 0.02
        base = hist_value
        bull = hist_value + 0.04
    elif sector_value is not None:
        bear = sector.revenue_growth_secular - 0.02
        base = sector.revenue_growth_secular
        bull = sector.revenue_growth_high_period + 0.02
    else:
        bear, base, bull = -0.02, 0.05, 0.10

    # Quality classification
    quality = _classify_user_input(
        user_value, hist_value, sector_value,
        lower=bear, upper=bull
    )

    # Narrativa
    rationale_lines = []
    if hist_value is not None:
        rationale_lines.append(
            f"📊 **Histórico:** Último YoY observado = {hist_value*100:+.1f}%"
        )
    if sector:
        rationale_lines.append(
            f"🏭 **Sector ({sector.sector_name_es}):** "
            f"Damodaran 5y growth proyectado = {sector.revenue_growth_high_period*100:.1f}%, "
            f"secular = {sector.revenue_growth_secular*100:.1f}%"
        )
    rationale_lines.append(
        f"🎯 **Rangos sugeridos:** Bear {bear*100:+.1f}%, "
        f"Base {base*100:+.1f}%, Bull {bull*100:+.1f}%"
    )
    if user_value is not None:
        if user_value > bull:
            rationale_lines.append(
                f"⚠️ Tu input ({user_value*100:+.1f}%) es **mayor que Bull case** "
                f"({bull*100:+.1f}%) — ¿qué evidencia justifica este crecimiento?"
            )
        elif user_value < bear:
            rationale_lines.append(
                f"⚠️ Tu input ({user_value*100:+.1f}%) es **menor que Bear case** "
                f"({bear*100:+.1f}%) — asumes deterioro estructural"
            )

    warnings = []
    if hist_value is not None and hist_value < 0 and user_value is not None and user_value > 0.05:
        warnings.append(
            f"Empresa en declive (-{abs(hist_value)*100:.1f}% YoY) pero tu Y1 asume "
            f"recovery a {user_value*100:+.1f}%. Justifica con catalysts."
        )

    return InputValidation(
        name="Revenue Growth Y1",
        unit="%",
        user_value=user_value,
        historical_value=hist_value,
        historical_method="Último YoY anual observado",
        sector_value=sector_value,
        sector_method=f"Damodaran 5y projected ({sector.sector_name_es})" if sector else "N/A",
        bear_value=bear, base_value=base, bull_value=bull,
        quality_score=quality,
        rationale="\n\n".join(rationale_lines),
        warnings=warnings,
        historical_breakdown=hist_y1_sug.breakdown if hist_y1_sug else None,
    )


def _validate_revenue_growth_y2y5(series, ticker: str,
                                    user_value: Optional[float] = None) -> InputValidation:
    """Revenue Growth Y2-Y5 compounded."""
    sector = get_sector(ticker)
    growth_data = compute_revenue_growth(series)
    hist_y2y5_sug = growth_data.get('revenue_growth_y2y5') if growth_data else None
    hist_value = hist_y2y5_sug.value_suggested / 100 if hist_y2y5_sug else None

    sector_value = sector.revenue_growth_high_period if sector else None

    if hist_value is not None and sector_value is not None:
        bear = min(hist_value, sector.revenue_growth_secular * 0.7)
        base = (hist_value + sector_value) / 2
        bull = sector.revenue_growth_high_period * 1.3
    elif hist_value is not None:
        bear = hist_value - 0.02
        base = max(0.02, (hist_value + 0.04) / 2)
        bull = hist_value + 0.05
    elif sector:
        bear = sector.revenue_growth_secular - 0.01
        base = sector.revenue_growth_secular
        bull = sector.revenue_growth_high_period + 0.03
    else:
        bear, base, bull = 0.0, 0.05, 0.10

    quality = _classify_user_input(user_value, hist_value, sector_value, bear, bull)

    rationale_lines = []
    if hist_value is not None:
        rationale_lines.append(f"📊 **Histórico mediana:** {hist_value*100:.1f}%")
    if sector:
        rationale_lines.append(
            f"🏭 **Sector:** secular {sector.revenue_growth_secular*100:.1f}%, "
            f"high period {sector.revenue_growth_high_period*100:.1f}%"
        )
    rationale_lines.append(
        f"🎯 **Sugerido:** Bear {bear*100:+.1f}%, Base {base*100:+.1f}%, Bull {bull*100:+.1f}%"
    )
    rationale_lines.append(
        "💡 **Damodaran:** En Y2-Y5 'high growth period' una empresa NO puede crecer "
        "indefinidamente arriba del growth nominal de la economía."
    )

    warnings = []
    if user_value is not None and user_value > 0.10:
        warnings.append(
            f"Y2-Y5 = {user_value*100:.1f}% es agresivo. Damodaran sugiere cap a "
            f"~7-8% para empresas establecidas."
        )

    return InputValidation(
        name="Revenue Growth Y2-Y5",
        unit="%",
        user_value=user_value,
        historical_value=hist_value,
        historical_method="Mediana últimos 3-5 años",
        sector_value=sector_value,
        sector_method=f"Damodaran high period ({sector.sector_name_es})" if sector else "N/A",
        bear_value=bear, base_value=base, bull_value=bull,
        quality_score=quality,
        rationale="\n\n".join(rationale_lines),
        warnings=warnings,
        historical_breakdown=hist_y2y5_sug.breakdown if hist_y2y5_sug else None,
    )


def _validate_op_margin_target(series, ticker: str,
                                user_value: Optional[float] = None) -> InputValidation:
    """Target Operating Margin (Y_convergence)."""
    sector = get_sector(ticker)
    margin_data = compute_op_margin(series)
    hist_target_sug = margin_data.get('op_margin_target') if margin_data else None
    hist_value = hist_target_sug.value_suggested / 100 if hist_target_sug else None

    sector_value = sector.op_margin_avg if sector else None

    if hist_value is not None and sector:
        bear = min(hist_value, sector.op_margin_p25)
        base = (hist_value + sector.op_margin_avg) / 2
        bull = max(sector.op_margin_p75, hist_value * 1.15)
    elif hist_value:
        bear = hist_value * 0.7
        base = hist_value
        bull = hist_value * 1.30
    elif sector:
        bear = sector.op_margin_p25
        base = sector.op_margin_avg
        bull = sector.op_margin_p75
    else:
        bear, base, bull = 0.10, 0.18, 0.25

    quality = _classify_user_input(user_value, hist_value, sector_value, bear, bull)

    rationale_lines = []
    if hist_value is not None:
        rationale_lines.append(
            f"📊 **Mediana histórica empresa:** {hist_value*100:.1f}%"
        )
    if sector:
        rationale_lines.append(
            f"🏭 **Sector ({sector.sector_name_es}):** "
            f"P25={sector.op_margin_p25*100:.1f}%, "
            f"Mediana={sector.op_margin_avg*100:.1f}%, "
            f"P75={sector.op_margin_p75*100:.1f}%"
        )
    rationale_lines.append(
        f"🎯 **Sugerido:** Bear {bear*100:.1f}%, Base {base*100:.1f}%, Bull {bull*100:.1f}%"
    )
    rationale_lines.append(
        "💡 **Damodaran:** Mean reversion al promedio sectorial es lo más conservador. "
        "Margins fuera del rango sectorial requieren explicación (moat, mix, etc.)."
    )

    warnings = []
    if hist_value and user_value and user_value > hist_value * 1.20:
        warnings.append(
            f"Target {user_value*100:.1f}% es {(user_value/hist_value-1)*100:.0f}% mayor "
            f"que mediana histórica {hist_value*100:.1f}%. Asume mejora estructural."
        )
    if sector and user_value and user_value > sector.op_margin_p75 * 1.10:
        warnings.append(
            f"Target {user_value*100:.1f}% supera el P75 sectorial "
            f"({sector.op_margin_p75*100:.1f}%). Implica que empresa será top-quartile."
        )

    return InputValidation(
        name="Target Operating Margin",
        unit="%",
        user_value=user_value,
        historical_value=hist_value,
        historical_method="Mediana histórica de la empresa",
        sector_value=sector_value,
        sector_method=f"Mediana sector ({sector.sector_name_es})" if sector else "N/A",
        bear_value=bear, base_value=base, bull_value=bull,
        quality_score=quality,
        rationale="\n\n".join(rationale_lines),
        warnings=warnings,
        historical_breakdown=hist_target_sug.breakdown if hist_target_sug else None,
    )


def _validate_sales_to_capital(series, ticker: str,
                                user_value: Optional[float] = None) -> InputValidation:
    """Sales-to-Capital ratio."""
    sector = get_sector(ticker)
    s2c_sug = compute_sales_to_capital(series)
    hist_value = s2c_sug.value_suggested if s2c_sug.value_suggested != 1.50 else None

    sector_value = sector.s2c_avg if sector else None

    if sector:
        bear = sector.s2c_p25
        base = sector.s2c_avg
        bull = sector.s2c_p75
    else:
        bear, base, bull = 1.0, 1.5, 2.5

    # Si historical es válido y razonable, usarlo como base
    if hist_value and 0.3 < hist_value < 5:
        if abs(hist_value - base) / base < 0.30:  # cerca del sector
            base = hist_value

    quality = _classify_user_input(user_value, hist_value, sector_value, bear * 0.85, bull * 1.15)

    rationale_lines = []
    if hist_value:
        rationale_lines.append(f"📊 **Histórico empresa (mediana años validos):** {hist_value:.2f}x")
    elif s2c_sug.warnings:
        rationale_lines.append(
            f"⚠️ **Histórico no calculable:** {'; '.join(s2c_sug.warnings)}"
        )
    if sector:
        rationale_lines.append(
            f"🏭 **Sector ({sector.sector_name_es}):** "
            f"P25={sector.s2c_p25:.2f}x, Mediana={sector.s2c_avg:.2f}x, P75={sector.s2c_p75:.2f}x"
        )
        rationale_lines.append(
            f"📚 **{sector.description[:200]}...**"
        )
    rationale_lines.append(
        f"🎯 **Sugerido:** Bear {bear:.2f}x, Base {base:.2f}x, Bull {bull:.2f}x"
    )
    rationale_lines.append(
        "💡 **Damodaran:** S2C bajo = capital intensivo (más reinversión). "
        "S2C alto = asset-light. Mover S2C de 1.0 a 1.85 puede mover el value/share +30%."
    )

    warnings = []
    if hist_value is None:
        warnings.append(
            "Histórico no calculable (revenue cae). Usando sector benchmark — "
            "considera ajustar manualmente para tu sub-industria."
        )

    return InputValidation(
        name="Sales-to-Capital",
        unit="x",
        user_value=user_value,
        historical_value=hist_value,
        historical_method="Mediana años con ΔRev > 0",
        sector_value=sector_value,
        sector_method=f"Damodaran sector ({sector.sector_name_es})" if sector else "N/A",
        bear_value=bear, base_value=base, bull_value=bull,
        quality_score=quality,
        rationale="\n\n".join(rationale_lines),
        warnings=warnings + s2c_sug.warnings,
        historical_breakdown=s2c_sug.breakdown,
    )


def _validate_beta_unlevered(series, ticker: str,
                              user_value: Optional[float] = None) -> InputValidation:
    """Beta unlevered (sectorial)."""
    sector = get_sector(ticker)

    if sector:
        bear = sector.beta_unlevered_p25
        base = sector.beta_unlevered
        bull = sector.beta_unlevered_p75
        sector_value = sector.beta_unlevered
    else:
        bear, base, bull = 0.6, 0.85, 1.1
        sector_value = None

    quality = _classify_user_input(user_value, None, sector_value, bear * 0.85, bull * 1.15)

    rationale_lines = []
    if sector:
        rationale_lines.append(
            f"🏭 **Sector ({sector.sector_name_es}):** "
            f"P25={sector.beta_unlevered_p25:.2f}, "
            f"Mediana={sector.beta_unlevered:.2f}, "
            f"P75={sector.beta_unlevered_p75:.2f}"
        )
    else:
        rationale_lines.append("⚠️ Sector no identificado para este ticker.")
    rationale_lines.append(
        f"🎯 **Sugerido:** Bear {bear:.2f}, Base {base:.2f}, Bull {bull:.2f}"
    )
    rationale_lines.append(
        "💡 **Damodaran:** Beta unlevered sectorial es más estable que regresión 5y. "
        "Para emisoras MX poco líquidas considera +0.10-0.20 illiquidity premium."
    )

    return InputValidation(
        name="Beta Unlevered",
        unit="",
        user_value=user_value,
        historical_value=None,
        historical_method="N/A — beta sectorial Damodaran",
        sector_value=sector_value,
        sector_method=f"Damodaran sector beta ({sector.sector_name_es})" if sector else "N/A",
        bear_value=bear, base_value=base, bull_value=bull,
        quality_score=quality,
        rationale="\n\n".join(rationale_lines),
        warnings=[],
    )


def _validate_effective_tax(series, ticker: str,
                              user_value: Optional[float] = None) -> InputValidation:
    """Effective tax rate (base year)."""
    sector = get_sector(ticker)
    tax_sug = compute_effective_tax_rate(series)
    hist_value = tax_sug.value_suggested / 100 if tax_sug else None

    sector_value = sector.effective_tax_avg if sector else None

    if hist_value:
        bear = hist_value + 0.02
        base = hist_value
        bull = max(0.20, hist_value - 0.03)
    elif sector:
        bear = sector.effective_tax_avg + 0.02
        base = sector.effective_tax_avg
        bull = sector.effective_tax_avg - 0.02
    else:
        bear, base, bull = 0.30, 0.27, 0.24

    quality = _classify_user_input(user_value, hist_value, sector_value, 0.20, 0.32)

    rationale_lines = []
    if hist_value:
        rationale_lines.append(f"📊 **Mediana histórica empresa:** {hist_value*100:.1f}%")
    if sector:
        rationale_lines.append(
            f"🏭 **Sector ({sector.sector_name_es}):** {sector.effective_tax_avg*100:.1f}%"
        )
    rationale_lines.append("📜 **MX marginal legal:** 30%")
    rationale_lines.append(
        f"🎯 **Sugerido:** Bear {bear*100:.1f}% (alto), Base {base*100:.1f}%, "
        f"Bull {bull*100:.1f}% (créditos fiscales mayor)"
    )
    rationale_lines.append(
        "💡 **Damodaran:** Empezar con effective y fade a marginal Y6-Y10 "
        "(asumiendo créditos fiscales se agotan)."
    )

    return InputValidation(
        name="Effective Tax Rate (Base)",
        unit="%",
        user_value=user_value,
        historical_value=hist_value,
        historical_method="Mediana histórica empresa",
        sector_value=sector_value,
        sector_method=f"Sector promedio ({sector.sector_name_es})" if sector else "N/A",
        bear_value=bear, base_value=base, bull_value=bull,
        quality_score=quality,
        rationale="\n\n".join(rationale_lines),
        warnings=[],
        historical_breakdown=tax_sug.breakdown,
    )


# ============================================================================
# API publica: validar TODOS los inputs
# ============================================================================

def validate_all_inputs(
    series,
    ticker: str,
    user_inputs: Optional[Dict[str, float]] = None,
) -> List[InputValidation]:
    """Devuelve lista de InputValidation para todos los inputs DCF.

    Args:
        series: HistoricalSeries del ticker
        ticker: ticker symbol (para lookup sectorial)
        user_inputs: dict opcional con valores actuales del usuario.
                     Keys: 'revenue_growth_y1', 'revenue_growth_y2y5',
                           'op_margin_target', 'sales_to_capital',
                           'beta_unlevered', 'effective_tax'
    """
    user_inputs = user_inputs or {}

    return [
        _validate_revenue_growth_y1(series, ticker, user_inputs.get('revenue_growth_y1')),
        _validate_revenue_growth_y2y5(series, ticker, user_inputs.get('revenue_growth_y2y5')),
        _validate_op_margin_target(series, ticker, user_inputs.get('op_margin_target')),
        _validate_sales_to_capital(series, ticker, user_inputs.get('sales_to_capital')),
        _validate_beta_unlevered(series, ticker, user_inputs.get('beta_unlevered')),
        _validate_effective_tax(series, ticker, user_inputs.get('effective_tax')),
    ]


# ============================================================================
# Generador de 3 escenarios + Weighted Expected Value
# ============================================================================

@dataclass
class ScenarioOutput:
    """Output de un escenario completo (Bear, Base o Bull)."""
    name: str
    drivers: dict           # los inputs usados
    value_per_share: float  # output del DCF
    upside_pct: float       # vs market price


@dataclass
class ScenarioSet:
    """Conjunto de 3 escenarios + weighted EV."""
    bear: ScenarioOutput
    base: ScenarioOutput
    bull: ScenarioOutput
    p_bear: float = 0.30        # probabilidad escenario bear
    p_base: float = 0.50        # probabilidad escenario base
    p_bull: float = 0.20        # probabilidad escenario bull

    @property
    def weighted_expected_value(self) -> float:
        """Valor esperado ponderado por probabilidades."""
        return (self.p_bear * self.bear.value_per_share
                + self.p_base * self.base.value_per_share
                + self.p_bull * self.bull.value_per_share)

    @property
    def weighted_upside(self) -> float:
        return (self.p_bear * self.bear.upside_pct
                + self.p_base * self.base.upside_pct
                + self.p_bull * self.bull.upside_pct)

    def summary_table(self, market_price: float) -> pd.DataFrame:
        rows = [
            ("Bear (P=30%)",  self.bear.value_per_share,  self.bear.upside_pct),
            ("Base (P=50%)",  self.base.value_per_share,  self.base.upside_pct),
            ("Bull (P=20%)",  self.bull.value_per_share,  self.bull.upside_pct),
            ("Weighted EV",   self.weighted_expected_value, self.weighted_upside),
            ("Market Price",  market_price, 0.0),
        ]
        return pd.DataFrame(rows, columns=["Scenario", "Value/Share", "Upside %"])


def generate_scenarios(series, ticker: str, base_company,
                        market_price: float,
                        p_bear: float = 0.30,
                        p_base: float = 0.50,
                        p_bull: float = 0.20) -> ScenarioSet:
    """Genera los 3 escenarios automaticos basado en validators.

    Args:
        series: HistoricalSeries
        ticker: ticker symbol
        base_company: CompanyBase (con financials actuales)
        market_price: precio de mercado para upside calc
    """
    from src.dcf_mexico.valuation.dcf_fcff import DCFAssumptions, project_company
    from src.dcf_mexico.valuation.wacc import RF_MX_DEFAULT, ERP_MX_DEFAULT, MARGINAL_TAX_MX

    validations = validate_all_inputs(series, ticker)
    by_name = {v.name: v for v in validations}

    def _build_and_run(scenario: str) -> ScenarioOutput:
        if scenario == "bear":
            getter = lambda v: v.bear_value
        elif scenario == "bull":
            getter = lambda v: v.bull_value
        else:
            getter = lambda v: v.base_value

        rev_g_y1 = getter(by_name["Revenue Growth Y1"])
        rev_g_y2y5 = getter(by_name["Revenue Growth Y2-Y5"])
        op_margin_t = getter(by_name["Target Operating Margin"])
        s2c = getter(by_name["Sales-to-Capital"])
        beta_u = getter(by_name["Beta Unlevered"])
        eff_tax = getter(by_name["Effective Tax Rate (Base)"])

        # Op margin Y1 = current
        current_margin = base_company.ebit / base_company.revenue if base_company.revenue > 0 else op_margin_t

        ass = DCFAssumptions(
            country='Mexico',
            revenue_growth_y1=rev_g_y1,
            revenue_growth_high=rev_g_y2y5,
            terminal_growth=0.035,
            op_margin_y1=current_margin,
            target_op_margin=op_margin_t,
            year_of_margin_convergence=5,
            sales_to_capital=s2c,
            effective_tax_base=eff_tax,
            marginal_tax_terminal=MARGINAL_TAX_MX,
            risk_free=RF_MX_DEFAULT,
            erp=ERP_MX_DEFAULT,
            unlevered_beta=beta_u,
            terminal_wacc_override=None,
            market_price=market_price,
            forecast_years=10,
            high_growth_years=5,
            override_terminal_roic=False,
            probability_of_failure=0.0,
        )
        out = project_company(base_company, ass)

        return ScenarioOutput(
            name=scenario.capitalize(),
            drivers={
                "Rev Growth Y1": f"{rev_g_y1*100:+.1f}%",
                "Rev Growth Y2-Y5": f"{rev_g_y2y5*100:+.1f}%",
                "Target Op Margin": f"{op_margin_t*100:.1f}%",
                "Sales-to-Capital": f"{s2c:.2f}x",
                "Beta Unlevered": f"{beta_u:.2f}",
                "Effective Tax": f"{eff_tax*100:.1f}%",
            },
            value_per_share=out.value_per_share,
            upside_pct=out.upside_pct,
        )

    return ScenarioSet(
        bear=_build_and_run("bear"),
        base=_build_and_run("base"),
        bull=_build_and_run("bull"),
        p_bear=p_bear, p_base=p_base, p_bull=p_bull,
    )
