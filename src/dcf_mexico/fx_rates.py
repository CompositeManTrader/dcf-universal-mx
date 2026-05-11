"""
USDMXN FX rates históricos por trimestre (Banxico-sourced).

Resuelve el bug de usar FX constante (e.g., 19.50) para todos los
periodos cuando en realidad fluctúa cada trimestre. Crítico para
emisoras que reportan en USD (GMEXICO, CEMEX, ORBIA, KOF).

Convención:
  - eop: end of period (cierre del trimestre) → usar para BALANCE SHEET
  - avg: promedio del trimestre → usar para INCOME STATEMENT / cashflow

Referencia: https://www.banxico.org.mx/SieInternet/

Funciones:
  - get_usdmxn_eop(date_str): FX cierre de periodo
  - get_usdmxn_avg(date_str): FX promedio del periodo
  - get_usdmxn(date_str, kind="avg"): wrapper conveniente
  - get_spot_rate(): FX spot reciente (para DCF forward-looking)
  - get_constant_currency_rate(): rate de referencia para constant
                                    currency analysis (= último spot)
"""
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional
import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def _load_fx_data() -> dict:
    """Carga el YAML una sola vez (cached)."""
    p = _project_root() / "config" / "fx_rates_historic.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _normalize_date(date_str: str) -> str:
    """Acepta '2025-12-31' o '20251231' y devuelve '2025-12-31'."""
    s = str(date_str).strip()
    if len(s) == 10 and "-" in s:
        return s
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    # Try parse and format
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.strftime("%Y-%m-%d")
    except Exception:
        return s


def _find_closest_quarter(date_str: str, fx_data: dict) -> Optional[str]:
    """Si la fecha exacta no existe, busca el cierre de trimestre más cercano
    (anterior, para no usar un FX futuro para datos pasados)."""
    target = _normalize_date(date_str)
    quarterly = fx_data.get("quarterly", {})

    # Match exacto
    if target in quarterly:
        return target

    # Buscar el cierre de trimestre más reciente <= target
    target_dt = datetime.strptime(target, "%Y-%m-%d")
    candidates = []
    for k in quarterly.keys():
        try:
            k_dt = datetime.strptime(k, "%Y-%m-%d")
            if k_dt <= target_dt:
                candidates.append((k_dt, k))
        except Exception:
            continue

    if candidates:
        candidates.sort(reverse=True)   # más reciente primero
        return candidates[0][1]
    return None


def get_usdmxn_eop(date_str: str) -> float:
    """USDMXN al cierre del periodo. Usar para BALANCE SHEET items.

    Args:
        date_str: 'YYYY-MM-DD' (e.g., '2025-12-31')

    Returns:
        float: USDMXN rate. Fallback al default si no se encuentra match.
    """
    fx = _load_fx_data()
    matched = _find_closest_quarter(date_str, fx)
    if matched and matched in fx["quarterly"]:
        return float(fx["quarterly"][matched]["eop"])
    return float(fx.get("default_fallback", 20.0))


def get_usdmxn_avg(date_str: str) -> float:
    """USDMXN promedio del periodo. Usar para INCOME STATEMENT / CASHFLOW
    (Damodaran convention para flujos = TC promedio).

    Args:
        date_str: 'YYYY-MM-DD'

    Returns:
        float: USDMXN rate.
    """
    fx = _load_fx_data()
    matched = _find_closest_quarter(date_str, fx)
    if matched and matched in fx["quarterly"]:
        return float(fx["quarterly"][matched]["avg"])
    return float(fx.get("default_fallback", 20.0))


def get_usdmxn(date_str: str, kind: str = "avg") -> float:
    """Wrapper. kind = 'avg' (income/cashflow) o 'eop' (balance)."""
    if kind == "eop":
        return get_usdmxn_eop(date_str)
    return get_usdmxn_avg(date_str)


def get_spot_rate() -> float:
    """USDMXN spot reciente. Usar para DCF forward-looking
    (valuamos hoy, así que usamos FX hoy)."""
    fx = _load_fx_data()
    return float(fx.get("spot", {}).get("rate", 20.0))


def get_constant_currency_rate() -> float:
    """Rate de referencia para constant currency analysis.
    Por convención usamos el spot (el más reciente) para que las
    comparaciones históricas se hagan al FX de HOY (lo que el negocio
    representaría en pesos actuales)."""
    return get_spot_rate()


def list_available_periods() -> list[str]:
    """Lista todas las fechas con FX disponible (para UI)."""
    fx = _load_fx_data()
    return sorted(fx.get("quarterly", {}).keys())


def get_period_breakdown(date_str: str) -> dict:
    """Devuelve un dict con eop, avg y info de cuál fecha usó (para diagnóstico).

    Returns:
        {"date_used": ..., "eop": ..., "avg": ..., "is_exact_match": bool,
         "spot_for_reference": ...}
    """
    fx = _load_fx_data()
    matched = _find_closest_quarter(date_str, fx)
    if matched and matched in fx["quarterly"]:
        data = fx["quarterly"][matched]
        return {
            "date_used": matched,
            "eop": float(data["eop"]),
            "avg": float(data["avg"]),
            "is_exact_match": (matched == _normalize_date(date_str)),
            "spot_for_reference": get_spot_rate(),
        }
    return {
        "date_used": "fallback",
        "eop": float(fx.get("default_fallback", 20.0)),
        "avg": float(fx.get("default_fallback", 20.0)),
        "is_exact_match": False,
        "spot_for_reference": get_spot_rate(),
    }
