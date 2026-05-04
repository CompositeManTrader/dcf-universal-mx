---
description: Extract structured InvestorReport JSON from a PDF (no API needed)
allowed-tools: Read, Write, Bash, Glob
argument-hint: <TICKER> <pdf_path>
---

# Extract Investor Report

Procesar un PDF de Investor Relations de una emisora IPC mexicana y guardar el resultado como JSON estructurado en `data/investor_reports/{TICKER}/`.

## Arguments

- **$1 (TICKER)**: Símbolo de la emisora (e.g. CUERVO, KOF, AMX)
- **$2 (pdf_path)**: Ruta al archivo PDF (relativa o absoluta)

## What to do

1. **Read the PDF** at `$2` using the Read tool (Claude Code soporta PDFs nativamente vía Read)

2. **Identify report metadata**:
   - Date (de la portada o footer del PDF)
   - Period covered (FY, 1Q, 2Q, etc.)
   - Report type: earnings_release / guidance_update / investor_presentation / annual_report / press_release / conference_call / investor_day / other
   - Title

3. **Extract structured data** following this exact JSON schema:

```json
{
  "ticker": "$1",
  "report_date": "YYYY-MM-DD",
  "period_covered": "FY2026 | 1Q26 | etc.",
  "report_type": "guidance_update | earnings_release | etc.",
  "title": "Título del documento",
  "pdf_filename": "nombre del archivo PDF",
  "guidance": [
    {
      "metric": "Revenue Growth (Constant Currency)",
      "period": "FY2026",
      "value_low": -3.0,
      "value_high": -1.0,
      "value_point": null,
      "unit": "%",
      "direction": "decline",
      "confidence": "medium",
      "qualitative_text": "Caída en el rango bajo de un solo dígito",
      "notes": ""
    }
  ],
  "drivers": [
    {
      "category": "Volume | Price | FX | Mix | M&A | Cost",
      "description": "Descripción del driver",
      "impact": "🟢 Positive | 🔴 Negative | ⚪ Neutral | 🟡 Mixed",
      "materiality": "high | medium | low",
      "quote": "Cita textual si aparece"
    }
  ],
  "events": [
    {
      "event_type": "M&A (acquisition / divestiture) | Share buyback | Dividend announcement | CapEx plan | New product launch | Capacity expansion | Management change | Debt issuance / refinance | Legal / regulatory | Other material event",
      "title": "Título del evento",
      "description": "Detalle",
      "event_date": "YYYY-MM-DD o null",
      "financial_impact": "Cuantificación si disponible",
      "materiality": "high | medium | low"
    }
  ],
  "sentiment": {
    "tone": "🟢 Optimistic | 🟢 Positive | ⚪ Neutral | 🟡 Cautious | 🟠 Defensive | 🔴 Negative",
    "score": -0.3,
    "confidence": "high | medium | low",
    "rationale": "Por qué este tono"
  },
  "key_topics": ["topic 1", "topic 2", "topic 3"],
  "summary_es": "Resumen ejecutivo en español, 3-5 oraciones, foco en lo MATERIAL para inversionista.",
  "summary_en": "",
  "extraction_method": "claude_code_slash",
  "extraction_date": "ISO timestamp now",
  "extraction_notes": ""
}
```

## Reglas de extracción

- **Guidance numérica**: extraer value_low/value_high del rango.
- **Guidance cualitativa** ("low single digit decline" etc.):
  - "low single digit decline" → value_low=-3.0, value_high=-1.0
  - "mid single digit growth" → value_low=4.0, value_high=6.0
  - "high single digit" → value_low=7.0, value_high=9.0
  - "double digit" → value_low=10.0, value_high=15.0
- **CapEx en USD M**: unit="USD M", value_low/high del rango.
- **AMP/marketing como %**: unit="%".
- **Sentiment score** (escala):
  - Optimistic: 0.6 a 1.0
  - Positive: 0.3 a 0.6
  - Neutral: -0.2 a 0.3
  - Cautious: -0.5 a -0.2
  - Defensive: -0.7 a -0.5
  - Negative: -1.0 a -0.7
- Si NO encuentras un campo, déjalo vacío `""` o `null`.
- summary_es: máx 5 oraciones, foco MATERIAL.

## Save to disk

4. **Copiar el PDF** al repo: `data/investor_reports/{TICKER}/pdfs/{filename}.pdf`
   (para que se pueda visualizar inline en Streamlit)
   - Usar Bash `cp` o `Write` con bytes del PDF
   - Crear directorio `pdfs/` si no existe

5. **Generate filename JSON**: `{TICKER}_{report_date}_{report_type}.json`
   Example: `CUERVO_2026-02-27_guidance_update.json`

6. **Write JSON to**: `data/investor_reports/{TICKER}/{filename}.json`
   Crear directorio si no existe.
   Asegurar que el JSON tenga `pdf_local_path` apuntando al PDF copiado:
   ```
   "pdf_local_path": "data/investor_reports/CUERVO/pdfs/Guia2026.pdf"
   ```

7. **Validate** que el JSON es parseable con Python `json.loads()`.

## (Opcional) GitHub commit

8. Si el usuario tiene GitHub configurado y lo pide, hacer commit con mensaje:
   ```
   intel({ticker.lower()}): add {report_type} {period_covered} ({report_date})
   ```
   Incluir tanto el JSON como el PDF en el commit.

## Output

Reportar al usuario:
- ✅ Path del JSON guardado
- 📊 Counts: # guidance items, # drivers, # events
- 🎯 Sentiment tone + score
- 📝 Summary 1-2 líneas
