"""
Integración entre Investor Reports y el modelo DCF.

Permite:
1. Auto-fill drivers DCF desde guidance management
2. Track record adjustment (haircuts si management ha fallado guidance)
3. Comparison: management view vs DCF assumptions
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple

from .schema import InvestorReport, GuidanceItem
from .analyzer import compare_guidance_vs_actuals, compute_credibility


# ============================================================================
# Auto-fill DCF drivers from latest guidance
# ============================================================================

@dataclass
class DCFDriverSuggestion:
    """Driver DCF sugerido desde management guidance."""
    driver_name: str          # "revenue_growth_y1", "capex_pct_revenue"
    suggested_value: float    # midpoint o adjusted
    source_metric: str        # nombre del metric en guidance
    source_period: str
    source_date: str
    confidence: str           # high / medium / low
    note: str = ""


def extract_dcf_suggestions(
    reports: List[InvestorReport],
    revenue_for_capex_pct: Optional[float] = None,
    fx_usd_to_mxn: float = 19.5,
) -> List[DCFDriverSuggestion]:
    """Extrae sugerencias de drivers DCF desde la guidance MAS RECIENTE.

    Args:
        reports: lista de reports (usa el más reciente)
        revenue_for_capex_pct: revenue base para convertir CapEx absoluto a %
        fx_usd_to_mxn: para convertir guidance USD a MXN

    Returns: lista de DCFDriverSuggestion para popular DCFAssumptions.
    """
    if not reports:
        return []

    sorted_reports = sorted(reports, key=lambda r: r.report_date, reverse=True)
    suggestions = []

    for r in sorted_reports:
        for g in r.guidance:
            mp = g.midpoint()
            if mp is None:
                continue

            # Revenue Growth → revenue_growth_y1 (si periodo es FY próximo)
            if "revenue" in g.metric.lower() and "growth" in g.metric.lower():
                # Convertir % a decimal
                val = mp / 100 if g.unit == "%" else mp
                suggestions.append(DCFDriverSuggestion(
                    driver_name="revenue_growth_y1",
                    suggested_value=val,
                    source_metric=g.metric,
                    source_period=g.period,
                    source_date=r.report_date,
                    confidence=g.confidence,
                    note=f"De guidance '{g.qualitative_text}'",
                ))

            # CapEx (USD M) → capex_pct_revenue
            if "capex" in g.metric.lower():
                if "USD" in g.unit and revenue_for_capex_pct:
                    capex_mxn = mp * fx_usd_to_mxn
                    capex_pct = capex_mxn / revenue_for_capex_pct
                    suggestions.append(DCFDriverSuggestion(
                        driver_name="capex_pct_revenue",
                        suggested_value=capex_pct,
                        source_metric=g.metric,
                        source_period=g.period,
                        source_date=r.report_date,
                        confidence=g.confidence,
                        note=f"USD ${mp}M × {fx_usd_to_mxn} = ${capex_mxn:,.0f} MDP "
                             f"({capex_pct*100:.1f}% de revenue)",
                    ))

            # AMP % Revenue → opex_pct (parcial — solo informativo)
            if "amp" in g.metric.lower() or "marketing" in g.metric.lower():
                val = mp / 100 if "%" in g.unit else mp
                suggestions.append(DCFDriverSuggestion(
                    driver_name="opex_amp_pct_revenue",
                    suggested_value=val,
                    source_metric=g.metric,
                    source_period=g.period,
                    source_date=r.report_date,
                    confidence=g.confidence,
                    note="AMP es parte de OpEx total. Verifica resto (G&A, Selling).",
                ))

        # Solo procesar el más reciente con guidance numerica
        if suggestions:
            break

    return suggestions


# ============================================================================
# Track Record Haircut
# ============================================================================

@dataclass
class TrackRecordAdjustment:
    """Ajuste a aplicar a drivers DCF basado en credibility de management."""
    driver_name: str
    raw_value: float                  # lo que management dice
    adjusted_value: float             # con haircut
    haircut_bps: float                # ajuste en bps
    accuracy_score: float             # % de guidances cumplidas históricamente
    rationale: str


def apply_track_record_haircut(
    suggestions: List[DCFDriverSuggestion],
    reports: List[InvestorReport],
    actuals_observed: Dict[str, Dict[str, float]],
) -> List[TrackRecordAdjustment]:
    """Aplica haircut a las sugerencias basado en track record management.

    Si management ha fallado las últimas 2 guidances de Revenue Growth,
    haircut de -200bps al siguiente.
    """
    if not suggestions:
        return []

    # Calcular credibility por metric
    comparisons = compare_guidance_vs_actuals(reports, actuals_observed)
    credibility = {c.metric: c for c in compute_credibility(comparisons)}

    out = []
    for sug in suggestions:
        # Buscar credibility para este source_metric
        cred = credibility.get(sug.source_metric)
        if cred is None or cred.total_guidances == 0:
            # No hay track record, sin ajuste
            out.append(TrackRecordAdjustment(
                driver_name=sug.driver_name,
                raw_value=sug.suggested_value,
                adjusted_value=sug.suggested_value,
                haircut_bps=0.0,
                accuracy_score=0.0,
                rationale="Sin track record histórico — usar valor raw.",
            ))
            continue

        # Determinar haircut
        # Si accuracy < 50%, aplicar haircut basado en bias avg
        haircut_bps = 0.0
        rationale = "Track record OK — sin haircut."

        if cred.accuracy_pct < 50 and cred.avg_delta_bps is not None:
            # Bias optimista (avg negativo) → haircut hacia abajo
            haircut_bps = cred.avg_delta_bps  # esto ya es negativo si optimista
            rationale = (
                f"Management ha fallado {cred.misses}/{cred.total_guidances} "
                f"guidances con bias {cred.bias.lower()}. "
                f"Avg delta: {cred.avg_delta_bps:+.0f}bps. Apply haircut."
            )

        adjusted = sug.suggested_value + (haircut_bps / 10000)

        out.append(TrackRecordAdjustment(
            driver_name=sug.driver_name,
            raw_value=sug.suggested_value,
            adjusted_value=adjusted,
            haircut_bps=haircut_bps,
            accuracy_score=cred.accuracy_pct,
            rationale=rationale,
        ))

    return out
