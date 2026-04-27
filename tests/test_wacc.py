"""Tests para wacc.py."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from dcf_mexico.valuation.wacc import (
    cost_of_equity_capm,
    relever_beta,
    unlever_beta,
    synthetic_rating,
    compute_wacc,
)


# -------------------------------------------------------------------
def test_capm_basic():
    """Re = Rf + β × ERP."""
    assert cost_of_equity_capm(0.05, 1.0, 0.06) == pytest.approx(0.11)
    assert cost_of_equity_capm(0.10, 1.5, 0.05) == pytest.approx(0.175)
    assert cost_of_equity_capm(0.0, 0.0, 0.10) == pytest.approx(0.0)


def test_unlever_relever_inverse():
    """Unlever then relever should round-trip."""
    beta_l = 1.20
    d_e = 0.50
    tax = 0.30
    beta_u = unlever_beta(beta_l, d_e, tax)
    relevered = relever_beta(beta_u, d_e, tax)
    assert relevered == pytest.approx(beta_l, rel=1e-9)


def test_relever_zero_debt():
    """Sin deuda, beta levered = beta unlevered."""
    assert relever_beta(0.80, 0.0) == pytest.approx(0.80)


def test_relever_increases_beta():
    """Mas apalancamiento -> beta mayor."""
    bu = 0.80
    assert relever_beta(bu, 0.0) < relever_beta(bu, 0.5) < relever_beta(bu, 1.0)


# -------------------------------------------------------------------
def test_synthetic_rating_buckets():
    """Coverage muy alta -> AAA. Negativa -> D."""
    assert synthetic_rating(15.0)[0] == "Aaa/AAA"
    assert synthetic_rating(7.0)[0] == "Aa2/AA"
    assert synthetic_rating(3.0)[0] == "A3/A-"
    assert synthetic_rating(2.6)[0] == "Baa2/BBB"
    assert synthetic_rating(1.0)[0] == "Caa/CCC"
    assert synthetic_rating(0.5)[0] == "C2/C"
    assert synthetic_rating(-5.0)[0] == "D2/D"


def test_synthetic_rating_spread_monotonic():
    """A mayor coverage -> menor spread."""
    spreads = [synthetic_rating(c)[1] for c in [10, 5, 3, 2, 1, 0.5]]
    for i in range(len(spreads) - 1):
        assert spreads[i] <= spreads[i + 1]


# -------------------------------------------------------------------
def test_compute_wacc_typical_case():
    """WACC realista de empresa MX investment grade."""
    res = compute_wacc(
        market_cap=50_000,
        total_debt=10_000,
        interest_coverage=8.0,
        unlevered_beta=0.80,
        risk_free=0.0950,
        erp=0.0680,
        marginal_tax=0.30,
    )
    assert 0.05 <= res.wacc <= 0.20
    assert res.weight_equity + res.weight_debt == pytest.approx(1.0)
    # Cost of equity > WACC > after-tax cost of debt
    assert res.cost_equity > res.wacc > res.aftertax_cost_debt
    # Beta levered > beta unlevered (con deuda)
    assert res.levered_beta > 0.80


def test_compute_wacc_zero_debt():
    """Sin deuda -> WACC = cost of equity."""
    res = compute_wacc(
        market_cap=100_000,
        total_debt=0.0,
        interest_coverage=99.0,
        unlevered_beta=1.0,
        risk_free=0.05,
        erp=0.06,
    )
    assert res.weight_debt == pytest.approx(0.0)
    assert res.wacc == pytest.approx(res.cost_equity)


def test_compute_wacc_invalid():
    """market_cap + debt = 0 debe lanzar."""
    with pytest.raises(ValueError):
        compute_wacc(market_cap=0, total_debt=0, interest_coverage=1.0,
                      unlevered_beta=1.0)
