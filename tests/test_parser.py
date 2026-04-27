"""Tests con CUERVO como fixture (Q4 2025)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pytest

from dcf_mexico.parse import parse_xbrl


FIXTURE = ROOT / "tests" / "fixtures" / "ifrsxbrl_CUERVO_2025-4.xls"


@pytest.fixture(scope="module")
def cuervo():
    assert FIXTURE.exists(), f"Falta fixture: {FIXTURE}"
    return parse_xbrl(FIXTURE)


def test_info(cuervo):
    assert cuervo.info.ticker == "CUERVO"
    assert cuervo.info.period_end.startswith("2025")
    assert cuervo.info.is_financial is False


def test_balance_cierra(cuervo):
    """A = L + E con tolerancia 0.5%."""
    bs = cuervo.balance
    rhs = bs.total_liabilities + bs.total_equity
    assert bs.total_assets > 0
    assert abs(bs.total_assets - rhs) / bs.total_assets < 0.005


def test_total_activos_no_es_circulantes(cuervo):
    """Bug v2: 'Total de activos' no debe coincidir con 'Total de activos circulantes'."""
    bs = cuervo.balance
    assert bs.total_assets > bs.total_current_assets


def test_revenue_positivo(cuervo):
    assert cuervo.income.revenue > 0
    assert cuervo.income.operating_margin > 0  # CUERVO siempre rentable


def test_dcf_inputs_completos(cuervo):
    d = cuervo.dcf
    assert d.ticker == "CUERVO"
    assert d.revenue > 0
    assert d.shares_outstanding > 0
    assert 0.0 <= d.effective_tax_rate <= 0.50


def test_acciones_cuervo_aprox(cuervo):
    # CUERVO tiene ~3,653 millones de acciones serie unica
    shares_mn = cuervo.informative.shares_outstanding / 1_000_000
    assert 3_500 < shares_mn < 3_800, f"Acciones (mn) fuera de rango esperado: {shares_mn}"


def test_validacion_ok(cuervo):
    # No debe haber errores criticos (puede haber WARN)
    errores = [i for i in cuervo.validation.issues if i.startswith("[ERROR]")]
    assert errores == [], f"Errores de validacion: {errores}"
