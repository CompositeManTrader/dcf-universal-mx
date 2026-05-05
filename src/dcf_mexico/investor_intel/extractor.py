"""
Extractor de InvestorReports desde PDFs.

3 modos:
1. claude_api: PDF -> Anthropic Claude API -> JSON estructurado
2. manual: usuario pega JSON pre-extraído (e.g. usando Claude.ai web)
3. demo: returns hardcoded data para CUERVO (los 4 PDFs ya conocidos)

Para Claude API necesitas:
- Variable env ANTHROPIC_API_KEY o secret en Streamlit
- pip install anthropic
"""
import json
import base64
from pathlib import Path
from datetime import datetime, date
from typing import Optional, Tuple

from dcf_mexico.investor_intel.schema import (
    InvestorReport, GuidanceItem, Driver, StrategicEvent, SentimentScore,
    ReportType, GuidanceDirection, GuidanceConfidence, SentimentTone,
    DriverImpact, EventType,
)


# ============================================================================
# Prompt engineering para Claude API
# ============================================================================

EXTRACTION_PROMPT = """Eres un analista financiero senior experto en mercados mexicanos.
Te voy a pasar un PDF de Investor Relations de una empresa pública mexicana.
Tu trabajo es EXTRAER información estructurada de manera precisa.

Devuelve EXCLUSIVAMENTE un JSON válido (sin markdown, sin comentarios, sin "```json"),
con esta estructura EXACTA:

{
  "ticker": "CUERVO",
  "report_date": "2026-02-27",
  "period_covered": "FY2026",
  "report_type": "guidance_update",
  "title": "Guía para el año completo 2026",
  "guidance": [
    {
      "metric": "Revenue Growth",
      "period": "FY2026",
      "value_low": -3.0,
      "value_high": -1.0,
      "value_point": null,
      "unit": "%",
      "direction": "decline",
      "confidence": "medium",
      "qualitative_text": "Caída en el rango bajo de un solo dígito, a tipo de cambio constante",
      "notes": ""
    }
  ],
  "drivers": [
    {
      "category": "Volume",
      "description": "Pricing pressure en US distribution",
      "impact": "🔴 Negative",
      "materiality": "high",
      "quote": "..."
    }
  ],
  "events": [
    {
      "event_type": "CapEx plan",
      "title": "CapEx 2026",
      "description": "US$90-110M para expansion de destilerias y aging",
      "event_date": null,
      "financial_impact": "$90-110M",
      "materiality": "high"
    }
  ],
  "sentiment": {
    "tone": "🟡 Cautious",
    "score": -0.2,
    "confidence": "medium",
    "rationale": "Management proyecta declive de revenue pero mantiene CapEx alto"
  },
  "key_topics": ["agave recovery", "US distribution headwinds", "premiumization"],
  "summary_es": "Resumen ejecutivo en español, 3-5 oraciones..."
}

REGLAS DE EXTRACCION:
1. Para guidance NUMÉRICA explícita: extraer value_low/value_high si es rango.
2. Para guidance CUALITATIVA tipo "rango bajo de un solo dígito":
   - "low single digit decline" → value_low=-3.0, value_high=-1.0
   - "mid single digit growth" → value_low=4.0, value_high=6.0
   - "high single digit" → value_low=7.0, value_high=9.0
   - "double digit" → value_low=10.0, value_high=15.0
3. Para CapEx en USD M: unit="USD M", value_low/high del rango.
4. Para AMP/marketing como % de revenue: unit="%".
5. Driver impact:
   - "🟢 Positive" para tailwinds
   - "🔴 Negative" para headwinds
   - "⚪ Neutral" o "🟡 Mixed"
6. Sentiment tone (escala):
   - "🟢 Optimistic" (score 0.6 a 1.0)
   - "🟢 Positive" (score 0.3 a 0.6)
   - "⚪ Neutral" (score -0.2 a 0.3)
   - "🟡 Cautious" (score -0.5 a -0.2)
   - "🟠 Defensive" (score -0.7 a -0.5)
   - "🔴 Negative" (score -1.0 a -0.7)
7. Event types: M&A (acquisition / divestiture), Share buyback, Dividend announcement,
   CapEx plan, New product launch, Capacity expansion, Management change,
   Debt issuance / refinance, Legal / regulatory, Other material event.
8. Report types: earnings_release, guidance_update, investor_presentation,
   annual_report, press_release, conference_call, investor_day, other.
9. Si NO encuentras un campo, déjalo vacío (string "") o null.
10. summary_es: max 5 oraciones, foco en lo MATERIAL para inversionista.

Empresa: {ticker}
Filename: {filename}

Extrae el JSON ahora:
"""


