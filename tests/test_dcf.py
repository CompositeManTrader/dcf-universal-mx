"""Tests para dcf_fcff.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from dcf_mexico.valuation.dcf_fcff import (
    DCFAssumptions,
    CompanyBase,
    project_company,
)


@pytest.fixture
def base():
    """Empresa modelo: 50B revenue, 10B EBIT, 5B cash, 8B debt, 1B shares."""
    return CompanyBase(
        ticker="TEST",
        revenue=50_000,
        ebit=10_000,
        interest_expense=800,
        cash=5_000,
        financial_debt=8_000,
        minority_interest=200,
        non_operating_assets=500,
        shares_outstanding=1_000_000_000,
        effective_tax_rate=0.27,
    )


@pytest.fixture
def assumptions():
    return DCFAssumptions(
        revenue_growth_high=0.07,
        terminal_growth=0.03,
        target_op_margin=0.20,
        sales_to_capital=1.50,
        effective_tax_base=0.27,
        marginal_tax_terminal=0.30,
        risk_free=0.0921,
        erp=0.0610,
        unlevered_beta=0.80,
        terminal_wacc_override=0.085,
        market_price=50.0,
    )


def test_projection_length(base, assumptions):
    out = project_company(base, assumptions)
    assert len(out.years) == assumptions.forecast_years
    assert out.years == list(range(1, assumptions.forecast_years + 1))


def test_revenue_growth_correct(base, assumptions):
    """Year 1 revenue = base * (1 + growth_high)."""
    out = project_company(base, assumptions)
    expected_y1 = base.revenue * (1 + assumptions.revenue_growth_high)
    assert out.revenue[0] == pytest.approx(expected_y1, rel=1e-6)


def test_revenue_grows_then_fades(base, assumptions):
    """Revenue siempre creciente, growth Y6+ < growth Y1-5."""
    out = project_company(base, assumptions)
    for i in range(len(out.revenue) - 1):
        assert out.revenue[i + 1] > out.revenue[i]
    # Growth implicito Y10 vs Y2 debe ser <
    g_y2 = out.revenue[1] / out.revenue[0] - 1
    g_y10 = out.revenue[-1] / out.revenue[-2] - 1
    assert g_y10 < g_y2


def test_terminal_value_finite(base, assumptions):
    out = project_company(base, assumptions)
    assert out.terminal_value > 0
    assert out.pv_terminal > 0
    assert out.pv_terminal < out.terminal_value  # discount aplicado


def test_equity_bridge(base, assumptions):
    """Equity = EV - net_debt - minority + non_op_assets."""
    out = project_company(base, assumptions)
    expected = (
        out.enterprise_value
        - (base.financial_debt - base.cash)
        - base.minority_interest
        + base.non_operating_assets
    )
    assert out.equity_value == pytest.approx(expected, rel=1e-6)


def test_value_per_share_positive(base, assumptions):
    out = project_company(base, assumptions)
    assert out.value_per_share > 0


def test_upside_calculation(base, assumptions):
    """Upside = value/price - 1."""
    out = project_company(base, assumptions)
    expected = out.value_per_share / assumptions.market_price - 1
    assert out.upside_pct == pytest.approx(expected, rel=1e-6)


def test_higher_growth_higher_value(base, assumptions):
    """Mas growth -> mas value (todo lo demas igual)."""
    out_low = project_company(base, assumptions)
    a_high = DCFAssumptions(**{**assumptions.__dict__, "revenue_growth_high": 0.12})
    out_high = project_company(base, a_high)
    assert out_high.value_per_share > out_low.value_per_share


def test_higher_wacc_lower_value(base, assumptions):
    """Mas WACC (terminal override) -> menos value."""
    out_low = project_company(base, assumptions)
    a_high = DCFAssumptions(**{**assumptions.__dict__,
                                "terminal_wacc_override": 0.15,
                                "risk_free": 0.13})
    out_high = project_company(base, a_high)
    assert out_high.value_per_share < out_low.value_per_share


def test_terminal_growth_capped(base, assumptions):
    """Terminal growth >= terminal WACC -> sanity, modelo no debe explotar."""
    a_bad = DCFAssumptions(**{**assumptions.__dict__,
                                "terminal_growth": 0.10,
                                "terminal_wacc_override": 0.08})
    out = project_company(base, a_bad)
    # El modelo debe haber ajustado terminal_wacc para evitar division por cero
    assert out.terminal_wacc > a_bad.terminal_growth
    assert out.value_per_share > 0


def test_no_market_price_no_upside(base, assumptions):
    a = DCFAssumptions(**{**assumptions.__dict__, "market_price": None})
    out = project_company(base, a)
    assert out.upside_pct == 0.0
