"""
Análisis de TENDENCIAS MULTI-PERIODO (3y, 5y, all-time CAGR + classification).

Más allá del simple YoY, este módulo detecta:
- CAGR (Compound Annual Growth Rate) de 3y / 5y / all-time
- Aceleración o desaceleración (¿el crecimiento se está acelerando?)
- Reversiones de tendencia (mejora->deterioro o vice versa)
- Volatilidad (¿es secular o cíclico?)
- Persistencia (¿N años consecutivos de mejora?)
- Clasificación: secular_growth / cyclical / structural_decline / volatile / transitorio

Uso:
    from src.dcf_mexico.analysis.trends import (
        compute_all_trends, classify_trend, MetricTrend
    )
    trends = compute_all_trends(series)   # historical series
    for t in trends:
        print(t.metric, t.cagr_5y, t.classification, t.narrative)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, Dict, Callable
import statistics
import pandas as pd


# ============================================================================
# Tipos
# ============================================================================

class TrendClassification(Enum):
    SECULAR_GROWTH = "🚀 Secular Growth"           # Crecimiento sostenido + acelerando
    SECULAR_DECLINE = "📉 Secular Decline"         # Caída sostenida + persistente
    STABLE = "⚪ Estable"                           # Cambios mínimos
    CYCLICAL = "🔄 Cíclico"                         # Oscilaciones grandes
    RECOVERY = "📈 Recovery"                        # Recuperándose después de caída
    DETERIORATION = "⚠️ Deterioro"                 # Empeorando consistentemente
    REVERSAL_POSITIVE = "🔄🟢 Reversión Positiva"   # Cambia de bajada a subida
    REVERSAL_NEGATIVE = "🔄🔴 Reversión Negativa"   # Cambia de subida a bajada
    INSUFFICIENT_DATA = "⚪ Datos insuficientes"


class TrendStrength(Enum):
    STRONG = "💪 Fuerte"
    MODERATE = "🟡 Moderada"
    WEAK = "⚪ Débil"


@dataclass
class MetricTrend:
    """Tendencia multi-período de una métrica."""
    metric: str
    category: str                             # Profitability/Growth/Leverage/etc.
    unit: str                                 # %, MDP, x

    # Time series (sorted ASC by year)
    values: List[Tuple[int, float]]           # [(year, value), ...]

    # CAGRs
    cagr_3y: Optional[float] = None           # solo si tenemos 3+ años
    cagr_5y: Optional[float] = None           # solo si tenemos 5+ años
    cagr_all: Optional[float] = None

    # Average / Median absolute change (para metricas con valores negativos)
    avg_yoy_change: Optional[float] = None
    median_yoy_change: Optional[float] = None

    # YoY series
    yoy_changes_pct: List[float] = field(default_factory=list)
    yoy_changes_abs: List[float] = field(default_factory=list)

    # Pattern analysis
    consecutive_improvements: int = 0          # años consecutivos mejorando (al final)
    consecutive_deteriorations: int = 0        # años consecutivos empeorando (al final)
    is_accelerating: bool = False
    is_decelerating: bool = False
    has_reversal: bool = False                 # cambió de signo el trend
    volatility: float = 0.0                    # std dev de YoY %

    # Latest snapshot
    latest_value: float = 0.0
    latest_year: int = 0

    # Classification + narrative
    classification: TrendClassification = TrendClassification.INSUFFICIENT_DATA
    strength: TrendStrength = TrendStrength.WEAK
    narrative: str = ""
    interpretation: str = ""


# ============================================================================
# Helpers
# ============================================================================

def _cagr(start: float, end: float, n_years: int) -> Optional[float]:
    """CAGR = (end/start)^(1/n) - 1. Solo válido si ambos > 0."""
    if start <= 0 or end <= 0 or n_years <= 0:
        return None
    try:
        return (end / start) ** (1.0 / n_years) - 1.0
    except (ZeroDivisionError, ValueError):
        return None


def _yoy_pct(curr: float, prev: float) -> float:
    """YoY % change. 0 si denom == 0."""
    if abs(prev) < 1e-9:
        return 0.0
    return (curr - prev) / abs(prev)


def _is_consistent(values: List[float], threshold_pct: float = 0.02) -> bool:
    """¿Los valores son monotonously crecientes/decrecientes?"""
    if len(values) < 3:
        return False
    diffs = [values[i+1] - values[i] for i in range(len(values)-1)]
    same_sign = all(d > 0 for d in diffs) or all(d < 0 for d in diffs)
    return same_sign


def _build_trend(metric_name: str, category: str, unit: str,
                  series: List[Tuple[int, float]]) -> MetricTrend:
    """Construye un MetricTrend desde la serie temporal."""
    series = sorted(series, key=lambda x: x[0])  # asc por year
    if not series:
        return MetricTrend(
            metric=metric_name, category=category, unit=unit,
            values=[], classification=TrendClassification.INSUFFICIENT_DATA,
        )

    years = [y for y, _ in series]
    values = [v for _, v in series]
    n = len(values)

    trend = MetricTrend(
        metric=metric_name, category=category, unit=unit,
        values=series, latest_value=values[-1], latest_year=years[-1],
    )

    if n < 2:
        trend.classification = TrendClassification.INSUFFICIENT_DATA
        trend.narrative = "Solo 1 año disponible"
        return trend

    # YoY changes
    for i in range(1, n):
        trend.yoy_changes_abs.append(values[i] - values[i-1])
        trend.yoy_changes_pct.append(_yoy_pct(values[i], values[i-1]))

    # CAGRs
    if n >= 4:  # >= 3 años + 1
        trend.cagr_3y = _cagr(values[-4], values[-1], 3)
    if n >= 6:
        trend.cagr_5y = _cagr(values[-6], values[-1], 5)
    trend.cagr_all = _cagr(values[0], values[-1], n - 1)

    # Average and median YoY
    if trend.yoy_changes_pct:
        trend.avg_yoy_change = statistics.mean(trend.yoy_changes_pct)
        trend.median_yoy_change = statistics.median(trend.yoy_changes_pct)

    # Volatility (std dev of YoY)
    if len(trend.yoy_changes_pct) >= 2:
        trend.volatility = statistics.stdev(trend.yoy_changes_pct)

    # Consecutive improvements/deteriorations al final
    consec_imp = 0
    consec_det = 0
    for diff in reversed(trend.yoy_changes_abs):
        if diff > 0:
            if consec_det > 0: break
            consec_imp += 1
        elif diff < 0:
            if consec_imp > 0: break
            consec_det += 1
        else:
            break
    trend.consecutive_improvements = consec_imp
    trend.consecutive_deteriorations = consec_det

    # Aceleración: comparar growth de últimos 2 años vs últimos 4-5
    if len(trend.yoy_changes_pct) >= 4:
        recent = statistics.mean(trend.yoy_changes_pct[-2:])
        prior = statistics.mean(trend.yoy_changes_pct[-4:-2])
        if recent > prior + 0.02:
            trend.is_accelerating = True
        elif recent < prior - 0.02:
            trend.is_decelerating = True

    # Reversal: ¿el último año tiene signo opuesto al promedio prior?
    if len(trend.yoy_changes_pct) >= 3:
        prior_avg = statistics.mean(trend.yoy_changes_pct[:-1])
        last = trend.yoy_changes_pct[-1]
        if (prior_avg < -0.02 and last > 0.02) or (prior_avg > 0.02 and last < -0.02):
            trend.has_reversal = True

    # Classification
    trend.classification, trend.strength = _classify(trend)
    trend.narrative, trend.interpretation = _narrate(trend)
    return trend


def _classify(trend: MetricTrend) -> Tuple[TrendClassification, TrendStrength]:
    """Clasifica la tendencia."""
    if not trend.yoy_changes_pct:
        return TrendClassification.INSUFFICIENT_DATA, TrendStrength.WEAK

    avg = trend.avg_yoy_change or 0
    vol = trend.volatility
    consec_imp = trend.consecutive_improvements
    consec_det = trend.consecutive_deteriorations

    # Strength
    if abs(avg) > 0.10:
        strength = TrendStrength.STRONG
    elif abs(avg) > 0.03:
        strength = TrendStrength.MODERATE
    else:
        strength = TrendStrength.WEAK

    # Reversals primero (toman precedencia)
    if trend.has_reversal:
        last = trend.yoy_changes_pct[-1]
        if last > 0:
            return TrendClassification.REVERSAL_POSITIVE, strength
        else:
            return TrendClassification.REVERSAL_NEGATIVE, strength

    # Recovery: bajadas previas + ahora subiendo
    prior_avg = (statistics.mean(trend.yoy_changes_pct[:-1])
                 if len(trend.yoy_changes_pct) > 1 else 0)
    if prior_avg < -0.02 and consec_imp >= 2:
        return TrendClassification.RECOVERY, strength

    # Secular growth: avg positivo + persistencia
    if avg > 0.05 and consec_imp >= 2:
        return TrendClassification.SECULAR_GROWTH, strength

    # Secular decline: avg negativo + persistencia
    if avg < -0.05 and consec_det >= 2:
        return TrendClassification.SECULAR_DECLINE, strength

    # Deterioration: deteriorando consistentemente últimos años
    if consec_det >= 3:
        return TrendClassification.DETERIORATION, strength

    # Volatil: alta volatilidad
    if vol > 0.20:
        return TrendClassification.CYCLICAL, strength

    # Estable
    if abs(avg) < 0.02:
        return TrendClassification.STABLE, TrendStrength.WEAK

    # Default
    if avg > 0:
        return TrendClassification.SECULAR_GROWTH, strength
    elif avg < 0:
        return TrendClassification.SECULAR_DECLINE, strength
    return TrendClassification.STABLE, TrendStrength.WEAK


def _narrate(trend: MetricTrend) -> Tuple[str, str]:
    """Genera narrativa + interpretación."""
    n = len(trend.values)
    if n < 2:
        return "Insuficiente data", "Necesitas más historia"

    avg = trend.avg_yoy_change or 0
    cls = trend.classification
    cagr_text = ""
    if trend.cagr_5y is not None:
        cagr_text = f" CAGR 5y: {trend.cagr_5y*100:+.1f}%"
    elif trend.cagr_3y is not None:
        cagr_text = f" CAGR 3y: {trend.cagr_3y*100:+.1f}%"
    elif trend.cagr_all is not None:
        cagr_text = f" CAGR {n-1}y: {trend.cagr_all*100:+.1f}%"

    accel_text = ""
    if trend.is_accelerating:
        accel_text = " 🚀 ACELERANDO"
    elif trend.is_decelerating:
        accel_text = " 📉 DESACELERANDO"

    persist_text = ""
    if trend.consecutive_improvements >= 2:
        persist_text = f" ({trend.consecutive_improvements}y consecutivos mejorando)"
    elif trend.consecutive_deteriorations >= 2:
        persist_text = f" ({trend.consecutive_deteriorations}y consecutivos cayendo)"

    narrative = (
        f"{cls.value}.{cagr_text}{accel_text}{persist_text} "
        f"Volatilidad: {trend.volatility*100:.1f}%."
    )

    # Interpretation
    interps = {
        TrendClassification.SECULAR_GROWTH: (
            "Trend secular positivo - empresa crece consistentemente. "
            "Si fundamentos lo respaldan, justifica premium valuation."
        ),
        TrendClassification.SECULAR_DECLINE: (
            "Trend secular negativo - investigar causas estructurales. "
            "Posible erosión competitiva, disrupción, ciclo terminal."
        ),
        TrendClassification.STABLE: (
            "Estable - métrica madura sin cambios. "
            "OK para empresas defensivas/maduras."
        ),
        TrendClassification.CYCLICAL: (
            "Cíclico - alta volatilidad histórica. "
            "Cuidado en valuación: usar promedios normalizados, no peak/trough."
        ),
        TrendClassification.RECOVERY: (
            "En recuperación tras periodo débil. "
            "Verificar sustentabilidad - distinguir rebote de mejora estructural."
        ),
        TrendClassification.DETERIORATION: (
            "Deterioro consistente - RED FLAG. "
            "Investigar drivers (competition, costs, demanda)."
        ),
        TrendClassification.REVERSAL_POSITIVE: (
            "Reversión positiva - cambio de tendencia. "
            "Catalyst importante o inicio de turnaround."
        ),
        TrendClassification.REVERSAL_NEGATIVE: (
            "Reversión negativa - posible inflexión. "
            "Watch: ¿temporal o cambio estructural?"
        ),
        TrendClassification.INSUFFICIENT_DATA: "Más historia necesaria.",
    }
    interpretation = interps.get(cls, "")

    return narrative, interpretation


# ============================================================================
# Builders por categoria
# ============================================================================

def _series_for_metric(snaps, getter: Callable, fx_mult: float = 1.0,
                        scale: float = 1e6) -> List[Tuple[int, float]]:
    """Extrae (year, value) para una metrica desde una lista de snapshots."""
    out = []
    for s in snaps:
        try:
            v = getter(s)
            if v is None:
                continue
            out.append((s.year, v * fx_mult / scale))
        except Exception:
            continue
    return out


def compute_all_trends(series, fx_mult: float = 1.0,
                        use_annual: bool = True) -> List[MetricTrend]:
    """Calcula trends de todas las métricas críticas.

    Args:
        series: HistoricalSeries
        fx_mult: para empresas USD
        use_annual: True usa series.annual; False usa series.snapshots
    """
    snaps = series.annual if use_annual else series.snapshots
    if len(snaps) < 2:
        return []

    trends = []

    # ===== INCOME / GROWTH =====
    trends.append(_build_trend("Revenue", "Growth", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.income.revenue, fx_mult)))
    trends.append(_build_trend("EBIT", "Profitability", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.income.ebit, fx_mult)))
    trends.append(_build_trend("EBITDA", "Profitability", "MDP",
        _series_for_metric(snaps,
            lambda s: (s.parsed.income.ebit or 0) + (s.parsed.informative.da_12m or 0),
            fx_mult)))
    trends.append(_build_trend("Net Income", "Profitability", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.income.net_income, fx_mult)))

    # ===== MARGINS (% of revenue) =====
    def _margin(s, attr_num):
        rev = s.parsed.income.revenue or 0
        num = getattr(s.parsed.income, attr_num, 0) or 0
        return (num / rev * 100) if rev > 0 else None

    trends.append(_build_trend("Gross Margin", "Profitability", "%",
        _series_for_metric(snaps, lambda s: _margin(s, 'gross_profit'), 1.0, 1.0)))
    trends.append(_build_trend("Operating Margin", "Profitability", "%",
        _series_for_metric(snaps, lambda s: _margin(s, 'ebit'), 1.0, 1.0)))
    trends.append(_build_trend("Net Margin", "Profitability", "%",
        _series_for_metric(snaps, lambda s: _margin(s, 'net_income'), 1.0, 1.0)))

    def _ebitda_margin(s):
        rev = s.parsed.income.revenue or 0
        ebit = s.parsed.income.ebit or 0
        da = s.parsed.informative.da_12m or 0
        return ((ebit + da) / rev * 100) if rev > 0 else None
    trends.append(_build_trend("EBITDA Margin", "Profitability", "%",
        _series_for_metric(snaps, _ebitda_margin, 1.0, 1.0)))

    # ===== BALANCE SHEET =====
    trends.append(_build_trend("Total Assets", "Balance", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.balance.total_assets, fx_mult)))
    trends.append(_build_trend("Total Equity (Controlling)", "Balance", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.balance.equity_controlling, fx_mult)))
    trends.append(_build_trend("Cash & Equivalents", "Liquidity", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.balance.cash, fx_mult)))
    trends.append(_build_trend("Total Debt + Leases", "Leverage", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.balance.total_debt_with_leases, fx_mult)))
    trends.append(_build_trend("Inventories", "Working Capital", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.balance.inventories, fx_mult)))
    trends.append(_build_trend("Accounts Receivable", "Working Capital", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.balance.accounts_receivable, fx_mult)))

    # ===== EFFICIENCY (DIO/DSO/DPO) =====
    def _dio(s):
        cogs = s.parsed.income.cost_of_sales or 0
        inv = s.parsed.balance.inventories or 0
        return (inv / cogs * 365) if cogs > 0 else None
    trends.append(_build_trend("DIO (Days Inventory)", "Efficiency", "days",
        _series_for_metric(snaps, _dio, 1.0, 1.0)))

    def _dso(s):
        rev = s.parsed.income.revenue or 0
        ar = s.parsed.balance.accounts_receivable or 0
        return (ar / rev * 365) if rev > 0 else None
    trends.append(_build_trend("DSO (Days Sales)", "Efficiency", "days",
        _series_for_metric(snaps, _dso, 1.0, 1.0)))

    def _dpo(s):
        cogs = s.parsed.income.cost_of_sales or 0
        ap = s.parsed.balance.accounts_payable or 0
        return (ap / cogs * 365) if cogs > 0 else None
    trends.append(_build_trend("DPO (Days Payable)", "Efficiency", "days",
        _series_for_metric(snaps, _dpo, 1.0, 1.0)))

    def _ccc(s):
        d, di, dp = _dio(s), _dso(s), _dpo(s)
        return (d + di - dp) if (d is not None and di is not None and dp is not None) else None
    trends.append(_build_trend("Cash Conversion Cycle", "Efficiency", "days",
        _series_for_metric(snaps, _ccc, 1.0, 1.0)))

    # ===== LEVERAGE RATIOS =====
    def _net_debt_ebitda(s):
        debt = s.parsed.balance.total_debt_with_leases or 0
        cash = s.parsed.balance.cash or 0
        ebit = s.parsed.income.ebit or 0
        da = s.parsed.informative.da_12m or 0
        ebitda = ebit + da
        return ((debt - cash) / ebitda) if ebitda > 0 else None
    trends.append(_build_trend("Net Debt / EBITDA", "Leverage", "x",
        _series_for_metric(snaps, _net_debt_ebitda, 1.0, 1.0)))

    def _coverage(s):
        ebit = s.parsed.income.ebit or 0
        intx = abs(s.parsed.income.interest_expense or 0)
        return (ebit / intx) if intx > 0 else None
    trends.append(_build_trend("Interest Coverage", "Leverage", "x",
        _series_for_metric(snaps, _coverage, 1.0, 1.0)))

    def _debt_equity(s):
        debt = s.parsed.balance.total_debt_with_leases or 0
        eq = s.parsed.balance.equity_controlling or 0
        return (debt / eq) if eq > 0 else None
    trends.append(_build_trend("Debt / Equity", "Leverage", "x",
        _series_for_metric(snaps, _debt_equity, 1.0, 1.0)))

    # ===== RETURNS =====
    def _roic(s):
        ebit = s.parsed.income.ebit or 0
        pbt = s.parsed.income.pretax_income or 0
        tax = s.parsed.income.tax_expense or 0
        tax_rate = (tax / pbt) if pbt > 0 else 0.30
        nopat = ebit * (1 - tax_rate)
        ic = ((s.parsed.balance.equity_controlling or 0)
              + (s.parsed.balance.total_debt_with_leases or 0)
              - (s.parsed.balance.cash or 0))
        return (nopat / ic * 100) if ic > 0 else None
    trends.append(_build_trend("ROIC", "Profitability", "%",
        _series_for_metric(snaps, _roic, 1.0, 1.0)))

    def _roe(s):
        ni = s.parsed.income.net_income_controlling or s.parsed.income.net_income or 0
        eq = s.parsed.balance.equity_controlling or 0
        return (ni / eq * 100) if eq > 0 else None
    trends.append(_build_trend("ROE", "Profitability", "%",
        _series_for_metric(snaps, _roe, 1.0, 1.0)))

    def _roa(s):
        ni = s.parsed.income.net_income or 0
        ta = s.parsed.balance.total_assets or 0
        return (ni / ta * 100) if ta > 0 else None
    trends.append(_build_trend("ROA", "Profitability", "%",
        _series_for_metric(snaps, _roa, 1.0, 1.0)))

    # ===== CASH FLOW =====
    trends.append(_build_trend("Cash from Operations", "Cash Flow", "MDP",
        _series_for_metric(snaps, lambda s: s.parsed.cashflow.cfo, fx_mult)))

    def _fcf(s):
        cfo = s.parsed.cashflow.cfo or 0
        capex = s.parsed.cashflow.capex_ppe or 0
        return cfo - capex
    trends.append(_build_trend("Free Cash Flow", "Cash Flow", "MDP",
        _series_for_metric(snaps, _fcf, fx_mult)))

    def _fcf_margin(s):
        rev = s.parsed.income.revenue or 0
        return (_fcf(s) / rev * 100) if rev > 0 else None
    trends.append(_build_trend("FCF Margin", "Cash Flow", "%",
        _series_for_metric(snaps, _fcf_margin, 1.0, 1.0)))

    def _cfo_ni(s):
        cfo = s.parsed.cashflow.cfo or 0
        ni = s.parsed.income.net_income or 0
        return (cfo / ni) if ni > 0 else None
    trends.append(_build_trend("CFO / Net Income (Quality)", "Quality", "x",
        _series_for_metric(snaps, _cfo_ni, 1.0, 1.0)))

    return trends


def trends_to_table(trends: List[MetricTrend]) -> pd.DataFrame:
    """Convierte lista de trends a DataFrame para display."""
    rows = []
    for t in trends:
        cagr_3y_str = f"{t.cagr_3y*100:+.1f}%" if t.cagr_3y is not None else "—"
        cagr_5y_str = f"{t.cagr_5y*100:+.1f}%" if t.cagr_5y is not None else "—"
        cagr_all_str = f"{t.cagr_all*100:+.1f}%" if t.cagr_all is not None else "—"
        latest_str = (f"{t.latest_value:,.2f}" if t.unit in ("MDP",)
                      else f"{t.latest_value:.2f}{t.unit}")
        rows.append({
            "Métrica":         t.metric,
            "Categoría":       t.category,
            "Latest":          latest_str,
            "Latest Year":     t.latest_year,
            "CAGR 3y":         cagr_3y_str,
            "CAGR 5y":         cagr_5y_str,
            "CAGR all":        cagr_all_str,
            "Vol":             f"{t.volatility*100:.1f}%",
            "Tendencia":       t.classification.value,
            "Strength":        t.strength.value,
            "Acel":            "🚀" if t.is_accelerating else ("📉" if t.is_decelerating else ""),
            "Persist":         (f"+{t.consecutive_improvements}y" if t.consecutive_improvements >= 2
                                else (f"-{t.consecutive_deteriorations}y" if t.consecutive_deteriorations >= 2 else "")),
        })
    return pd.DataFrame(rows)


def categorize_trends(trends: List[MetricTrend]) -> Dict[str, List[MetricTrend]]:
    """Agrupa trends por classification para analisis."""
    return {
        "secular_growth": [t for t in trends if t.classification == TrendClassification.SECULAR_GROWTH],
        "secular_decline": [t for t in trends if t.classification == TrendClassification.SECULAR_DECLINE],
        "deterioration": [t for t in trends if t.classification == TrendClassification.DETERIORATION],
        "recovery": [t for t in trends if t.classification == TrendClassification.RECOVERY],
        "cyclical": [t for t in trends if t.classification == TrendClassification.CYCLICAL],
        "stable": [t for t in trends if t.classification == TrendClassification.STABLE],
        "reversal_positive": [t for t in trends if t.classification == TrendClassification.REVERSAL_POSITIVE],
        "reversal_negative": [t for t in trends if t.classification == TrendClassification.REVERSAL_NEGATIVE],
        "accelerating": [t for t in trends if t.is_accelerating],
        "decelerating": [t for t in trends if t.is_decelerating],
    }