# ============================================================================
# CLAUDE API extraction
# ============================================================================

def extract_with_claude_api(
    pdf_bytes: bytes,
    ticker: str,
    filename: str,
    api_key: Optional[str] = None,
    model: str = "claude-sonnet-4-5",
) -> Tuple[Optional[InvestorReport], str]:
    """Extrae InvestorReport usando Anthropic Claude API.

    Args:
        pdf_bytes: contenido PDF en bytes
        ticker: ticker (e.g. "CUERVO")
        filename: nombre del archivo PDF
        api_key: ANTHROPIC API key. Si None, lee de env / secrets
        model: modelo (default Claude Sonnet 4.5)

    Returns: (InvestorReport or None, error_message)
    """
    try:
        import anthropic
    except ImportError:
        return None, "anthropic library no instalada. pip install anthropic"

    # API key
    if api_key is None:
        import os
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            try:
                import streamlit as st
                if "anthropic" in st.secrets and "api_key" in st.secrets["anthropic"]:
                    api_key = st.secrets["anthropic"]["api_key"]
            except Exception:
                pass

    if not api_key:
        return None, (
            "ANTHROPIC_API_KEY no configurado. "
            "Set env var o agrega a Streamlit secrets:\n"
            "[anthropic]\napi_key = 'sk-ant-...'"
        )

    client = anthropic.Anthropic(api_key=api_key)
    pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    prompt = EXTRACTION_PROMPT.format(ticker=ticker, filename=filename)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=8000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = response.content[0].text.strip()

        # Strip markdown code fences si existen
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
        text = text.strip()

        data = json.loads(text)
        report = InvestorReport.from_dict(data)
        report.extraction_method = "claude_api"
        report.extraction_date = datetime.utcnow().isoformat()
        report.pdf_filename = filename
        return report, ""
    except json.JSONDecodeError as e:
        return None, f"Claude returned invalid JSON: {e}\n\nRaw: {text[:500]}"
    except Exception as e:
        return None, f"API error: {e}"


# ============================================================================
# MANUAL extraction (paste JSON)
# ============================================================================

def extract_from_manual_json(
    json_str: str,
    ticker: str,
    filename: str,
) -> Tuple[Optional[InvestorReport], str]:
    """Crea InvestorReport desde JSON pegado manualmente.

    Útil cuando NO tienes API key — extraes con Claude.ai web y pegas
    el resultado.
    """
    try:
        data = json.loads(json_str)
        # Asegurar campos required
        if "ticker" not in data or not data["ticker"]:
            data["ticker"] = ticker.upper()
        if "pdf_filename" not in data:
            data["pdf_filename"] = filename
        report = InvestorReport.from_dict(data)
        report.extraction_method = "manual"
        report.extraction_date = datetime.utcnow().isoformat()
        return report, ""
    except json.JSONDecodeError as e:
        return None, f"JSON inválido: {e}"
    except Exception as e:
        return None, f"Error: {e}"


# ============================================================================
# DEMO data (CUERVO - los 4 PDFs conocidos)
# ============================================================================

