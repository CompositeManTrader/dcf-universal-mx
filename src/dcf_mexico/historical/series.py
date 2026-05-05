"""
HistoricalSeries: estructura para multi-period de un ticker.

Carga TODOS los XBRL disponibles de un ticker desde data/raw_xbrl/, los
parsea (con cache), y devuelve un objeto navegable por periodo.

Convencion de naming:
    ifrsxbrl_<TICKER>_<YYYY>-<Q>.xls
Donde Q es uno de:
    '4D' -> Q4 dictaminado (anual auditado)
    '1', '2', '3', '4' -> trimestres
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from dcf_mexico.config import find_all_xbrl, parse_period_tag, is_annual_period
from dcf_mexico.parse import parse_xbrl


@dataclass
class PeriodSnapshot:
    """Un periodo (1 archivo XBRL) parseado, con metadata facil de query."""
    period_tag: str       # "2025-4D" o "2024-1"
    year: int             # 2025
    quarter: str          # "4D" o "1"
    is_annual: bool       # True si quarter == "4D"
    period_end: str       # "2025-12-31" del XBRL (info.period_end)
    filepath: Path
    parsed: object        # ParseResult del parser

    @property
    def label(self) -> str:
        """Etiqueta para display: 'FY 2024' o 'Q1 2025' o 'Q4 2025'."""
        if self.is_annual:
            return f"FY {self.year}"
        return f"Q{self.quarter} {self.year}"

    @property
    def sort_key(self) -> tuple:
        """Key para sortear: (year, quarter_num). 4D al final del año."""
        q_map = {"1": 1, "2": 2, "3": 3, "4": 4, "4D": 5}  # 4D despues de 4 preliminar
        return (self.year, q_map.get(self.quarter, 0))


@dataclass
class HistoricalSeries:
    ticker: str
    snapshots: list[PeriodSnapshot] = field(default_factory=list)

    @property
    def annual(self) -> list[PeriodSnapshot]:
        """Periodos anuales: prefiere 4D (auditado); si no existe para un año,
        usa Q4 (acum YTD = FY). Esto permite que emisoras sin reporte
        dictaminado todavia tengan vista anual."""
        # Por año, prefiere 4D; fallback a Q4
        by_year_4d = {s.year: s for s in self.snapshots if s.quarter == "4D"}
        by_year_q4 = {s.year: s for s in self.snapshots if s.quarter == "4"}
        years = sorted(set(list(by_year_4d.keys()) + list(by_year_q4.keys())))
        result = []
        for y in years:
            if y in by_year_4d:
                result.append(by_year_4d[y])
            elif y in by_year_q4:
                result.append(by_year_q4[y])
        return result

    @property
    def annual_strict(self) -> list[PeriodSnapshot]:
        """Solo periodos 4D (auditados estrictos), sin fallback a Q4."""
        return [s for s in self.snapshots if s.is_annual]

    @property
    def quarterly(self) -> list[PeriodSnapshot]:
        """Solo trimestrales (1, 2, 3, 4 - excluye 4D)."""
        return [s for s in self.snapshots if not s.is_annual]

    @property
    def latest(self) -> Optional[PeriodSnapshot]:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def n_periods(self) -> int:
        return len(self.snapshots)

    @property
    def n_annual(self) -> int:
        return len(self.annual)

    @property
    def n_quarterly(self) -> int:
        return len(self.quarterly)

    def get_snapshot(self, period_tag: str) -> Optional[PeriodSnapshot]:
        for s in self.snapshots:
            if s.period_tag == period_tag:
                return s
        return None

    def coverage_summary(self) -> pd.DataFrame:
        rows = [{
            "period_tag": s.period_tag,
            "label":      s.label,
            "kind":       "Annual" if s.is_annual else "Quarterly",
            "period_end": s.period_end,
            "filename":   s.filepath.name,
        } for s in self.snapshots]
        return pd.DataFrame(rows)


def load_historical(ticker: str, raw_dir: Optional[Path] = None,
                     parse_func=None) -> HistoricalSeries:
    """Carga TODOS los XBRL disponibles de un ticker.

    Por defecto usa parse_xbrl() del parser. Pasar `parse_func=cached_parser`
    si tienes un wrapper con cache (ej. en Streamlit con @st.cache_data).
    """
    parse_func = parse_func or parse_xbrl
    files = find_all_xbrl(ticker, raw_dir=raw_dir)

    snapshots = []
    for fp in files:
        year, quarter = parse_period_tag(fp)
        if year == 0:
            continue
        try:
            parsed = parse_func(fp)
        except Exception:
            continue   # skip archivos rotos
        snap = PeriodSnapshot(
            period_tag=f"{year}-{quarter}",
            year=year,
            quarter=quarter,
            is_annual=is_annual_period(quarter),
            period_end=parsed.info.period_end,
            filepath=fp,
            parsed=parsed,
        )
        snapshots.append(snap)

    # Sort cronologico (4D viene despues del 4 preliminar del mismo año)
    snapshots.sort(key=lambda s: s.sort_key)

    return HistoricalSeries(ticker=ticker, snapshots=snapshots)
