"""
Construye paneles historicos a partir de HistoricalSeries:
  - Bloomberg-style multi-period sheets (filas = conceptos, cols = periodos)
  - Time series por metrica clave
  - Stats de crecimiento (CAGR, peak/trough, vol)
"""
from __future__ import annotations

from typing import Optional

import pandas as pd
import numpy as np


def _safe_div(num, den):
    return num / den if den and den != 0 else 0.0


def _snapshot_metrics(snap, fx_mult: float = 1.0) -> dict:
    """Extrae las metricas clave de un snapshot, en MDP.

    fx_mult: 19.5 si XBRL reporta en USD, else 1.0.
    """
    res = snap.parsed
    bs = res.balance
    is_ = res.income
    cf = res.cashflow
    inf = res.informative

    # raw_pesos / 1e6 = MDP. Si reporta USD, multiplicar por fx primero.
    def to_mdp(v):
        return (v * fx_mult) / 1_000_000

    revenue = to_mdp(is_.revenue) if not inf.revenue_12m else to_mdp(inf.revenue_12m)
    ebit = to_mdp(is_.ebit) if not inf.ebit_12m else to_mdp(inf.ebit_12m)
    net_income = to_mdp(is_.net_income_controlling or is_.net_income)
    da = to_mdp(inf.da_12m) if inf.da_12m else 0.0

    return {
        "Revenue":              revenue,
        "EBIT":                 ebit,
        "EBITDA":               ebit + da,
        "Net Income":           net_income,
        "D&A":                  da,
        "Op Margin":            _safe_div(ebit, revenue),
        "EBITDA Margin":        _safe_div(ebit + da, revenue),
        "Net Margin":           _safe_div(net_income, revenue),
        "Tax Rate":             is_.effective_tax_rate,
        # Balance
        "Cash":                 to_mdp(bs.cash),
        "Total Debt":           to_mdp(bs.total_debt_with_leases),
        "Net Debt":             to_mdp(bs.net_debt),
        "Total Assets":         to_mdp(bs.total_assets),
        "Equity (controll.)":   to_mdp(bs.equity_controlling),
        "Invested Capital":     to_mdp(bs.invested_capital),
        # CF
        "CFO":                  to_mdp(cf.cfo),
        "Capex (gross)":        to_mdp(cf.capex_gross),
        "Capex (net)":          to_mdp(cf.capex_net),
        "FCFF (simple)":        to_mdp(cf.cfo - cf.capex_net),
        # Per-share / ratios
        "ROE":                  _safe_div(net_income, to_mdp(bs.equity_controlling)),
        "ROA":                  _safe_div(net_income, to_mdp(bs.total_assets)),
        "Net Debt / EBITDA":    _safe_div(to_mdp(bs.net_debt), ebit + da),
        "Debt / Equity":        _safe_div(to_mdp(bs.total_debt_with_leases), to_mdp(bs.equity_controlling)),
        "Shares (mn)":          inf.shares_outstanding / 1_000_000,
    }


def _detect_fx_mult(snap, fx_rate_usdmxn: float = 19.5) -> float:
    """Devuelve fx_mult correcto segun la moneda reportada en el XBRL."""
    currency = (snap.parsed.info.currency or "MXN").upper().strip()
    return fx_rate_usdmxn if currency == "USD" else 1.0


def build_historical_bloomberg(
    series,
    fx_rate_usdmxn: float = 19.5,
    annual_only: bool = True,
    max_periods: Optional[int] = None,
) -> pd.DataFrame:
    """Tabla Bloomberg-style: filas = metricas, cols = periodos.

    Si annual_only=True usa solo periodos 4D (anuales auditados).
    max_periods: limita a los N mas recientes (None = todos).
    Auto-detecta moneda (USD vs MXN) por snapshot.
    """
    snaps = series.annual if annual_only else series.snapshots
    if max_periods:
        snaps = snaps[-max_periods:]
    if not snaps:
        return pd.DataFrame()

    cols = {}
    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)
        cols[s.label] = _snapshot_metrics(s, fx_mult=fx)
    df = pd.DataFrame(cols)
    return df


def build_metric_timeseries(
    series,
    metric: str,
    fx_rate_usdmxn: float = 19.5,
    annual_only: bool = True,
) -> pd.DataFrame:
    """Devuelve un DataFrame con cols ['period_end', 'label', 'value'] para
    plotear time series de una metrica especifica.
    """
    snaps = series.annual if annual_only else series.snapshots
    rows = []
    for s in snaps:
        fx = _detect_fx_mult(s, fx_rate_usdmxn)
        m = _snapshot_metrics(s, fx_mult=fx)
        rows.append({
            "period_end": s.period_end,
            "year":       s.year,
            "label":      s.label,
            "value":      m.get(metric, 0.0),
        })
    return pd.DataFrame(rows)


def compute_growth_stats(values: list, years: int = None) -> dict:
    """CAGR, mean, peak, trough, volatility."""
    vals = [v for v in values if v is not None and not np.isnan(v)]
    if len(vals) < 2:
        return {"cagr": 0, "mean": vals[0] if vals else 0, "peak": vals[0] if vals else 0,
                "trough": vals[0] if vals else 0, "vol": 0, "n": len(vals)}
    n = years if years is not None else (len(vals) - 1)
    first, last = vals[0], vals[-1]
    cagr = (last / first) ** (1 / n) - 1 if first > 0 and n > 0 else 0
    return {
        "cagr":   cagr,
        "mean":   float(np.mean(vals)),
        "peak":   float(np.max(vals)),
        "trough": float(np.min(vals)),
        "vol":    float(np.std(vals) / np.mean(vals)) if np.mean(vals) != 0 else 0,
        "n":      len(vals),
    }
