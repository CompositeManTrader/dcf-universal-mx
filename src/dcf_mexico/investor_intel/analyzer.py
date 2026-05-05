"""
Analyzer engine para InvestorReports.

Funciones clave:
1. guidance_vs_actuals: compara guidance histórica con realidad observada
2. management_credibility_score: track record (% de guidances cumplidas)
3. sentiment_evolution: evolution del tono trimestre a trimestre
4. detect_material_changes: changes vs prior report
5. extract_guidance_evolution: cómo cambió guidance del mismo metric over time
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Dict, Optional, Tuple
import statistics
import pandas as pd

from .schema import (
    InvestorReport, GuidanceItem, SentimentScore,
    ReportType, GuidanceDirection,
)


# ============================================================================
# Guidance vs Actuals tracking
# ============================================================================

@dataclass
class GuidanceVsActual:
    """Compara una guidance específica vs el resultado real observado."""
    metric: str
    period: str                              # "FY2025"
    guidance_low: Optional[float] = None
    guidance_high: Optional[float] = None
    guidance_midpoint: Optional[float] = None
    guidance_text: str = ""
    guidance_date: str = ""                  # cuando se emitió la guidance
    actual_value: Optional[float] = None
    actual_date: str = ""                    # cuando se observó (FY end)
    delta_to_midpoint: Optional[float] = None
    classification: str = "pending"          # beat / miss / inline / pending
    severity: str = ""                       # ej. "+/- 200bps"


def compare_guidance_vs_actuals(
    reports: List[InvestorReport],
    actuals: Dict[str, Dict[str, float]],
) -> List[GuidanceVsActual]:
    """Para cada guidance histórica, busca el actual en `actuals`.

    Args:
        reports: lista de InvestorReports (orden cualquiera)
        actuals: dict {period: {metric: actual_value}}, e.g.
                 {"FY2025": {"Revenue Growth (Constant Currency)": -2.0, ...}}

    Returns: lista de GuidanceVsActual.
    """
    out = []
    for r in reports:
        for g in r.guidance:
            actual = actuals.get(g.period, {}).get(g.metric)
            mp = g.midpoint()

            if actual is None or mp is None:
                classification = "pending"
                delta = None
                severity = ""
            else:
                delta = actual - mp
                # Clasificar
                if g.value_low is not None and g.value_high is not None:
                    if g.value_low <= actual <= g.value_high:
                        classification = "in_range"
                    elif actual > g.value_high:
                        classification = "beat"
                    else:
                        classification = "miss"
                else:
                    # Solo midpoint o solo qualitative
                    if abs(delta) <= abs(mp) * 0.05:
                        classification = "in_range"
                    elif delta > 0:
                        classification = "beat"
                    else:
                        classification = "miss"

                # Severity en bps si es %
                if g.unit == "%":
                    severity = f"{delta * 100:+.0f}bps"
                else:
                    severity = f"{delta:+.1f} {g.unit}"

            out.append(GuidanceVsActual(
                metric=g.metric,
                period=g.period,
                guidance_low=g.value_low,
                guidance_high=g.value_high,
                guidance_midpoint=mp,
                guidance_text=g.qualitative_text,
                guidance_date=r.report_date,
                actual_value=actual,
                delta_to_midpoint=delta,
                classification=classification,
                severity=severity,
            ))
    return out


def compare_to_table(comparisons: List[GuidanceVsActual]) -> pd.DataFrame:
    """Convierte a DataFrame para display."""
    rows = []
    for c in comparisons:
        emoji = {
            "beat": "🟢 BEAT",
            "in_range": "🟡 IN RANGE",
            "miss": "🔴 MISS",
            "pending": "⏳ PENDING",
        }.get(c.classification, "")
        rows.append({
            "Métrica": c.metric,
            "Periodo": c.period,
            "Guidance": (
                f"{c.guidance_low:+.1f} a {c.guidance_high:+.1f}"
                if c.guidance_low is not None and c.guidance_high is not None
                else (f"{c.guidance_midpoint:+.1f}" if c.guidance_midpoint is not None
                      else c.guidance_text[:60])
            ),
            "Fecha guidance": c.guidance_date,
            "Real": (f"{c.actual_value:+.1f}" if c.actual_value is not None
                     else "—"),
            "Delta": c.severity,
            "Resultado": emoji,
        })
    return pd.DataFrame(rows)


# ============================================================================
# Management Credibility Score
# ============================================================================

@dataclass
class CredibilityScore:
    metric: str
    total_guidances: int
    beats: int
    in_range: int
    misses: int
    pending: int
    accuracy_pct: float                      # % beats + in_range
    avg_delta_bps: Optional[float] = None    # promedio de delta en bps
    bias: str = ""                           # "optimistic" / "pessimistic" / "balanced"


def compute_credibility(comparisons: List[GuidanceVsActual]) -> List[CredibilityScore]:
    """Calcula credibility score por métrica."""
    by_metric = {}
    for c in comparisons:
        by_metric.setdefault(c.metric, []).append(c)

    out = []
    for metric, cs in by_metric.items():
        beats = sum(1 for c in cs if c.classification == "beat")
        in_range = sum(1 for c in cs if c.classification == "in_range")
        misses = sum(1 for c in cs if c.classification == "miss")
        pending = sum(1 for c in cs if c.classification == "pending")
        total = beats + in_range + misses

        accuracy = ((beats + in_range) / total * 100) if total > 0 else 0

        # Avg delta (solo de los completados)
        deltas = [c.delta_to_midpoke if hasattr(c, 'delta_to_midpoke') else c.delta_to_midpoint
                  for c in cs if c.delta_to_midpoint is not None]
        avg_delta_bps = (statistics.mean(deltas) * 100 if deltas else None)

        # Bias
        if avg_delta_bps is None:
            bias = "—"
        elif avg_delta_bps > 50:
            bias = "Pessimistic (bate guidance)"
        elif avg_delta_bps < -50:
            bias = "Optimistic (no cumple guidance)"
        else:
            bias = "Balanced"

        out.append(CredibilityScore(
            metric=metric, total_guidances=len(cs),
            beats=beats, in_range=in_range, misses=misses, pending=pending,
            accuracy_pct=accuracy, avg_delta_bps=avg_delta_bps, bias=bias,
        ))
    return out


# ============================================================================
# Sentiment Evolution
# ============================================================================

@dataclass
class SentimentTimepoint:
    report_date: str
    period: str
    report_type: str
    title: str
    tone: str
    score: float
    rationale: str


def sentiment_evolution(reports: List[InvestorReport]) -> List[SentimentTimepoint]:
    """Devuelve evolución de sentiment ordenada por fecha."""
    out = []
    for r in reports:
        if r.sentiment is None:
            continue
        out.append(SentimentTimepoint(
            report_date=r.report_date,
            period=r.period_covered,
            report_type=r.report_type,
            title=r.title,
            tone=r.sentiment.tone,
            score=r.sentiment.score,
            rationale=r.sentiment.rationale,
        ))
    out.sort(key=lambda s: s.report_date)
    return out


def sentiment_to_table(timepoints: List[SentimentTimepoint]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Fecha": t.report_date,
            "Periodo": t.period,
            "Tipo": t.report_type,
            "Tono": t.tone,
            "Score": f"{t.score:+.2f}",
            "Rationale": t.rationale[:150],
        }
        for t in timepoints
    ])


# ============================================================================
# Material Changes (entre 2 reports adyacentes)
# ============================================================================

@dataclass
class MaterialChange:
    change_type: str         # "guidance_changed" / "sentiment_shift" / "new_event" / etc.
    severity: str            # "high" / "medium" / "low"
    description: str
    from_value: str
    to_value: str
    from_date: str
    to_date: str


def detect_material_changes(
    curr_report: InvestorReport,
    prior_report: InvestorReport,
) -> List[MaterialChange]:
    """Detecta cambios materiales entre 2 reports."""
    changes = []

    # 1. Sentiment shift
    if curr_report.sentiment and prior_report.sentiment:
        delta = curr_report.sentiment.score - prior_report.sentiment.score
        if abs(delta) > 0.3:
            changes.append(MaterialChange(
                change_type="sentiment_shift",
                severity="high" if abs(delta) > 0.5 else "medium",
                description=f"Tono cambió de {prior_report.sentiment.tone} a "
                           f"{curr_report.sentiment.tone}",
                from_value=prior_report.sentiment.tone,
                to_value=curr_report.sentiment.tone,
                from_date=prior_report.report_date,
                to_date=curr_report.report_date,
            ))

    # 2. Guidance changes (mismo metric+period)
    prior_g_map = {(g.metric, g.period): g for g in prior_report.guidance}
    for g in curr_report.guidance:
        key = (g.metric, g.period)
        if key in prior_g_map:
            old = prior_g_map[key]
            old_mp = old.midpoint()
            new_mp = g.midpoint()
            if old_mp is not None and new_mp is not None:
                delta = new_mp - old_mp
                if abs(delta) > 0.5:  # threshold puntual
                    changes.append(MaterialChange(
                        change_type="guidance_changed",
                        severity="high" if abs(delta) > 2 else "medium",
                        description=(
                            f"Guidance {g.metric} ({g.period}) cambió de "
                            f"{old.range_str()} a {g.range_str()}"
                        ),
                        from_value=old.range_str(),
                        to_value=g.range_str(),
                        from_date=prior_report.report_date,
                        to_date=curr_report.report_date,
                    ))

    # 3. Nuevos eventos materiales
    prior_event_titles = {e.title for e in prior_report.events}
    for e in curr_report.events:
        if e.title not in prior_event_titles and e.materiality in ("high", "medium"):
            changes.append(MaterialChange(
                change_type="new_event",
                severity=e.materiality,
                description=f"{e.event_type}: {e.title}. {e.description}",
                from_value="—",
                to_value=e.title,
                from_date=prior_report.report_date,
                to_date=curr_report.report_date,
            ))

    return changes


# ============================================================================
# Guidance Evolution (mismo metric+period a través del tiempo)
# ============================================================================

def guidance_evolution(
    reports: List[InvestorReport],
    metric: str,
    period: str,
) -> List[Tuple[str, GuidanceItem]]:
    """Evolución de una guidance específica through time.

    Útil para ver "Cómo cambió guidance FY2026 Revenue Growth desde Q1 25 hasta hoy?"
    """
    out = []
    for r in sorted(reports, key=lambda x: x.report_date):
        for g in r.guidance:
            if g.metric == metric and g.period == period:
                out.append((r.report_date, g))
                break
    return out


def guidance_evolution_table(
    reports: List[InvestorReport],
    metric: str,
    period: str,
) -> pd.DataFrame:
    evo = guidance_evolution(reports, metric, period)
    return pd.DataFrame([
        {
            "Fecha emisión": d,
            "Range": g.range_str(),
            "Midpoint": g.midpoint(),
            "Direction": g.direction,
            "Confidence": g.confidence,
            "Texto original": g.qualitative_text[:80],
        }
        for d, g in evo
    ])
