"""
Detección de alertas materiales en Investor Reports.

Se ejecuta cuando se sube un nuevo report y compara contra el inmediato
anterior. Genera notificaciones por:
- Sentiment shifts importantes
- Guidance cuts/upgrades
- Eventos materiales (M&A, buybacks, dividends)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

from .schema import InvestorReport
from .analyzer import detect_material_changes, MaterialChange


@dataclass
class Alert:
    """Alert generado por un cambio material."""
    timestamp: str
    ticker: str
    severity: str               # high / medium / low
    category: str               # sentiment / guidance / event
    title: str
    description: str
    action_recommended: str = ""

    def to_emoji_text(self) -> str:
        sev_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(self.severity, "⚪")
        return f"{sev_emoji} [{self.ticker}] {self.title}"


def generate_alerts_from_change(
    change: MaterialChange, ticker: str
) -> Optional[Alert]:
    """Convierte un MaterialChange en Alert."""
    if change.change_type == "sentiment_shift":
        # Sentiment shift downward es más importante
        action = (
            "Revisar guidance + drivers + comparar con consensus."
            if "Cautious" in change.to_value or "Negative" in change.to_value
            else "Validar si el optimismo es justificado por fundamentos."
        )
        return Alert(
            timestamp=datetime.utcnow().isoformat(),
            ticker=ticker,
            severity=change.severity,
            category="sentiment",
            title="Cambio de tono en management",
            description=change.description,
            action_recommended=action,
        )

    if change.change_type == "guidance_changed":
        return Alert(
            timestamp=datetime.utcnow().isoformat(),
            ticker=ticker,
            severity=change.severity,
            category="guidance",
            title="Guidance modificada",
            description=change.description,
            action_recommended="Actualizar drivers DCF + recomputar valor.",
        )

    if change.change_type == "new_event":
        return Alert(
            timestamp=datetime.utcnow().isoformat(),
            ticker=ticker,
            severity=change.severity,
            category="event",
            title="Evento material anunciado",
            description=change.description,
            action_recommended="Evaluar impacto en thesis y bridge equity.",
        )

    return None


def generate_alerts(
    curr_report: InvestorReport,
    prior_report: InvestorReport,
) -> List[Alert]:
    """Genera todos los alerts entre 2 reports."""
    changes = detect_material_changes(curr_report, prior_report)
    alerts = []
    for c in changes:
        a = generate_alerts_from_change(c, curr_report.ticker)
        if a:
            alerts.append(a)
    return alerts
