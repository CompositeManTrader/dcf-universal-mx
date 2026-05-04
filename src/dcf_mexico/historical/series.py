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
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config import find_all_xbrl, parse_period_tag, is_annual_period
from ..parse import parse_xbrl


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
        """Etiqueta para display: 'FY 2024', 'Q1 2025', 'TTM Q3 2026', etc."""
        if isinstance(self.quarter, str) and self.quarter.startswith("TTM"):
            # Formato 'TTM-Q3' -> 'TTM Q3 2026'
            q_part = self.quarter.split("-", 1)[1] if "-" in self.quarter else ""
            return f"TTM {q_part} {self.year}".strip()
        if self.is_annual:
            return f"FY {self.year}"
        return f"Q{self.quarter} {self.year}"

    @property
    def sort_key(self) -> tuple:
        """Key para sortear: (year, quarter_num). 4D al final del año, TTM
        después de todo (ya es trailing-12M sintético)."""
        q_map = {"1": 1, "2": 2, "3": 3, "4": 4, "4D": 5}  # 4D despues de 4 preliminar
        if isinstance(self.quarter, str) and self.quarter.startswith("TTM"):
            return (self.year, 9)  # TTM va al final
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
    def annual_with_ttm(self) -> list[PeriodSnapshot]:
        """Vista anual con regla estricta:

        1. Si **existe 4D** para el año Y → usarlo (FY auditado, completo).
        2. Si **NO existe 4D** para el año Y → construir **TTM** sumando
           explícitamente los últimos 4 trimestres disponibles que terminen
           en el último quarter conocido de Y:

               TTM = latest_q_YTD(Y) + FY_prev(Y-1) − YTD_same_q(Y-1)

           (matemáticamente equivalente a Q1Δ + Q2Δ + Q3Δ + Q4Δ)

        Esto garantiza que **nunca** se muestre Q4 acumulado solo como
        proxy de FY si el reporte 4D dictaminado no existe — siempre
        se construye TTM explícito de 12 meses verificable contra la
        suma de trimestres.

        Balance Sheet usa el último trimestre tal cual (es stock).
        """
        if not self.snapshots:
            return []

        # Indexar por año
        by_year: dict[int, list] = {}
        for s in self.snapshots:
            by_year.setdefault(s.year, []).append(s)

        result: list[PeriodSnapshot] = []
        for y in sorted(by_year.keys()):
            year_snaps = by_year[y]

            # 1. Preferir 4D (auditado completo)
            snap_4d = next((s for s in year_snaps if s.quarter == "4D"),
                            None)
            if snap_4d is not None:
                result.append(snap_4d)
                continue

            # 2. Sin 4D → buscar el último quarter disponible del año Y
            #    (puede ser Q1, Q2, Q3 o Q4) y construir TTM
            quarters_avail = [s for s in year_snaps
                                if s.quarter in ("1", "2", "3", "4")]
            if not quarters_avail:
                continue
            latest_q = max(quarters_avail, key=lambda s: s.sort_key)

            # 3. Necesitamos prev_FY (Y-1) y prev_same_q (Y-1, mismo Q)
            prev_year_snaps = by_year.get(y - 1, [])
            prev_fy = next(
                (s for s in prev_year_snaps if s.quarter == "4D"), None)
            if prev_fy is None:
                # Si no hay 4D anterior, intentar Q4 anterior como FY proxy
                # (asumiendo que el parser reporta Q4 acumulado correctamente
                #  para años cerrados con sus 4 trimestres)
                prev_fy = next(
                    (s for s in prev_year_snaps if s.quarter == "4"), None)

            prev_same_q = next(
                (s for s in prev_year_snaps
                 if s.quarter == latest_q.quarter), None)

            if prev_fy is not None and prev_same_q is not None:
                # 4. Caso ideal: TTM bien calculado
                ttm = _build_ttm_snapshot(latest_q, prev_fy, prev_same_q)
                if ttm is not None:
                    result.append(ttm)
                    continue

            # 5. Sin data suficiente para TTM exacto:
            #    Si latest_q es Q4, lo usamos como aproximación FY
            #    (asumiendo Q4 = YTD acumulado, comportamiento histórico)
            if latest_q.quarter == "4":
                result.append(latest_q)
            # Si solo hay Q1/Q2/Q3 sin year-1 → skip (no se puede armar FY)

        return result

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


def _build_ttm_snapshot(latest_q: PeriodSnapshot,
                          prev_fy: PeriodSnapshot,
                          prev_same_q: PeriodSnapshot) -> Optional[PeriodSnapshot]:
    """Construye un PeriodSnapshot sintético con income/cashflow TTM.

    Fórmula por campo:
        TTM = latest_q (YTD del año actual)
            + prev_FY (12 meses año anterior)
            - prev_same_q (YTD año anterior, mismo trimestre)

    Esto garantiza una ventana de 12 meses exactos terminando en el
    period_end del último trimestre.

    Balance Sheet e Informative se quedan con los valores del último
    trimestre (son stocks, no flujos).

    Returns None si los dataclasses no son compatibles (no debería pasar).
    """
    from copy import deepcopy
    from dataclasses import fields, is_dataclass

    try:
        parsed_ttm = deepcopy(latest_q.parsed)
    except Exception:
        return None

    def _ttm_sum_dc(dc_lq, dc_fy, dc_pq, dc_target):
        """Aplica TTM a cada campo numérico de un dataclass."""
        if not (is_dataclass(dc_lq) and is_dataclass(dc_fy)
                and is_dataclass(dc_pq)):
            return
        for f in fields(dc_target):
            try:
                v_lq = getattr(dc_lq, f.name, None)
                v_fy = getattr(dc_fy, f.name, None)
                v_pq = getattr(dc_pq, f.name, None)
                if (isinstance(v_lq, (int, float))
                        and isinstance(v_fy, (int, float))
                        and isinstance(v_pq, (int, float))):
                    setattr(dc_target, f.name, v_lq + v_fy - v_pq)
            except Exception:
                continue

    # Income statement (acumulado) → TTM
    if hasattr(parsed_ttm, "income"):
        _ttm_sum_dc(latest_q.parsed.income,
                     prev_fy.parsed.income,
                     prev_same_q.parsed.income,
                     parsed_ttm.income)

    # Cash flow → TTM
    if hasattr(parsed_ttm, "cashflow"):
        _ttm_sum_dc(latest_q.parsed.cashflow,
                     prev_fy.parsed.cashflow,
                     prev_same_q.parsed.cashflow,
                     parsed_ttm.cashflow)

    # Informative items que son flujos 12M (revenue_12m, ebit_12m, da_12m, etc.)
    # Estos ya son TTM en el XBRL, así que se quedan tal cual.

    # DCF inputs si existe (puede ser util para Damodaran tab)
    if hasattr(parsed_ttm, "dcf") and parsed_ttm.dcf is not None:
        _ttm_sum_dc(latest_q.parsed.dcf,
                     prev_fy.parsed.dcf,
                     prev_same_q.parsed.dcf,
                     parsed_ttm.dcf)

    snap = PeriodSnapshot(
        period_tag=f"{latest_q.year}-TTM-Q{latest_q.quarter}",
        year=latest_q.year,
        quarter=f"TTM-Q{latest_q.quarter}",
        is_annual=True,           # tratar como anual para el filter de panels
        period_end=latest_q.period_end,
        filepath=latest_q.filepath,
        parsed=parsed_ttm,
    )
    return snap


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
