"""Tests para financial.py (Justified P/B + Excess Returns)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from dcf_mexico.valuation.financial import (
    FinancialAssumptions,
    FinancialBase,
    value_financial,
    justified_pb,
)


def test_justified_pb_basic():
    """P/B = (ROE - g) / (Re - g). ROE > Re -> P/B > 1."""
    pb = justified_pb(roe=0.15, growth=0.03, cost_of_equity=0.10)
    assert pb == pytest.approx((0.15 - 0.03) / (0.10 - 0.03))
    assert pb > 1.0


def test_justified_pb_roe_below_re():
    """Si ROE < Re -> P/B < 1 (la empresa destruye valor)."""
    pb = justified_pb(roe=0.05, growth=0.03, cost_of_equity=0.10)
    assert pb < 1.0


def test_justified_pb_zero_when_re_le_g():
    """Si Re <= g devuelve 0 (proteccion division)."""
    assert justified_pb(roe=0.10, growth=0.10, cost_of_equity=0.05) == 0.0


def test_value_financial_basic():
    """Banco hipotetico con ROE 15%, BV 100M, 1M shares."""
    base = FinancialBase(
        ticker="BANCO",
        book_value_equity=100_000,    # 100B MDP
        net_income=15_000,             # ROE = 15%
        shares_outstanding=1_000_000_000,
        dividends_paid=6_000,          # payout 40%
    )
    a = FinancialAssumptions(
        roe=0.15,
        growth_high=0.07,
        growth_terminal=0.03,
        payout_ratio=0.40,
        risk_free=0.0921,
        erp=0.0610,
        levered_beta=1.10,
        market_price=100.0,
    )
    out = value_financial(base, a)
    assert out.cost_of_equity == pytest.approx(0.0921 + 1.10 * 0.0610)
    assert out.justified_pb > 0
    assert out.pb_value_per_share > 0
    assert out.er_value_per_share > 0


def test_value_financial_high_roe_higher_value():
    """Mas ROE -> mas value (sostenido)."""
    base = FinancialBase(
        ticker="X", book_value_equity=100_000, net_income=10_000,
        shares_outstanding=1_000_000_000, dividends_paid=4_000,
    )
    a_low = FinancialAssumptions(roe=0.10, market_price=50.0)
    a_high = FinancialAssumptions(roe=0.20, market_price=50.0)
    out_low = value_financial(base, a_low)
    out_high = value_financial(base, a_high)
    assert out_high.er_value_per_share > out_low.er_value_per_share
    assert out_high.justified_pb > out_low.justified_pb


def test_financial_base_metrics():
    base = FinancialBase(
        ticker="X", book_value_equity=10_000, net_income=1_500,
        shares_outstanding=1_000_000_000, dividends_paid=600,
    )
    assert base.roe == pytest.approx(0.15)
    assert base.implied_payout == pytest.approx(0.40)
    assert base.book_value_per_share == pytest.approx(10.0)
    assert base.eps == pytest.approx(1.5)
