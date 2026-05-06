"""
Damodaran Reference Tables loader.

Carga las tablas oficiales de Damodaran (Country ERP, Industry Beta,
Synthetic Rating, Failure Rate guide) desde YAML/Python statics.

Source: https://pages.stern.nyu.edu/~adamodar/New_Home_Page/dataarchived.html
        Datos Jan-2026 (actualizar 1x/año típicamente).
"""
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional
import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


# ============================================================================
# Country Equity Risk Premiums
# ============================================================================

@dataclass
class CountryERP:
    code: str          # ISO-2 (US, MX, BR, ...)
    name: str
    region: str
    rating: str        # Sovereign rating Moody's
    crp: float         # Country Risk Premium (decimal)
    total_erp: float   # mature_ERP + CRP
    tax_rate: float    # Statutory corporate tax


@lru_cache(maxsize=1)
def load_country_erp(path: Optional[Path] = None) -> tuple[float, dict[str, CountryERP]]:
    """Devuelve (mature_erp, {code: CountryERP}). Cache global."""
    p = path or _project_root() / "config" / "damodaran_country_erp.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    mature = float(raw["mature_erp"])
    out = {}
    for code, v in raw["countries"].items():
        out[code] = CountryERP(
            code=code,
            name=v["name"],
            region=v["region"],
            rating=v.get("rating", ""),
            crp=float(v["crp"]),
            total_erp=float(v["total_erp"]),
            tax_rate=float(v["tax_rate"]),
        )
    return mature, out


def get_country_erp(code: str) -> Optional[CountryERP]:
    _, table = load_country_erp()
    return table.get(code.upper())


# ============================================================================
# Industry Beta (Global)
# ============================================================================

@dataclass
class IndustryBeta:
    key: str
    name: str
    beta_unlevered: float
    d_e_ratio: float
    tax_rate: float
    sales_to_capital: float
    target_op_margin: float
    roic: float
    notes: str = ""


@lru_cache(maxsize=1)
def load_industry_betas(path: Optional[Path] = None) -> dict[str, IndustryBeta]:
    p = path or _project_root() / "config" / "damodaran_industry_betas.yaml"
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    out = {}
    for key, v in raw["industries"].items():
        out[key] = IndustryBeta(
            key=key,
            name=v["name"],
            beta_unlevered=float(v["beta_unlevered"]),
            d_e_ratio=float(v["d_e_ratio"]),
            tax_rate=float(v["tax_rate"]),
            sales_to_capital=float(v["sales_to_capital"]),
            target_op_margin=float(v["target_op_margin"]),
            roic=float(v["roic"]),
            notes=v.get("notes", ""),
        )
    return out


def get_industry_beta(key: str) -> Optional[IndustryBeta]:
    return load_industry_betas().get(key)


# ============================================================================
# Synthetic Rating Table (de wacc.py, expuesta para UI)
# ============================================================================

SYNTHETIC_RATING_TABLE = [
    # (interest_coverage_min, rating, default_spread)
    (8.50,  "Aaa/AAA",   0.0050),
    (6.50,  "Aa2/AA",    0.0080),
    (5.50,  "A1/A+",     0.0100),
    (4.25,  "A2/A",      0.0120),
    (3.00,  "A3/A-",     0.0150),
    (2.50,  "Baa2/BBB",  0.0200),
    (2.25,  "Ba1/BB+",   0.0285),
    (2.00,  "Ba2/BB",    0.0367),
    (1.75,  "B1/B+",     0.0450),
    (1.50,  "B2/B",      0.0567),
    (1.25,  "B3/B-",     0.0814),
    (0.80,  "Caa/CCC",   0.1117),
    (0.65,  "Ca2/CC",    0.1417),
    (0.20,  "C2/C",      0.1500),
    (-1e9,  "D2/D",      0.1900),
]


# ============================================================================
# Failure Rate Reference Guide
# ============================================================================

FAILURE_RATE_GUIDE = [
    {
        "stage": "Idea / Pre-revenue",
        "p_fail_low": 0.60, "p_fail_high": 0.80, "p_fail_typical": 0.70,
        "examples": "Startups sin ingresos, biotech preclínica, dev mining",
        "color": "🔴",
    },
    {
        "stage": "Early stage / Burning cash",
        "p_fail_low": 0.30, "p_fail_high": 0.50, "p_fail_typical": 0.40,
        "examples": "Series A-B, growth companies con ebitda neg",
        "color": "🟠",
    },
    {
        "stage": "Growth (rentable, expansión)",
        "p_fail_low": 0.10, "p_fail_high": 0.20, "p_fail_typical": 0.15,
        "examples": "Series C+ rentables, mid-cap en crecimiento",
        "color": "🟡",
    },
    {
        "stage": "Mature stable (defensive)",
        "p_fail_low": 0.02, "p_fail_high": 0.05, "p_fail_typical": 0.035,
        "examples": "Walmex, FEMSA, AMX en steady state",
        "color": "🟢",
    },
    {
        "stage": "Blue chip / IG rating (BBB+)",
        "p_fail_low": 0.00, "p_fail_high": 0.01, "p_fail_typical": 0.005,
        "examples": "CUERVO, KOFL, GMEXICO con BB-/BBB+ ratings",
        "color": "🟢",
    },
    {
        "stage": "Distressed (junk, restructuring)",
        "p_fail_low": 0.20, "p_fail_high": 0.50, "p_fail_typical": 0.35,
        "examples": "Pemex, ICA pre-restructuración, AMX cuando High Yield",
        "color": "🔴",
    },
]
