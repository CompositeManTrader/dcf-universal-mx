"""
Costo de capital (WACC) bottom-up estilo Damodaran, adaptado a Mexico.

Componentes:
  - Costo de equity via CAPM con beta bottom-up (industria) re-apalancada
  - Country Risk Premium Mexico aditivo al ERP maduro
  - Costo de deuda via synthetic rating (interest coverage -> spread)
  - WACC ponderado por target D/(D+E)

Defaults (revisar trimestralmente):
  - Risk-free MXN: 9.50% (M-BONO 10Y nominal, abr-26)
  - Mature market ERP (US): 5.0% (Damodaran Jan-26)
  - CRP Mexico: 1.80% (Damodaran Jan-26)
  - Marginal tax MX: 30%
"""
from __future__ import annotations

from dataclasses import dataclass

# --- Defaults Mexico (actualizar 1x/quarter) ---
RF_MX_DEFAULT = 0.0950          # M-BONO 10Y nominal
ERP_MATURE_DEFAULT = 0.0500      # ERP US maduro (Damodaran)
CRP_MX_DEFAULT = 0.0180          # Country Risk Premium Mexico
ERP_MX_DEFAULT = ERP_MATURE_DEFAULT + CRP_MX_DEFAULT  # 6.80%
MARGINAL_TAX_MX = 0.30
DEFAULT_REGION_PREMIUM_FOR_DEBT = 0.0180  # spread soberano MX vs UST


# --- Synthetic rating table de Damodaran (interest coverage -> rating + default spread) ---
# Para non-financial firms grandes; spreads sobre US Treasury en USD.
# Para deuda MXN, sumamos al spread el premium pais.
_RATING_TABLE = [
    # (coverage_min, rating, spread_us)
    (8.50, "Aaa/AAA", 0.0050),
    (6.50, "Aa2/AA",  0.0080),
    (5.50, "A1/A+",   0.0100),
    (4.25, "A2/A",    0.0120),
    (3.00, "A3/A-",   0.0150),
    (2.50, "Baa2/BBB",0.0200),
    (2.25, "Ba1/BB+", 0.0285),
    (2.00, "Ba2/BB",  0.0367),
    (1.75, "B1/B+",   0.0450),
    (1.50, "B2/B",    0.0567),
    (1.25, "B3/B-",   0.0814),
    (0.80, "Caa/CCC", 0.1117),
    (0.65, "Ca2/CC",  0.1417),
    (0.20, "C2/C",    0.1500),
    (-1e9, "D2/D",    0.1900),
]


def synthetic_rating(interest_coverage: float) -> tuple[str, float]:
    """Devuelve (rating, default_spread_USD). Para CRD MX sumar premium pais."""
    for cov_min, rating, spread in _RATING_TABLE:
        if interest_coverage >= cov_min:
            return rating, spread
    return "D2/D", 0.19


# --- CAPM ---
def cost_of_equity_capm(
    risk_free: float,
    levered_beta: float,
    erp: float,
) -> float:
    """Re = Rf + beta * ERP."""
    return risk_free + levered_beta * erp


def unlever_beta(
    levered_beta: float,
    debt_to_equity: float,
    tax_rate: float = MARGINAL_TAX_MX,
) -> float:
    """β_u = β_L / (1 + (1-t) * D/E)."""
    return levered_beta / (1.0 + (1.0 - tax_rate) * debt_to_equity)


def relever_beta(
    unlevered_beta: float,
    debt_to_equity: float,
    tax_rate: float = MARGINAL_TAX_MX,
) -> float:
    """β_L = β_u * (1 + (1-t) * D/E). Re-apalancado al D/E target."""
    return unlevered_beta * (1.0 + (1.0 - tax_rate) * debt_to_equity)


# --- WACC integrado ---
@dataclass
class WACCResult:
    risk_free: float
    erp: float
    unlevered_beta: float
    levered_beta: float
    cost_equity: float
    pretax_cost_debt: float
    aftertax_cost_debt: float
    rating: str
    default_spread: float
    weight_equity: float
    weight_debt: float
    wacc: float
    interest_coverage: float
    debt_to_equity: float


def compute_wacc(
    *,
    market_cap: float,                 # Equity en MDP (price * shares)
    total_debt: float,                 # Deuda financiera + leases en MDP
    interest_coverage: float,          # EBIT / Gastos financieros
    unlevered_beta: float,             # Beta industria bottom-up Damodaran
    risk_free: float = RF_MX_DEFAULT,
    erp: float = ERP_MX_DEFAULT,
    marginal_tax: float = MARGINAL_TAX_MX,
    country_debt_premium: float = DEFAULT_REGION_PREMIUM_FOR_DEBT,
) -> WACCResult:
    """Calcula WACC bottom-up al style Damodaran adaptado a MX."""
    if market_cap <= 0 and total_debt <= 0:
        raise ValueError("market_cap + total_debt deben ser > 0")

    d_to_e = total_debt / market_cap if market_cap > 0 else 99.0
    levered_beta = relever_beta(unlevered_beta, d_to_e, marginal_tax)
    cost_equity = cost_of_equity_capm(risk_free, levered_beta, erp)

    rating, spread_us = synthetic_rating(interest_coverage)
    # Pretax cost debt MXN = Rf MXN + spread crediticio + premium pais (default ya incluido?)
    # Damodaran: cost_debt = Rf + default_spread (sobre risk-free de la moneda)
    # Para evitar doble conteo del CRP, usamos solo el spread crediticio.
    pretax_cost_debt = risk_free + spread_us + country_debt_premium
    aftertax_cost_debt = pretax_cost_debt * (1.0 - marginal_tax)

    total_value = market_cap + total_debt
    we = market_cap / total_value
    wd = total_debt / total_value
    wacc = we * cost_equity + wd * aftertax_cost_debt

    return WACCResult(
        risk_free=risk_free,
        erp=erp,
        unlevered_beta=unlevered_beta,
        levered_beta=levered_beta,
        cost_equity=cost_equity,
        pretax_cost_debt=pretax_cost_debt,
        aftertax_cost_debt=aftertax_cost_debt,
        rating=rating,
        default_spread=spread_us,
        weight_equity=we,
        weight_debt=wd,
        wacc=wacc,
        interest_coverage=interest_coverage,
        debt_to_equity=d_to_e,
    )
