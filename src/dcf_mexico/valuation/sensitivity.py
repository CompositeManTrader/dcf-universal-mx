"""Analisis de sensibilidad: tornado y matriz 2D sobre el value/share."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace, fields
from typing import Iterable

import pandas as pd

from .dcf_fcff import DCFAssumptions, project_company, CompanyBase


def _value_with_override(base: CompanyBase, a: DCFAssumptions, **overrides) -> float:
    """Re-corre DCF con overrides en assumptions y devuelve value_per_share."""
    new_a = replace(a, **overrides)
    out = project_company(base, new_a)
    return out.value_per_share


def tornado(
    base: CompanyBase,
    assumptions: DCFAssumptions,
    drivers: dict[str, tuple[float, float]] | None = None,
) -> pd.DataFrame:
    """
    Tornado de sensibilidad: para cada driver, evalua valor con bajo/alto.
    `drivers` es dict {nombre_field: (low, high)}.
    Si no se pasa, usa defaults razonables alrededor del caso base.
    """
    if drivers is None:
        drivers = {
            "revenue_growth_high":   (assumptions.revenue_growth_high - 0.03, assumptions.revenue_growth_high + 0.03),
            "target_op_margin":      (assumptions.target_op_margin - 0.03, assumptions.target_op_margin + 0.03),
            "sales_to_capital":      (max(0.5, assumptions.sales_to_capital - 0.5), assumptions.sales_to_capital + 0.5),
            "terminal_growth":       (max(0.005, assumptions.terminal_growth - 0.015), assumptions.terminal_growth + 0.015),
            "unlevered_beta":        (max(0.3, assumptions.unlevered_beta - 0.3), assumptions.unlevered_beta + 0.3),
            "risk_free":             (max(0.03, assumptions.risk_free - 0.02), assumptions.risk_free + 0.02),
            "erp":                   (max(0.04, assumptions.erp - 0.02), assumptions.erp + 0.02),
        }

    base_value = _value_with_override(base, assumptions)

    rows = []
    for driver, (low, high) in drivers.items():
        v_low = _value_with_override(base, assumptions, **{driver: low})
        v_high = _value_with_override(base, assumptions, **{driver: high})
        rows.append({
            "Driver": driver,
            "Low input": round(low, 4),
            "High input": round(high, 4),
            "Value @ Low (MXN)": round(v_low, 2),
            "Value @ High (MXN)": round(v_high, 2),
            "Δ Value (MXN)": round(v_high - v_low, 2),
            "Δ Value %": round((v_high - v_low) / base_value * 100, 2) if base_value else 0,
        })
    df = pd.DataFrame(rows)
    df = df.reindex(df["Δ Value (MXN)"].abs().sort_values(ascending=False).index)
    return df


def matrix(
    base: CompanyBase,
    assumptions: DCFAssumptions,
    x_driver: str,
    y_driver: str,
    x_values: Iterable[float],
    y_values: Iterable[float],
) -> pd.DataFrame:
    """Matriz 2D: filas = y_driver, columnas = x_driver. Celdas = value/share."""
    x_values = list(x_values)
    y_values = list(y_values)
    grid = []
    for yv in y_values:
        row = []
        for xv in x_values:
            v = _value_with_override(base, assumptions, **{x_driver: xv, y_driver: yv})
            row.append(round(v, 2))
        grid.append(row)
    return pd.DataFrame(
        grid,
        index=[f"{y_driver}={round(v, 4)}" for v in y_values],
        columns=[f"{x_driver}={round(v, 4)}" for v in x_values],
    )
