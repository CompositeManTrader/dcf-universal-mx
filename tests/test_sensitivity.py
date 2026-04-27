"""Tests para sensitivity.py (tornado y matriz)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from dcf_mexico.valuation.dcf_fcff import DCFAssumptions, CompanyBase
from dcf_mexico.valuation.sensitivity import tornado, matrix


@pytest.fixture
def setup():
    base = CompanyBase(
        ticker="TEST", revenue=50_000, ebit=10_000, interest_expense=800,
        cash=5_000, financial_debt=8_000, minority_interest=0,
        non_operating_assets=0, shares_outstanding=1_000_000_000,
        effective_tax_rate=0.27,
    )
    a = DCFAssumptions(
        revenue_growth_high=0.07, terminal_growth=0.03,
        target_op_margin=0.20, sales_to_capital=1.50,
        risk_free=0.0921, erp=0.0610, unlevered_beta=0.80,
        terminal_wacc_override=0.085, market_price=50.0,
    )
    return base, a


def test_tornado_returns_df(setup):
    base, a = setup
    df = tornado(base, a)
    expected_cols = {"Driver", "Low input", "High input",
                     "Value @ Low (MXN)", "Value @ High (MXN)",
                     "Δ Value (MXN)", "Δ Value %"}
    assert expected_cols.issubset(set(df.columns))
    assert len(df) >= 5  # al menos 5 drivers default


def test_tornado_sorted_by_impact(setup):
    """Drivers ordenados por |ΔValue| descendente."""
    base, a = setup
    df = tornado(base, a)
    abs_deltas = df["Δ Value (MXN)"].abs().tolist()
    assert abs_deltas == sorted(abs_deltas, reverse=True)


def test_matrix_dimensions(setup):
    base, a = setup
    xs = [0.03, 0.05, 0.07]
    ys = [0.15, 0.20, 0.25]
    mat = matrix(base, a,
                  x_driver="revenue_growth_high",
                  y_driver="target_op_margin",
                  x_values=xs, y_values=ys)
    assert mat.shape == (len(ys), len(xs))


def test_matrix_monotonic_growth(setup):
    """A mayor growth, mayor value (en cada fila de margin)."""
    base, a = setup
    xs = [0.02, 0.05, 0.08]
    ys = [0.20]
    mat = matrix(base, a, "revenue_growth_high", "target_op_margin", xs, ys)
    row = mat.iloc[0].tolist()
    assert row[0] < row[1] < row[2]


def test_matrix_monotonic_margin(setup):
    """A mayor margin, mayor value (en cada columna de growth)."""
    base, a = setup
    xs = [0.05]
    ys = [0.15, 0.20, 0.25]
    mat = matrix(base, a, "revenue_growth_high", "target_op_margin", xs, ys)
    col = mat.iloc[:, 0].tolist()
    assert col[0] < col[1] < col[2]
