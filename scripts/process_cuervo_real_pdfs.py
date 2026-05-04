"""Procesa los PDFs reales de CUERVO y guarda InvestorReports."""
import warnings; warnings.filterwarnings('ignore')
import sys; sys.path.insert(0, '.')
from src.dcf_mexico.investor_intel import (
    InvestorReport, GuidanceItem, Driver, StrategicEvent, SentimentScore,
    ReportType, GuidanceDirection, GuidanceConfidence, SentimentTone,
    DriverImpact, EventType, save_report, delete_report,
)

# ============================================================================
# Borrar demos antiguos (placeholders)
# ============================================================================
import shutil
from pathlib import Path
demo_dir = Path("data/investor_reports/CUERVO")
if demo_dir.exists():
    for f in demo_dir.glob("*.json"):
        f.unlink()
    print(f"Cleared old demo reports in {demo_dir}")

# ============================================================================
# REPORT 1: Guia 2026 (PDF real procesado)
# ============================================================================
guia_2026 = InvestorReport(
    ticker="CUERVO",
    report_date="2026-02-27",
    period_covered="FY2026",
    report_type=ReportType.GUIDANCE_UPDATE.value,
    title="Guia para el ano completo 2026",
    pdf_filename="Guia para el anio completo 2026.pdf",
    guidance=[
        GuidanceItem(
            metric="Ventas Netas Consolidadas (Constant Currency)",
            period="FY2026",
            value_low=-3.0, value_high=-1.0,
            unit="%",
            direction=GuidanceDirection.DECLINE.value,
            confidence=GuidanceConfidence.MEDIUM.value,
            qualitative_text="Caida en el rango bajo de un solo digito, a tipo de cambio constante",
            notes="Constant currency basis = excluye efectos FX peso-dolar",
        ),
        GuidanceItem(
            metric="Gastos de Capital Consolidados",
            period="FY2026",
            value_low=90.0, value_high=110.0,
            unit="USD M",
            direction=GuidanceDirection.STABLE.value,
            confidence=GuidanceConfidence.HIGH.value,
            qualitative_text="Area de US$90-110 millones",
            notes="Para expansion destilerias (Tequila + Spirits) + anejamiento + almacenamiento",
        ),
        GuidanceItem(
            metric="Publicidad, Marketing y Promocion (AMP)",
            period="FY2026",
            value_low=19.0, value_high=21.0,
            unit="% Ventas Netas",
            direction=GuidanceDirection.STABLE.value,
            confidence=GuidanceConfidence.HIGH.value,
            qualitative_text="Rango de entre 19% y 21% de Ventas Netas",
        ),
    ],
    drivers=[],
    events=[
        StrategicEvent(
            event_type=EventType.CAPEX.value,
            title="Plan CapEx FY2026: US$90-110M",
            description=(
                "Inversion 2026 enfocada en: (1) expansion capacidad destilerias "
                "(Tequila + Otras Bebidas Espirituosas), (2) anejamiento, "
                "(3) almacenamiento. Respalda plan de crecimiento LP."
            ),
            event_date="2026-02-27",
            financial_impact="USD$90-110M",
            materiality="high",
        ),
    ],
    sentiment=SentimentScore(
        tone=SentimentTone.CAUTIOUS.value,
        score=-0.35,
        confidence="high",
        rationale=(
            "Management formaliza guia REVENUE DECLINE 2026 (low single digit). "
            "Mantiene CapEx alto (~US$100M) lo cual senala confianza en demanda LP, "
            "pero short-term es defensivo."
        ),
    ),
    key_topics=[
        "Revenue decline 2026 esperado (low single digit, FX-neutral)",
        "CapEx estable ~US$100M (vs ~$120M en 2025)",
        "Marketing investment sostenido (premiumization)",
        "Constant currency basis (FX-neutral guidance)",
        "Aging tequila premium (capital intensive)",
    ],
    summary_es=(
        "CUERVO formaliza guia 2026 NEGATIVA: Ventas Netas Consolidadas caeran en "
        "rango bajo de single digit (-1% a -3%) a tipo de cambio constante. "
        "CapEx se reduce ligeramente a US$90-110M (vs ~$120M en 2025) pero se "
        "mantiene robusto, enfocado en expansion de destilerias y anejamiento de "
        "tequila premium. AMP se mantiene 19-21% de ventas (en linea historico). "
        "Tono CAUTELOSO."
    ),
    extraction_method="claude_code_slash",
)

