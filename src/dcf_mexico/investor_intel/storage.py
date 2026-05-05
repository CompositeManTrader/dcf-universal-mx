"""
Storage layer para Investor Reports.

Guarda JSONs en data/investor_reports/{ticker}/{report_id}.json
y opcionalmente commitea al repo via GitHub API (mismo flow que XBRLs).
"""
import json
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime

from .schema import InvestorReport


# ============================================================================
# Filesystem storage
# ============================================================================

def get_storage_root(base_dir: Optional[Path] = None) -> Path:
    """Devuelve la carpeta raíz para investor reports."""
    if base_dir is None:
        # Default: relative al repo root
        from ..config import _project_root
        base_dir = _project_root() / "data" / "investor_reports"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_ticker_dir(ticker: str, base_dir: Optional[Path] = None) -> Path:
    """Devuelve la carpeta de un ticker (la crea si no existe)."""
    root = get_storage_root(base_dir)
    tdir = root / ticker.upper()
    tdir.mkdir(parents=True, exist_ok=True)
    return tdir


def get_pdfs_dir(ticker: str, base_dir: Optional[Path] = None) -> Path:
    """Devuelve la carpeta de PDFs para un ticker."""
    pdfs_dir = get_ticker_dir(ticker, base_dir) / "pdfs"
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    return pdfs_dir


def save_pdf_alongside_report(
    pdf_bytes: bytes,
    ticker: str,
    pdf_filename: str,
    base_dir: Optional[Path] = None,
) -> Path:
    """Guarda el PDF original junto con el JSON.

    Path: data/investor_reports/{TICKER}/pdfs/{filename}.pdf
    """
    pdfs_dir = get_pdfs_dir(ticker, base_dir)
    safe_filename = pdf_filename.replace("/", "_").replace("\\", "_")
    pdf_path = pdfs_dir / safe_filename
    pdf_path.write_bytes(pdf_bytes)
    return pdf_path


def load_pdf_for_report(report, base_dir: Optional[Path] = None) -> Optional[bytes]:
    """Carga el PDF original asociado a un report (si existe).

    Returns: bytes del PDF, o None si no existe.
    """
    if not report.pdf_local_path:
        return None
    from ..config import _project_root
    repo_root = _project_root() if base_dir is None else base_dir.parent.parent
    pdf_full = repo_root / report.pdf_local_path
    if pdf_full.exists():
        return pdf_full.read_bytes()
    # Try fallback al pdf_filename en pdfs_dir
    pdfs_dir = get_pdfs_dir(report.ticker, base_dir)
    fallback = pdfs_dir / report.pdf_filename
    if fallback.exists():
        return fallback.read_bytes()
    return None


def save_report(report: InvestorReport, base_dir: Optional[Path] = None) -> Path:
    """Guarda un InvestorReport como JSON.

    Filename: {report_id}.json (e.g. CUERVO_2026-02-27_guidance_update.json)
    """
    if not report.extraction_date:
        report.extraction_date = datetime.utcnow().isoformat()

    tdir = get_ticker_dir(report.ticker, base_dir)
    fname = f"{report.report_id}.json"
    fpath = tdir / fname
    fpath.write_text(report.to_json(), encoding="utf-8")
    return fpath


def load_report(filepath: Path) -> InvestorReport:
    """Carga un InvestorReport desde JSON."""
    with open(filepath, "r", encoding="utf-8") as f:
        return InvestorReport.from_json(f.read())


def load_all_reports_for_ticker(
    ticker: str, base_dir: Optional[Path] = None
) -> List[InvestorReport]:
    """Carga TODOS los reports de un ticker, ordenados por fecha desc."""
    tdir = get_ticker_dir(ticker, base_dir)
    reports = []
    for fp in tdir.glob("*.json"):
        try:
            reports.append(load_report(fp))
        except Exception as e:
            # Silently skip malformed
            print(f"Skipped {fp.name}: {e}")
    reports.sort(key=lambda r: r.report_date, reverse=True)
    return reports


def load_all_reports(
    base_dir: Optional[Path] = None,
) -> Dict[str, List[InvestorReport]]:
    """Carga TODOS los reports de TODOS los tickers."""
    root = get_storage_root(base_dir)
    out: Dict[str, List[InvestorReport]] = {}
    for tdir in root.iterdir():
        if tdir.is_dir():
            ticker = tdir.name
            out[ticker] = load_all_reports_for_ticker(ticker, base_dir)
    return out


def delete_report(report_id: str, ticker: str,
                   base_dir: Optional[Path] = None) -> bool:
    """Elimina un report por ID."""
    tdir = get_ticker_dir(ticker, base_dir)
    fpath = tdir / f"{report_id}.json"
    if fpath.exists():
        fpath.unlink()
        return True
    return False


def list_report_files(ticker: str,
                       base_dir: Optional[Path] = None) -> List[Path]:
    """Lista los archivos JSON de un ticker."""
    tdir = get_ticker_dir(ticker, base_dir)
    return sorted(tdir.glob("*.json"))


# ============================================================================
# GitHub commit (reuses github_storage from main module)
# ============================================================================

def save_and_commit_to_github(report: InvestorReport,
                                base_dir: Optional[Path] = None,
                                commit_message: Optional[str] = None) -> tuple:
    """Guarda + commit al repo GitHub si está configurado.

    Returns: (filepath, commit_result_or_None)
    """
    fpath = save_report(report, base_dir)

    # Try GitHub commit
    try:
        from ..github_storage import GitHubConfig, commit_file_to_github
        cfg = GitHubConfig.from_streamlit_secrets()
        if not cfg:
            return fpath, None

        with open(fpath, "rb") as f:
            file_bytes = f.read()

        relative_path = (f"data/investor_reports/{report.ticker.upper()}")
        msg = commit_message or (
            f"intel({report.ticker.lower()}): "
            f"add {report.report_type} {report.period_covered} "
            f"({report.report_date})"
        )

        result = commit_file_to_github(
            filename=fpath.name,
            file_bytes=file_bytes,
            config=cfg,
            target_dir=relative_path,
            commit_message=msg,
        )
        return fpath, result
    except Exception as e:
        return fpath, {"ok": False, "message": f"GitHub commit failed: {e}"}
