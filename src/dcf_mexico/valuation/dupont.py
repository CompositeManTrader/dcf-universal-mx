"""
Analisis DuPont (3-step y 5-step) para descomponer ROE en componentes.

3-Step DuPont:
    ROE = Net Margin × Asset Turnover × Equity Multiplier
        = (NI / Sales) × (Sales / Assets) × (Assets / Equity)

5-Step DuPont (extended):
    ROE = Tax Burden × Interest Burden × EBIT Margin × Asset Turnover × Equity Multiplier
        = (NI / EBT) × (EBT / EBIT) × (EBIT / Sales) × (Sales / Assets) × (Assets / Equity)
"""

from dataclasses import dataclass, asdict
from typing import Optional

import pandas as pd


@dataclass
class DuPontResult:
    # 3-step
    net_margin: float                  # NI / Sales
    asset_turnover: float              # Sales / Total Assets
    equity_multiplier: float           # Total Assets / Equity (leverage)
    roe_3step: float                   # producto

    # 5-step (extended)
    tax_burden: float                  # NI / Pretax (efecto tax)
    interest_burden: float             # Pretax / EBIT (efecto carga financiera)
    ebit_margin: float                 # EBIT / Sales
    roe_5step: float                   # producto de los 5

    # Reference values
    roa: float                         # NI / Total Assets (Net Margin × Asset Turnover)
    roic: float                        # NOPAT / Invested Capital (no DuPont, pero util)
    actual_roe_check: float            # NI / Equity directo (para validar el producto cuadra)
    consistency_pp: float              # diferencia 5step - actual (debe ser ~0)

    def to_table(self) -> pd.DataFrame:
        rows = [
            ("--- 3-step DuPont ---", ""),
            ("Net Margin (NI/Sales)",            f"{self.net_margin:.2%}"),
            ("× Asset Turnover (Sales/Assets)",  f"{self.asset_turnover:.3f}x"),
            ("× Equity Multiplier (Assets/Eq)",  f"{self.equity_multiplier:.3f}x"),
            ("= ROE (3-step)",                    f"{self.roe_3step:.2%}"),
            ("",                                   ""),
            ("--- 5-step DuPont (extended) ---", ""),
            ("Tax Burden (NI/EBT)",              f"{self.tax_burden:.2%}"),
            ("× Interest Burden (EBT/EBIT)",     f"{self.interest_burden:.2%}"),
            ("× EBIT Margin (EBIT/Sales)",       f"{self.ebit_margin:.2%}"),
            ("× Asset Turnover (Sales/Assets)",  f"{self.asset_turnover:.3f}x"),
            ("× Equity Multiplier (Assets/Eq)",  f"{self.equity_multiplier:.3f}x"),
            ("= ROE (5-step)",                    f"{self.roe_5step:.2%}"),
            ("",                                   ""),
            ("--- Reference ---",                ""),
            ("ROE actual (NI/Equity directo)",   f"{self.actual_roe_check:.2%}"),
            ("Consistency (5step - actual)",     f"{self.consistency_pp:+.4f}pp"),
            ("ROA (NI/Assets)",                   f"{self.roa:.2%}"),
            ("ROIC (NOPAT/IC)",                   f"{self.roic:.2%}"),
        ]
        return pd.DataFrame(rows, columns=["Component", "Value"])

    def to_components(self) -> pd.DataFrame:
        """Return component values as numbers (for charting)."""
        return pd.DataFrame([
            {"Component": "Tax Burden",        "Value": self.tax_burden,        "Type": "Pct"},
            {"Component": "Interest Burden",   "Value": self.interest_burden,   "Type": "Pct"},
            {"Component": "EBIT Margin",       "Value": self.ebit_margin,       "Type": "Pct"},
            {"Component": "Asset Turnover",    "Value": self.asset_turnover,    "Type": "Multiple"},
            {"Component": "Equity Multiplier", "Value": self.equity_multiplier, "Type": "Multiple"},
            {"Component": "= ROE (5-step)",    "Value": self.roe_5step,         "Type": "Pct"},
        ])


def compute_dupont(
    revenue: float,
    ebit: float,
    pretax_income: float,
    net_income: float,
    total_assets: float,
    total_equity: float,
    nopat: Optional[float] = None,
    invested_capital: Optional[float] = None,
) -> DuPontResult:
    """Compute DuPont decomposition. Inputs en MDP (consistentes entre si)."""
    # Defensive defaults
    safe = lambda num, den: (num / den) if den and den != 0 else 0.0

    # 3-step
    net_margin = safe(net_income, revenue)
    asset_turnover = safe(revenue, total_assets)
    equity_multiplier = safe(total_assets, total_equity)
    roe_3step = net_margin * asset_turnover * equity_multiplier

    # 5-step
    tax_burden = safe(net_income, pretax_income)
    interest_burden = safe(pretax_income, ebit)
    ebit_margin = safe(ebit, revenue)
    roe_5step = tax_burden * interest_burden * ebit_margin * asset_turnover * equity_multiplier

    # Reference
    roa = safe(net_income, total_assets)
    if nopat is None:
        nopat = ebit * 0.70  # asumir tax 30% si no se da
    if invested_capital is None or invested_capital <= 0:
        invested_capital = total_equity  # fallback si no hay IC
    roic = safe(nopat, invested_capital)
    actual_roe = safe(net_income, total_equity)
    consistency = (roe_5step - actual_roe)

    return DuPontResult(
        net_margin=net_margin,
        asset_turnover=asset_turnover,
        equity_multiplier=equity_multiplier,
        roe_3step=roe_3step,
        tax_burden=tax_burden,
        interest_burden=interest_burden,
        ebit_margin=ebit_margin,
        roe_5step=roe_5step,
        roa=roa,
        roic=roic,
        actual_roe_check=actual_roe,
        consistency_pp=consistency,
    )


def dupont_from_parser(res, currency_multiplier: float = 1.0) -> DuPontResult:
    """Construye DuPont desde un ParseResult del XBRL parser."""
    m = currency_multiplier
    bs = res.balance
    is_ = res.income
    return compute_dupont(
        revenue=is_.revenue * m,
        ebit=is_.ebit * m,
        pretax_income=is_.pretax_income * m,
        net_income=(is_.net_income_controlling or is_.net_income) * m,
        total_assets=bs.total_assets * m,
        total_equity=bs.equity_controlling * m,
        nopat=is_.ebit * (1 - is_.effective_tax_rate) * m,
        invested_capital=bs.invested_capital * m,
    )