# ============================================================================
# REPORT 2: 1T26 Earnings Release (PDF real procesado)
# ============================================================================
q1_26 = InvestorReport(
    ticker="CUERVO",
    report_date="2026-04-29",
    period_covered="1T26",
    report_type=ReportType.EARNINGS_RELEASE.value,
    title="Becle, S.A.B. de C.V. Reporta Resultados Financieros No Auditados del 1T26",
    pdf_filename="1T26 Reporte de Resultados - Final.pdf",
    guidance=[
        GuidanceItem(
            metric="AMP % Ventas Netas (FY2026 reaffirm)",
            period="FY2026",
            value_low=19.0, value_high=21.0,
            unit="% Ventas Netas",
            direction=GuidanceDirection.STABLE.value,
            confidence=GuidanceConfidence.HIGH.value,
            qualitative_text="manteniendose en linea con el rango de guia anual de la Compania de 19% a 21%",
            notes="1T26 actual: 20.4% AMP, dentro del rango",
        ),
    ],
    drivers=[
        Driver(
            category="Volume",
            description="Transicion de distribuidores en EE.UU. - reduccion de inventarios en sistema",
            impact=DriverImpact.NEGATIVE.value,
            materiality="high",
            quote="afectado por la transicion de distribuidores en EE. UU.",
        ),
        Driver(
            category="FX",
            description="Apreciacion peso mexicano vs USD - headwind material en revenue reportado (vs constant currency)",
            impact=DriverImpact.NEGATIVE.value,
            materiality="high",
            quote="efectos negativos de la conversion de divisas",
        ),
        Driver(
            category="Mix",
            description="Mezcla geografica desfavorable (caida US/Canada vs RoW crece)",
            impact=DriverImpact.NEGATIVE.value,
            materiality="high",
        ),
        Driver(
            category="Volume",
            description="Resto del Mundo crecio +20.1% YoY en volumen (compensacion parcial)",
            impact=DriverImpact.POSITIVE.value,
            materiality="medium",
        ),
        Driver(
            category="Mix",
            description="Mezcla de producto favorable (premium gana share)",
            impact=DriverImpact.POSITIVE.value,
            materiality="medium",
            quote="parcialmente compensado por una mezcla de producto favorable",
        ),
        Driver(
            category="Cost",
            description="Costos de insumos (agave) estables - normalizacion post 2018-2022",
            impact=DriverImpact.POSITIVE.value,
            materiality="medium",
            quote="costos de insumos estables",
        ),
        Driver(
            category="Cost",
            description="SG&A +440bps a 17.5% por desapalancamiento operativo (revenue cae 23%)",
            impact=DriverImpact.NEGATIVE.value,
            materiality="high",
        ),
        Driver(
            category="Cost",
            description="AMP -50bps a 20.4% (disciplina marketing, dentro del rango de guia)",
            impact=DriverImpact.POSITIVE.value,
            materiality="low",
        ),
        Driver(
            category="Volume",
            description="Mexico volumen organico +6.1% (excluyendo b:oost divestiture)",
            impact=DriverImpact.POSITIVE.value,
            materiality="medium",
            quote="Mexico incremento su volumen 6.1% en comparacion con el ano anterior, por encima del desempeno de la industria",
        ),
    ],
    events=[
        StrategicEvent(
            event_type=EventType.MA.value,
            title="Divestidura marca b:oost (Mexico)",
            description=(
                "Vendida la marca b:oost (bebidas no-alcoholicas Mexico). Impacto: "
                "volumen total reportado -13.4% pero -10.9% excluyendo b:oost. "
                "Volumen Mexico -6.9% reportado pero +6.1% organico."
            ),
            event_date="1Q26",
            financial_impact="No disclosed",
            materiality="medium",
        ),
        StrategicEvent(
            event_type=EventType.OTHER.value,
            title="Deleveraging continuo: Net Debt/UAFIDA = 1.0x (vs 1.9x en 1T25)",
            description=(
                "Empresa redujo apalancamiento neto ajustado por arrendamientos a "
                "1.0x (vs 1.9x en 1T25). Reduccion significativa de deuda."
            ),
            event_date="2026-03-31",
            financial_impact="Net Debt/UAFIDA mejora 90bps YoY",
            materiality="high",
        ),
    ],
    sentiment=SentimentScore(
        tone=SentimentTone.DEFENSIVE.value,
        score=-0.55,
        confidence="high",
        rationale=(
            "Trimestre brutalmente debil: Revenue -23%, UAFIDA -52%, NI -67%. "
            "Management acepta entorno 'desafiante y de contraccion para la industria'. "
            "Lenguaje DEFENSIVO: 'fortalecer el negocio mediante ejecucion disciplinada' "
            "+ 'reposicionamiento'. Unico positivo: deleveraging completado (1.0x ND/UAFIDA). "
            "AMP guidance reafirmado pero NO actualizo guia de revenue."
        ),
    ),
    key_topics=[
        "Revenue -23.1% (-13.5% en moneda constante)",
        "UAFIDA Margin contraction 580bps a 13.9%",
        "Volume -13.4% (excluyendo b:oost: -10.9%)",
        "US distribution transition (drag mayor)",
        "FX headwind (apreciacion peso vs USD)",
        "Mexico organico +6.1% (positivo)",
        "RoW volume +20.1% (positivo)",
        "Deleveraging completo: Net Debt/UAFIDA 1.0x",
        "AMP discipline 20.4% (dentro de guia)",
        "Divestidura b:oost",
    ],
    summary_es=(
        "CUERVO reporto 1T26 BRUTALMENTE DEBIL: Ventas -23.1% YoY (-13.5% en moneda "
        "constante), UAFIDA -52.5%, Utilidad Neta -66.5%. Margen UAFIDA cayo 860bps a "
        "13.9% (16.7% ajustado por FX). Drivers principales: (1) transicion de "
        "distribuidores en EE.UU. con destocking del sistema, (2) apreciacion peso vs "
        "USD, (3) mezcla geografica desfavorable. POSITIVOS: Mexico organico +6.1%, "
        "RoW volume +20.1%, costos agave estables, AMP discipline 20.4% (dentro de "
        "guia 19-21%). Empresa completo deleveraging: Net Debt/UAFIDA 1.0x (vs 1.9x). "
        "Management RE-AFFIRMA solo guia AMP, NO actualiza revenue. Tono DEFENSIVO."
    ),
    extraction_method="claude_code_slash",
)

# Save both
fp1 = save_report(guia_2026)
fp2 = save_report(q1_26)
print(f"OK Guia 2026: {fp1.name}")
print(f"   - {len(guia_2026.guidance)} guidance items")
print(f"   - {len(guia_2026.events)} events")
print(f"   - Sentiment: {guia_2026.sentiment.tone} ({guia_2026.sentiment.score})")
print()
print(f"OK 1T26 Earnings: {fp2.name}")
print(f"   - {len(q1_26.guidance)} guidance items (AMP reaffirm)")
print(f"   - {len(q1_26.drivers)} drivers identificados")
print(f"   - {len(q1_26.events)} events (b:oost divestiture, deleveraging)")
print(f"   - Sentiment: {q1_26.sentiment.tone} ({q1_26.sentiment.score})")
print()
print("=" * 60)
print("REPORTS REALES DE CUERVO GUARDADOS")
print("=" * 60)
