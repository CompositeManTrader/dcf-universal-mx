"""Loader de config YAML (sectors + issuers)."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass
class SectorDefaults:
    key: str
    name: str
    beta_unlevered: float
    sales_to_capital: float
    target_op_margin: float
    is_financial: bool = False
    is_reit: bool = False


@dataclass
class IssuerInfo:
    ticker: str
    name: str
    sector: str
    market_price: float
    yahoo: Optional[str] = None
    xbrl_url: Optional[str] = None        # URL directa al .zip / .xls del XBRL (opcional)
    dcf_override: Optional[dict] = None    # overrides para target_op_margin, sales_to_capital, etc


@dataclass
class MarketDefaults:
    risk_free: float
    erp: float
    marginal_tax: float
    terminal_growth: float
    terminal_wacc_override: Optional[float]
    revenue_growth_high: float
    forecast_years: int
    high_growth_years: int
    fx_rate_usdmxn: float = 19.50


@lru_cache(maxsize=1)
def load_sectors(path: Optional[Path] = None) -> dict[str, SectorDefaults]:
    p = path or _project_root() / "config" / "sectors.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = {}
    for k, v in raw.items():
        out[k] = SectorDefaults(
            key=k,
            name=v["name"],
            beta_unlevered=float(v["beta_unlevered"]),
            sales_to_capital=float(v["sales_to_capital"]),
            target_op_margin=float(v["target_op_margin"]),
            is_financial=bool(v.get("is_financial", False)),
            is_reit=bool(v.get("is_reit", False)),
        )
    return out


@lru_cache(maxsize=1)
def load_issuers(path: Optional[Path] = None) -> tuple[MarketDefaults, dict[str, IssuerInfo]]:
    p = path or _project_root() / "config" / "issuers.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    md = raw.get("market_defaults", {})
    market = MarketDefaults(
        risk_free=float(md["risk_free"]),
        erp=float(md["erp"]),
        marginal_tax=float(md.get("marginal_tax", 0.30)),
        terminal_growth=float(md.get("terminal_growth", 0.03)),
        terminal_wacc_override=float(md["terminal_wacc_override"]) if md.get("terminal_wacc_override") is not None else None,
        revenue_growth_high=float(md.get("revenue_growth_high", 0.05)),
        forecast_years=int(md.get("forecast_years", 10)),
        high_growth_years=int(md.get("high_growth_years", 5)),
        fx_rate_usdmxn=float(md.get("fx_rate_usdmxn", 19.50)),
    )
    issuers = {}
    for tkr, v in raw.get("issuers", {}).items():
        issuers[tkr] = IssuerInfo(
            ticker=tkr,
            name=v["name"],
            sector=v["sector"],
            market_price=float(v["market_price"]),
            yahoo=v.get("yahoo"),
            xbrl_url=v.get("xbrl_url"),
            dcf_override=v.get("dcf_override"),
        )
    return market, issuers


def find_xbrl(ticker: str, raw_dir: Optional[Path] = None) -> Optional[Path]:
    """Busca el XBRL local mas reciente para un ticker."""
    raw_dir = raw_dir or _project_root() / "data" / "raw_xbrl"
    if not raw_dir.exists():
        return None
    # Ej: ifrsxbrl_CUERVO_2025-4.xls / ifrsxbrl_CUERVO_2024-4.xls
    candidates = sorted(raw_dir.glob(f"ifrsxbrl_{ticker}_*.xls*"), reverse=True)
    return candidates[0] if candidates else None


def find_all_xbrl(ticker: str, raw_dir: Optional[Path] = None) -> list[Path]:
    """Devuelve TODOS los XBRL locales de un ticker, ordenados por periodo asc.

    Convencion de nombre: ifrsxbrl_<TICKER>_<YYYY>-<Q>.xls
    Donde Q puede ser '1', '2', '3', '4', o '4D' (4to dictaminado/anual).
    """
    raw_dir = raw_dir or _project_root() / "data" / "raw_xbrl"
    if not raw_dir.exists():
        return []
    return sorted(raw_dir.glob(f"ifrsxbrl_{ticker}_*.xls*"))


def parse_period_tag(filepath: Path) -> tuple[int, str]:
    """Extrae (year, quarter) del nombre del archivo.

    'ifrsxbrl_CUERVO_2025-4D.xls' -> (2025, '4D')
    'ifrsxbrl_CUERVO_2024-1.xls'  -> (2024, '1')
    """
    stem = filepath.stem  # 'ifrsxbrl_CUERVO_2025-4D'
    parts = stem.split("_")
    if len(parts) < 3:
        return (0, "")
    period_part = parts[-1]   # '2025-4D'
    if "-" not in period_part:
        return (0, "")
    year_str, q_str = period_part.split("-", 1)
    try:
        return (int(year_str), q_str.upper())
    except ValueError:
        return (0, q_str)


def is_annual_period(quarter: str) -> bool:
    """Q '4D' = anual dictaminado. Q '4' = trimestre Q4 preliminar."""
    return quarter.upper() == "4D"