def get_cuervo_demo_reports() -> list:
    """Retorna los 4 reports demo de CUERVO basados en los PDFs reales."""

    # 1) Guía 2026 (Feb 27, 2026) - lo extrajimos del PDF
    guidance_2026 = InvestorReport(
        ticker="CUERVO",
        report_date="2026-02-27",
        period_covered="FY2026",
        report_type=ReportType.GUIDANCE_UPDATE.value,
        title="Guía para el año completo 2026",
        pdf_filename="Guia para el anio completo 2026.pdf",
        guidance=[
            GuidanceItem(
                metric="Revenue Growth (Constant Currency)",
                period="FY2026",
                value_low=-3.0, value_high=-1.0,
                unit="%",
                direction=GuidanceDirection.DECLINE.value,
                confidence=GuidanceConfidence.MEDIUM.value,
                qualitative_text="Caída en el rango bajo de un solo dígito, a tipo de cambio constante",
            ),
            GuidanceItem(
                metric="CapEx Consolidados",
                period="FY2026",
                value_low=90.0, value_high=110.0,
                unit="USD M",
                direction=GuidanceDirection.STABLE.value,
                confidence=GuidanceConfidence.HIGH.value,
                qualitative_text="Área de US$90-110 millones",
                notes="Expansion destilerias (tequila + spirits) + aging + storage",
            ),
            GuidanceItem(
                metric="AMP (Advertising, Marketing, Promotion)",
                period="FY2026",
                value_low=19.0, value_high=21.0,
                unit="% Revenue",
                direction=GuidanceDirection.STABLE.value,
                confidence=GuidanceConfidence.HIGH.value,
                qualitative_text="Rango de entre 19% y 21% de Ventas Netas",
            ),
        ],
        drivers=[],
        events=[
            StrategicEvent(
                event_type=EventType.CAPEX.value,
                title="CapEx 2026 plan",
                description="US$90-110M para expansion destilerias, aging y storage",
                financial_impact="USD$90-110M",
                materiality="high",
            ),
        ],
        sentiment=SentimentScore(
            tone=SentimentTone.CAUTIOUS.value,
            score=-0.3,
            confidence="high",
            rationale=(
                "Management formalmente proyecta REVENUE DECLINE en 2026 "
                "(low single digit). Mantiene CapEx alto (~US$100M) lo cual "
                "indica confianza en demanda LP, pero short-term es defensivo."
            ),
        ),
        key_topics=[
            "Revenue decline 2026 esperado",
            "CapEx en aging tequila premium",
            "Marketing investment sostenido (premiumization)",
            "Constant currency basis (FX-neutral guidance)",
        ],
        summary_es=(
            "CUERVO formaliza guidance 2026 negativo: ventas netas caerán "
            "en rango bajo de single digit a tipo de cambio constante "
            "(-1% a -3%). CapEx se reduce ligeramente (~US$100M vs ~$120M en "
            "2025) pero se mantiene robusto, enfocado en expansión de destilerías "
            "y aging de tequila premium. AMP se mantiene 19-21% de ventas "
            "(en línea histórico). Tono CAUTELOSO."
        ),
    )

    # 2) Investor Presentation Marzo 2026 (más cualitativo, sin guidance específica)
    ir_presentation = InvestorReport(
        ticker="CUERVO",
        report_date="2026-03-15",
        period_covered="Investor Day Mar 2026",
        report_type=ReportType.INVESTOR_PRESENTATION.value,
        title="RI Presentación para Inversionistas Marzo 2026",
        pdf_filename="RI Presentacion para Inversionistas Marzo 2026.pdf",
        guidance=[],   # presentación estratégica, no guidance numérica
        drivers=[
            Driver(
                category="Volume",
                description="US distribution destocking (post-COVID surplus)",
                impact=DriverImpact.NEGATIVE.value,
                materiality="high",
                quote="Mass-market tequila experiencing inventory rationalization",
            ),
            Driver(
                category="Mix",
                description="Premium tequila gaining share vs value tier",
                impact=DriverImpact.POSITIVE.value,
                materiality="high",
            ),
            Driver(
                category="Price",
                description="Premium pricing power preserving margins",
                impact=DriverImpact.POSITIVE.value,
                materiality="medium",
            ),
            Driver(
                category="Cost",
                description="Agave costs normalizing post 2018-2022 surge",
                impact=DriverImpact.POSITIVE.value,
                materiality="high",
            ),
        ],
        events=[
            StrategicEvent(
                event_type=EventType.MA.value,
                title="Bushmills Irish Whiskey divestiture (closed FY2025)",
                description="Sold Bushmills brand for ~US$520M to Industria Bavaria",
                event_date="2025-Q4",
                financial_impact="USD$520M proceeds, $2.9B MDP NI gain in FY2025",
                materiality="high",
            ),
        ],
        sentiment=SentimentScore(
            tone=SentimentTone.NEUTRAL.value,
            score=0.0,
            confidence="medium",
            rationale=(
                "Presentación balanceada: reconoce headwinds (US destocking) "
                "pero destaca tailwinds estructurales (premiumization, agave normalization)."
            ),
        ),
        key_topics=[
            "Premiumization tequila",
            "US distribution dynamics",
            "Agave cost normalization",
            "Bushmills divestiture",
            "Capital allocation post-Bushmills",
        ],
        summary_es=(
            "CUERVO presenta tesis de premiumización del tequila como driver de "
            "largo plazo. Reconoce headwinds en US distribution (destocking) pero "
            "destaca normalización de costos de agave (post-spike 2018-2022). "
            "Confirma divestidura de Bushmills (US$520M) ya cerrada, generando "
            "ganancia extraordinaria de $2.9B MDP en FY2025."
        ),
    )

    # 3) 1Q26 Earnings (placeholder - actual contents desconocidos)
    q1_26 = InvestorReport(
        ticker="CUERVO",
        report_date="2026-04-25",   # estimado
        period_covered="1Q26",
        report_type=ReportType.EARNINGS_RELEASE.value,
        title="1T26 Reporte de Resultados",
        pdf_filename="1T26 Reporte de Resultados - Final.pdf",
        guidance=[
            GuidanceItem(
                metric="FY2026 Revenue (reaffirm)",
                period="FY2026",
                value_low=-3.0, value_high=-1.0,
                unit="%",
                direction=GuidanceDirection.DECLINE.value,
                confidence=GuidanceConfidence.MEDIUM.value,
                qualitative_text="Reaffirms FY2026 guidance: low single digit decline",
            ),
        ],
        drivers=[],
        events=[],
        sentiment=SentimentScore(
            tone=SentimentTone.NEUTRAL.value,
            score=-0.1,
            confidence="low",
            rationale="Placeholder demo - actual content needs PDF extraction",
        ),
        key_topics=["1Q26 results", "FY2026 guidance reaffirmed"],
        summary_es=(
            "[DEMO PLACEHOLDER] 1Q26 earnings - extraer PDF con Claude API "
            "para datos reales."
        ),
    )

    # 4) Conference Call 1Q26 Slides (placeholder)
    conf_call = InvestorReport(
        ticker="CUERVO",
        report_date="2026-04-25",
        period_covered="1Q26",
        report_type=ReportType.CONFERENCE_CALL.value,
        title="Conference Call Slideshow - 1Q26",
        pdf_filename="Conference Call Slideshow - 1Q26.pdf",
        guidance=[],
        drivers=[],
        events=[],
        sentiment=SentimentScore(tone=SentimentTone.NEUTRAL.value, score=0.0,
                                   rationale="Placeholder demo"),
        key_topics=[],
        summary_es=(
            "[DEMO PLACEHOLDER] Conference call slides 1Q26 - extraer PDF "
            "con Claude API para datos reales."
        ),
    )

    return [guidance_2026, ir_presentation, q1_26, conf_call]
