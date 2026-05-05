"""
Schema de Investor Reports (extracción estructurada de PDFs IR).

Captura QUE dice management trimestre a trimestre:
- Guidance numérica (revenue, capex, margins, etc.)
- Drivers operativos (volume, price, FX, mix)
- Strategic events (M&A, buybacks, capex announcements)
- Sentiment + key topics
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date
from enum import Enum
from typing import List, Optional, Dict, Any
import json


# ============================================================================
# Enums
# ============================================================================

class ReportType(Enum):
    EARNINGS_RELEASE = "earnings_release"          # Reporte trimestral / FY
    EARNINGS_CALL = "earnings_call"                 # Transcript de earnings call
    GUIDANCE_UPDATE = "guidance_update"             # Guía nueva o actualizada
    INVESTOR_PRESENTATION = "investor_presentation" # IR deck
    ANNUAL_REPORT = "annual_report"                 # Annual / 20-F
    PRESS_RELEASE = "press_release"                 # Material event announcement
    CONFERENCE_CALL = "conference_call"             # Earnings call slides
    INVESTOR_DAY = "investor_day"                   # Investor Day deck
    OTHER = "other"


class GuidanceDirection(Enum):
    GROWTH = "growth"
    DECLINE = "decline"
    STABLE = "stable"
    POINT = "point"          # un solo número, no rango
    QUALITATIVE = "qualitative"  # solo texto sin números


class GuidanceConfidence(Enum):
    HIGH = "high"            # rango específico con números
    MEDIUM = "medium"        # rango cualitativo (e.g. "low single digit")
    LOW = "low"              # solo aspiracional sin compromiso


class SentimentTone(Enum):
    OPTIMISTIC = "🟢 Optimistic"
    POSITIVE = "🟢 Positive"
    NEUTRAL = "⚪ Neutral"
    CAUTIOUS = "🟡 Cautious"
    DEFENSIVE = "🟠 Defensive"
    NEGATIVE = "🔴 Negative"


class DriverImpact(Enum):
    POSITIVE = "🟢 Positive"
    NEGATIVE = "🔴 Negative"
    NEUTRAL = "⚪ Neutral"
    MIXED = "🟡 Mixed"


class EventType(Enum):
    MA = "M&A (acquisition / divestiture)"
    BUYBACK = "Share buyback"
    DIVIDEND = "Dividend announcement"
    CAPEX = "CapEx plan"
    NEW_PRODUCT = "New product launch"
    CAPACITY = "Capacity expansion"
    MGMT_CHANGE = "Management change"
    DEBT_RAISE = "Debt issuance / refinance"
    LEGAL = "Legal / regulatory"
    OTHER = "Other material event"


# ============================================================================
# Dataclasses estructurados
# ============================================================================

@dataclass
class GuidanceItem:
    """Una guía numérica/cualitativa específica de management."""
    metric: str                              # "Revenue Growth", "CapEx", "AMP %"
    period: str                              # "FY2026", "1Q26", "Long-term"
    value_low: Optional[float] = None        # rango bajo (% o absoluto)
    value_high: Optional[float] = None       # rango alto
    value_point: Optional[float] = None      # si es punto único
    unit: str = "%"                          # %, USD M, MXN M, x, days
    direction: str = GuidanceDirection.STABLE.value
    confidence: str = GuidanceConfidence.MEDIUM.value
    qualitative_text: str = ""               # frase original
    notes: str = ""                          # contexto/notas

    def midpoint(self) -> Optional[float]:
        if self.value_point is not None:
            return self.value_point
        if self.value_low is not None and self.value_high is not None:
            return (self.value_low + self.value_high) / 2
        return None

    def range_str(self) -> str:
        if self.value_point is not None:
            return f"{self.value_point}{self.unit}"
        if self.value_low is not None and self.value_high is not None:
            return f"{self.value_low}{self.unit} a {self.value_high}{self.unit}"
        return self.qualitative_text or "—"


@dataclass
class Driver:
    """Driver operativo mencionado por management."""
    category: str                            # "Volume", "Price", "FX", "Mix", "M&A", "Cost"
    description: str
    impact: str = DriverImpact.NEUTRAL.value
    materiality: str = "medium"              # high/medium/low
    quote: str = ""                          # cita original si disponible


@dataclass
class StrategicEvent:
    """Evento estratégico material anunciado."""
    event_type: str                          # ver EventType
    title: str                               # "Adquisición de Bushmills"
    description: str                         # detalle
    event_date: Optional[str] = None         # ISO date string
    financial_impact: str = ""               # "$520M divestiture proceeds"
    materiality: str = "medium"              # high/medium/low


@dataclass
class SentimentScore:
    """Sentimiento overall del reporte."""
    tone: str = SentimentTone.NEUTRAL.value
    score: float = 0.0                       # -1.0 a +1.0
    confidence: str = "medium"               # confianza del scoring
    rationale: str = ""                      # por qué este tono


@dataclass
class InvestorReport:
    """Container principal: extracción completa de un PDF de IR."""
    # Identificación
    ticker: str                              # "CUERVO"
    report_date: str                         # ISO "2026-02-27"
    period_covered: str                      # "FY2026", "1Q26", "Investor Day Mar 2026"
    report_type: str = ReportType.OTHER.value
    title: str = ""                          # título del PDF
    source_url: str = ""                     # URL si scrapeado
    pdf_filename: str = ""                   # nombre del archivo PDF
    pdf_local_path: str = ""                 # path relativo al repo (e.g. "data/investor_reports/CUERVO/pdfs/x.pdf")

    # Extracción estructurada
    guidance: List[GuidanceItem] = field(default_factory=list)
    drivers: List[Driver] = field(default_factory=list)
    events: List[StrategicEvent] = field(default_factory=list)
    sentiment: Optional[SentimentScore] = None
    key_topics: List[str] = field(default_factory=list)

    # Narrative
    summary_es: str = ""                     # resumen ejecutivo en español
    summary_en: str = ""                     # english version

    # Transcript (para earnings calls completos)
    transcript_text: str = ""                # texto completo del transcript
    participants: List[str] = field(default_factory=list)  # Q&A participants
    qa_topics: List[str] = field(default_factory=list)     # tópicos del Q&A

    # Metadata extracción
    extraction_method: str = "manual"        # claude_api / manual / scraped / pdftotext
    extraction_date: str = ""                # cuándo se extrajo
    extraction_notes: str = ""

    # ID auto-generated
    @property
    def report_id(self) -> str:
        return f"{self.ticker}_{self.report_date}_{self.report_type}"

    # ========================================================================
    # Serialization
    # ========================================================================

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "InvestorReport":
        d = dict(d)  # don't mutate
        # Re-build nested dataclasses
        d["guidance"] = [GuidanceItem(**g) for g in d.get("guidance", [])]
        d["drivers"] = [Driver(**dr) for dr in d.get("drivers", [])]
        d["events"] = [StrategicEvent(**e) for e in d.get("events", [])]
        sent = d.get("sentiment")
        if sent and isinstance(sent, dict):
            d["sentiment"] = SentimentScore(**sent)
        return cls(**d)

    @classmethod
    def from_json(cls, json_str: str) -> "InvestorReport":
        return cls.from_dict(json.loads(json_str))


# ============================================================================
# Helpers
# ============================================================================

def list_report_types() -> List[str]:
    return [t.value for t in ReportType]


def list_guidance_directions() -> List[str]:
    return [d.value for d in GuidanceDirection]


def list_sentiment_tones() -> List[str]:
    return [t.value for t in SentimentTone]


def list_event_types() -> List[str]:
    return [e.value for e in EventType]


def list_driver_impacts() -> List[str]:
    return [d.value for d in DriverImpact]
