"""Proyección de Estados Financieros driver-based, integrada con DCF."""
from .engine import (
    BaseFinancials,
    ProjectionDrivers,
    ProjectedYear,
    ProjectionResult,
    project_financials,
)
from .backtest import BacktestResult, run_backtest

__all__ = [
    "BaseFinancials", "ProjectionDrivers", "ProjectedYear", "ProjectionResult",
    "project_financials", "BacktestResult", "run_backtest",
]
