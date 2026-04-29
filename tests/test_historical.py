"""Tests para historical.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest
import pandas as pd

from dcf_mexico.historical import (
    load_historical, build_historical_bloomberg,
    build_metric_timeseries, compute_growth_stats,
)
from dcf_mexico.config import find_all_xbrl, parse_period_tag, is_annual_period


def test_find_all_xbrl_returns_list():
    """find_all_xbrl debe devolver list (puede estar vacio)."""
    files = find_all_xbrl("CUERVO")
    assert isinstance(files, list)


def test_parse_period_tag_annual():
    """4D = anual."""
    fp = Path("ifrsxbrl_CUERVO_2025-4D.xls")
    year, q = parse_period_tag(fp)
    assert year == 2025
    assert q == "4D"
    assert is_annual_period(q) is True


def test_parse_period_tag_quarterly():
    fp = Path("ifrsxbrl_AMX_2026-1.xls")
    year, q = parse_period_tag(fp)
    assert year == 2026
    assert q == "1"
    assert is_annual_period(q) is False


def test_parse_period_tag_invalid():
    fp = Path("random_file.xls")
    year, q = parse_period_tag(fp)
    assert year == 0


def test_load_historical_cuervo():
    """CUERVO debe tener al menos 1 periodo en data/raw_xbrl."""
    hs = load_historical("CUERVO")
    assert hs.ticker == "CUERVO"
    assert hs.n_periods >= 1
    assert hs.latest is not None


def test_load_historical_unknown_ticker():
    hs = load_historical("EMISORA_INEXISTENTE_XYZ")
    assert hs.n_periods == 0
    assert hs.latest is None


def test_build_historical_bloomberg_cuervo():
    hs = load_historical("CUERVO")
    df = build_historical_bloomberg(hs, annual_only=False)
    # Debe tener al menos las metricas core
    expected_metrics = {"Revenue", "EBIT", "EBITDA", "Net Income",
                        "Op Margin", "ROE", "Total Assets"}
    assert expected_metrics.issubset(set(df.index))


def test_build_metric_timeseries_revenue():
    hs = load_historical("CUERVO")
    ts = build_metric_timeseries(hs, "Revenue", annual_only=False)
    assert "label" in ts.columns
    assert "value" in ts.columns
    assert (ts["value"] > 0).any()


def test_compute_growth_stats_basic():
    """CAGR a 3 anios, 100 -> 200 = ~26%."""
    s = compute_growth_stats([100, 130, 170, 200], years=3)
    assert s["n"] == 4
    assert s["peak"] == 200
    assert s["trough"] == 100
    assert 0.20 < s["cagr"] < 0.30


def test_compute_growth_stats_single_value():
    s = compute_growth_stats([100])
    assert s["n"] == 1
    assert s["cagr"] == 0


def test_compute_growth_stats_empty():
    s = compute_growth_stats([])
    assert s["n"] == 0
