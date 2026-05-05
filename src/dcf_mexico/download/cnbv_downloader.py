"""
Downloader de XBRL CNBV.

Estrategia (en orden):
  1. Si `xbrl_url` esta definido en config/issuers.yaml para el ticker, lo usa directo.
  2. Si no, scrapea la pagina de la emisora en BMV buscando el ZIP mas reciente
     (anexotbol_*.zip).
  3. Si nada funciona, devuelve un DownloadResult con instrucciones manuales.

Notas:
  - Las paginas de BMV tienen JavaScript pesado en algunos casos. El scraper
    solo busca links HTML estaticos. Si la pagina los oculta tras JS, el
    fallback manual es necesario.
  - Streamlit Cloud no tiene salida HTTP a sites externos en algunas
    configuraciones; este modulo se usa principalmente desde CLI local.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import requests

from ..config import load_issuers, IssuerInfo


# URLs raiz / patrones
BMV_EMISORA_URL = "https://www.bmv.com.mx/es/emisoras/perfil/{ticker}"
BMV_DOCS_BASE = "https://www.bmv.com.mx"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

XBRL_LINK_RE = re.compile(
    r'href="([^"]*(?:anexotbol|ifrsxbrl)[^"]*\.(?:zip|xls|xlsx))"',
    re.IGNORECASE,
)


@dataclass
class DownloadResult:
    ticker: str
    ok: bool
    method: str           # "config_url", "scraped", "manual_required", "cached"
    saved_path: Optional[Path] = None
    source_url: Optional[str] = None
    error: str = ""


def _http_get(url: str, timeout: int = 30) -> requests.Response:
    return requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)


def _save_xbrl_from_response(
    resp: requests.Response,
    ticker: str,
    period_tag: str,
    raw_dir: Path,
) -> Path:
    """Guarda el contenido como ifrsxbrl_<TICKER>_<period>.xls/.xlsx.
    Si es zip, extrae el primer xls/xlsx interno."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    content = resp.content

    # Detectar zip por magic bytes (PK\x03\x04)
    if content[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            xls_members = [n for n in zf.namelist() if n.lower().endswith((".xls", ".xlsx"))]
            if not xls_members:
                raise ValueError(f"ZIP sin .xls/.xlsx adentro: {zf.namelist()}")
            inner = xls_members[0]
            ext = Path(inner).suffix.lower()
            target = raw_dir / f"ifrsxbrl_{ticker}_{period_tag}{ext}"
            with zf.open(inner) as f:
                target.write_bytes(f.read())
            return target

    # Asumir xls/xlsx directo
    ext = ".xlsx" if content[:4] == b"PK\x03\x04" else ".xls"
    target = raw_dir / f"ifrsxbrl_{ticker}_{period_tag}{ext}"
    target.write_bytes(content)
    return target


def _scrape_bmv_for_xbrl_url(ticker: str) -> Optional[str]:
    """Best-effort: busca link a anexotbol .zip en la pagina de la emisora."""
    url = BMV_EMISORA_URL.format(ticker=ticker)
    try:
        resp = _http_get(url)
        if resp.status_code != 200:
            return None
    except Exception:
        return None

    matches = XBRL_LINK_RE.findall(resp.text)
    if not matches:
        return None
    # Elegir el mas reciente: heuristica = el ultimo en orden alfabetico (los nombres incluyen fecha)
    matches_full = [urljoin(BMV_DOCS_BASE, m) for m in matches]
    matches_full.sort(reverse=True)
    return matches_full[0]


def download_xbrl_for_ticker(
    ticker: str,
    period_tag: str = "2025-4",
    raw_dir: Optional[Path] = None,
    issuer: Optional[IssuerInfo] = None,
    explicit_url: Optional[str] = None,
    overwrite: bool = False,
) -> DownloadResult:
    """
    Descarga XBRL para un ticker. Estrategia:
      - explicit_url > issuer.xbrl_url > scraping > manual fallback
    """
    project_root = Path(__file__).resolve().parents[3]
    raw_dir = raw_dir or project_root / "data" / "raw_xbrl"

    # Check cache
    existing = sorted(raw_dir.glob(f"ifrsxbrl_{ticker}_{period_tag}.*"))
    if existing and not overwrite:
        return DownloadResult(
            ticker=ticker, ok=True, method="cached",
            saved_path=existing[0],
            source_url=None,
        )

    # Resolve URL
    url = explicit_url
    method = "explicit_url"
    if url is None and issuer is not None:
        url = getattr(issuer, "xbrl_url", None)
        if url:
            method = "config_url"

    if url is None:
        url = _scrape_bmv_for_xbrl_url(ticker)
        if url:
            method = "scraped"

    if url is None:
        return DownloadResult(
            ticker=ticker, ok=False, method="manual_required",
            error=(
                f"No se pudo resolver URL para {ticker}. "
                f"Descarga manual desde: {BMV_EMISORA_URL.format(ticker=ticker)} "
                f"y guarda como {raw_dir}/ifrsxbrl_{ticker}_{period_tag}.xls"
            ),
        )

    try:
        resp = _http_get(url, timeout=60)
        if resp.status_code != 200:
            return DownloadResult(
                ticker=ticker, ok=False, method=method, source_url=url,
                error=f"HTTP {resp.status_code} al descargar",
            )
        path = _save_xbrl_from_response(resp, ticker, period_tag, raw_dir)
        return DownloadResult(
            ticker=ticker, ok=True, method=method,
            saved_path=path, source_url=url,
        )
    except Exception as e:
        return DownloadResult(
            ticker=ticker, ok=False, method=method, source_url=url,
            error=f"Error descargando: {e}",
        )


def download_all(
    period_tag: str = "2025-4",
    raw_dir: Optional[Path] = None,
    overwrite: bool = False,
    only_missing: bool = True,
) -> list[DownloadResult]:
    """Itera sobre todos los issuers en config y descarga lo que falte."""
    _, issuers = load_issuers()
    results = []
    for ticker, issuer in sorted(issuers.items()):
        results.append(
            download_xbrl_for_ticker(
                ticker, period_tag=period_tag, raw_dir=raw_dir,
                issuer=issuer, overwrite=overwrite,
            )
        )
    return results
