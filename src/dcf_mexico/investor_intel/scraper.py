"""
Auto-scraping de IR sites de emisoras IPC.

Pipeline:
1. Lee config YAML por emisora (URL IR, file patterns)
2. Detecta nuevos PDFs no procesados
3. Descarga y los procesa con extractor.py
4. Guarda InvestorReport via storage.py
5. Auto-commit a GitHub si configurado

Diseñado para ejecutarse via GitHub Actions cron diario.
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import List, Optional, Dict
from pathlib import Path

try:
    import requests
    from urllib.parse import urljoin
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ============================================================================
# Config por emisora
# ============================================================================

@dataclass
class IRSiteConfig:
    """Config de un site IR de una emisora."""
    ticker: str
    company_name: str
    ir_url: str
    earnings_pattern: str = ""              # regex para detectar PDFs de earnings
    presentation_pattern: str = ""
    guidance_pattern: str = ""
    annual_report_pattern: str = ""
    press_release_pattern: str = ""
    enabled: bool = True
    notes: str = ""


# Catalogo inicial (expandir con todas las 35 IPC)
IR_SITES: Dict[str, IRSiteConfig] = {
    "CUERVO": IRSiteConfig(
        ticker="CUERVO",
        company_name="Becle, S.A.B. de C.V.",
        ir_url="https://ir.cuervo.com.mx/",
        earnings_pattern=r"(\d)T(\d{2})[\s_-].*Reporte.*\.pdf",
        presentation_pattern=r"(?:RI|IR).*Presentaci[oó]n.*\.pdf",
        guidance_pattern=r"(?:Gu[ií]a|Guidance).*\.pdf",
        annual_report_pattern=r"(?:Annual|Anual).*\.pdf",
        press_release_pattern=r"(?:Comunicado|Press[\s_-]?Release).*\.pdf",
        enabled=True,
    ),
    "KOF": IRSiteConfig(
        ticker="KOF",
        company_name="Coca-Cola FEMSA",
        ir_url="https://coca-colafemsa.com/inversionistas/",
        earnings_pattern=r"(\d)Q(\d{4}).*\.pdf",
        enabled=False,    # placeholder hasta agregar scraper
    ),
    "AMX": IRSiteConfig(
        ticker="AMX",
        company_name="América Móvil",
        ir_url="https://www.americamovil.com/inversionistas",
        enabled=False,
    ),
    "FEMSA": IRSiteConfig(
        ticker="FEMSA",
        company_name="FEMSA",
        ir_url="https://www.femsa.com/es/inversionistas/",
        enabled=False,
    ),
    "WALMEX": IRSiteConfig(
        ticker="WALMEX",
        company_name="Walmart de México",
        ir_url="https://www.walmex.mx/inversionistas/",
        enabled=False,
    ),
    "GFNORTE": IRSiteConfig(
        ticker="GFNORTE",
        company_name="Grupo Financiero Banorte",
        ir_url="https://investors.banorte.com/es",
        enabled=False,
    ),
    "CEMEX": IRSiteConfig(
        ticker="CEMEX",
        company_name="CEMEX",
        ir_url="https://www.cemex.com/investors",
        enabled=False,
    ),
    "BIMBO": IRSiteConfig(
        ticker="BIMBO",
        company_name="Grupo Bimbo",
        ir_url="https://www.grupobimbo.com/es/inversionistas",
        enabled=False,
    ),
}


# ============================================================================
# Pipeline scraper (placeholder con estructura)
# ============================================================================

@dataclass
class ScrapedFile:
    """Un PDF detectado en un IR site."""
    ticker: str
    url: str
    filename: str
    file_size: int = 0
    content_hash: str = ""             # SHA-256 para detectar duplicados
    detected_type: str = ""            # earnings/guidance/etc.


def list_ir_sites() -> List[IRSiteConfig]:
    return list(IR_SITES.values())


def get_ir_config(ticker: str) -> Optional[IRSiteConfig]:
    return IR_SITES.get(ticker.upper())


def detect_pdfs_in_html(html: str, base_url: str) -> List[Tuple[str, str]]:
    """Extrae URLs de PDFs de un HTML. Returns: [(url, filename), ...]."""
    pdf_links = re.findall(r'href=["\']([^"\']+\.pdf[^"\']*)["\']',
                            html, re.IGNORECASE)
    out = []
    for link in pdf_links:
        full_url = link if link.startswith("http") else urljoin(base_url, link)
        filename = link.split("/")[-1].split("?")[0]
        out.append((full_url, filename))
    return out


def classify_pdf_type(filename: str, config: IRSiteConfig) -> Optional[str]:
    """Clasifica un PDF según patterns configurados."""
    fname_lower = filename.lower()
    patterns = [
        ("earnings_release", config.earnings_pattern),
        ("guidance_update", config.guidance_pattern),
        ("investor_presentation", config.presentation_pattern),
        ("annual_report", config.annual_report_pattern),
        ("press_release", config.press_release_pattern),
    ]
    for ptype, pattern in patterns:
        if pattern and re.search(pattern, filename, re.IGNORECASE):
            return ptype
    return None


def scrape_ir_site(config: IRSiteConfig,
                    timeout: int = 30) -> List[ScrapedFile]:
    """Scrape un site IR. Returns lista de PDFs detectados.

    NOTA: Placeholder. Cada IR site tiene estructura distinta y requiere
    parser custom. Este es un esqueleto.
    """
    if not HAS_REQUESTS:
        return []
    if not config.enabled:
        return []

    try:
        r = requests.get(config.ir_url, timeout=timeout)
        r.raise_for_status()
        html = r.text
    except Exception as e:
        print(f"Error scraping {config.ticker}: {e}")
        return []

    pdfs = detect_pdfs_in_html(html, config.ir_url)
    out = []
    for url, fname in pdfs:
        ptype = classify_pdf_type(fname, config)
        out.append(ScrapedFile(
            ticker=config.ticker,
            url=url,
            filename=fname,
            detected_type=ptype or "unknown",
        ))
    return out


def scrape_all_enabled() -> Dict[str, List[ScrapedFile]]:
    """Scrape todos los IR sites habilitados."""
    out = {}
    for ticker, config in IR_SITES.items():
        if not config.enabled:
            continue
        out[ticker] = scrape_ir_site(config)
    return out


# Placeholder: tuple type for type hint
from typing import Tuple
