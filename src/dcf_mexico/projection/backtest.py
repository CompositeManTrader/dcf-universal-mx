"""
Back-test de la metodología de proyección.

Idea: tomar un año-ancla del pasado (ej: 2022) y simular qué habría
predicho el modelo. Comparar contra los valores REALES observados.

Métricas:
- MAE (Mean Absolute Error) absoluto
- MAPE (Mean Absolute Percentage Error)
- Direction accuracy (¿predijo subida/bajada correctamente?)
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import pandas as pd

from .engine import BaseFinancials, ProjectionDrivers, project_financials


@dataclass
class BacktestResult:
    anchor_year: int
    drivers_used: ProjectionDrivers
    rows: List[dict]                # cada fila: año, metric, predicted, actual, error
    mape_revenue: float
    mape_ebit: float
    mape_ni: float
    direction_accuracy_revenue: float

    def to_table(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)

    def summary(self) -> str:
        return (
            f"Back-test desde {self.anchor_year}:\n"
            f"  Revenue MAPE:  {self.mape_revenue*100:>6.2f}%\n"
            f"  EBIT MAPE:     {self.mape_ebit*100:>6.2f}%\n"
            f"  Net Inc MAPE:  {self.mape_ni*100:>6.2f}%\n"
            f"  Direction acc: {self.direction_accuracy_revenue*100:>6.0f}% (revenue YoY sign)"
        )


def run_backtest(series, anchor_year: int, fx_mult: float = 1.0,
                  smoothing: str = "median") -> Optional[BacktestResult]:
    """Tomar anchor_year, simular proyección hacia adelante usando solo
    información disponible HASTA ese año, y comparar vs lo real observado.

    Args:
        series: HistoricalSeries
        anchor_year: año desde el cual proyectar (debe haber años posteriores)
        smoothing: metodología drivers ('median', 'avg', 'last')
    """
    snaps = series.annual
    anchor_snaps = [s for s in snaps if s.year <= anchor_year]
    future_snaps = [s for s in snaps if s.year > anchor_year]

    if len(anchor_snaps) < 2 or not future_snaps:
        return None

    # Construir series histórica truncada al anchor
    class _PartialSeries:
        def __init__(self, snaps_):
            self.annual = snaps_
            self.snapshots = snaps_
            self.ticker = series.ticker
    partial = _PartialSeries(anchor_snaps)

    # Drivers calculados solo con info ≤ anchor_year
    horizon = len(future_snaps)
    drivers = ProjectionDrivers.from_history(partial, horizon=horizon,
                                                fx_mult=fx_mult, smoothing=smoothing)

    # Base = anchor year
    base = BaseFinancials.from_snapshot(anchor_snaps[-1], fx_mult=fx_mult)

    # Proyectar
    projected = project_financials(base, drivers, horizon=horizon)

    # Comparar vs real
    rows = []
    rev_pcts, ebit_pcts, ni_pcts = [], [], []
    correct_direction = 0
    total_direction = 0

    prev_actual_rev = base.revenue

    for i, future_snap in enumerate(future_snaps):
        actual_rev = (future_snap.parsed.income.revenue or 0) * fx_mult / 1_000_000
        actual_ebit = (future_snap.parsed.income.ebit or 0) * fx_mult / 1_000_000
        actual_ni = (future_snap.parsed.income.net_income or 0) * fx_mult / 1_000_000

        proj = projected.years[i]

        rev_err = (proj.revenue - actual_rev) / actual_rev if actual_rev else 0
        ebit_err = (proj.ebit - actual_ebit) / actual_ebit if actual_ebit else 0
        ni_err = (proj.net_income - actual_ni) / actual_ni if actual_ni else 0

        rev_pcts.append(abs(rev_err))
        ebit_pcts.append(abs(ebit_err))
        ni_pcts.append(abs(ni_err))

        # Direction: predijo el sentido (sube/baja vs prior actual)?
        actual_dir = 1 if actual_rev > prev_actual_rev else -1
        proj_dir = 1 if proj.revenue > prev_actual_rev else -1
        if actual_dir == proj_dir:
            correct_direction += 1
        total_direction += 1

        rows.append({
            "Year": future_snap.year,
            "Revenue Real":      round(actual_rev, 1),
            "Revenue Proyect":   round(proj.revenue, 1),
            "Rev Error %":       f"{rev_err*100:+.1f}%",
            "EBIT Real":         round(actual_ebit, 1),
            "EBIT Proyect":      round(proj.ebit, 1),
            "EBIT Error %":      f"{ebit_err*100:+.1f}%",
            "NI Real":           round(actual_ni, 1),
            "NI Proyect":        round(proj.net_income, 1),
            "NI Error %":        f"{ni_err*100:+.1f}%",
        })

        prev_actual_rev = actual_rev

    return BacktestResult(
        anchor_year=anchor_year,
        drivers_used=drivers,
        rows=rows,
        mape_revenue=sum(rev_pcts) / len(rev_pcts) if rev_pcts else 0,
        mape_ebit=sum(ebit_pcts) / len(ebit_pcts) if ebit_pcts else 0,
        mape_ni=sum(ni_pcts) / len(ni_pcts) if ni_pcts else 0,
        direction_accuracy_revenue=correct_direction / total_direction if total_direction else 0,
    )
