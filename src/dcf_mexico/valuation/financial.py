"""
Valuacion para EMISORAS FINANCIERAS (bancos, aseguradoras, financieras).

Para estas emisoras NO aplica el FCFF DCF clasico porque:
  - Sus pasivos son su materia prima (depositos = funding, no deuda operativa)
  - El concepto de "deuda neta" no aplica (no hay distincion clara debt/operating)
  - El working capital y CapEx no son drivers relevantes
  - Damodaran recomienda DDM o Excess Returns Model (ERM)

Implementamos 2 metodos:

  1. JUSTIFIED P/B (Gordon-style):
        P/B = (ROE - g) / (Re - g)
        Value/share = P/B_justified * BV/share
     Ventaja: solo requiere ROE, growth, cost of equity. Datos siempre disponibles.

  2. EXCESS RETURNS MODEL (mas riguroso):
        Value = BV_0 + sum_t [(ROE_t - Re) * BV_{t-1}] / (1+Re)^t + Terminal
     Donde el terminal usa Gordon sobre los excess returns en estado estable.
"""

from dataclasses import dataclass, field
from typing import Optional

from .wacc import cost_of_equity_capm, RF_MX_DEFAULT, ERP_MX_DEFAULT


# -------------------------------------------------------------------
@dataclass
class FinancialAssumptions:
    """Drivers para valuacion de financieras."""
    roe: float                            # ROE current o normalizado
    growth_high: float = 0.05             # crecimiento BV equity Y1-Y5
    growth_terminal: float = 0.03         # crecimiento perpetuidad (cap a inflacion)
    payout_ratio: float = 0.40            # dividendo / utilidad neta
    forecast_years: int = 10
    high_growth_years: int = 5
    # Cost of equity inputs
    risk_free: float = RF_MX_DEFAULT
    erp: float = ERP_MX_DEFAULT
    levered_beta: float = 1.10            # bancos tipicamente 1.0-1.3
    market_price: Optional[float] = None


@dataclass
class FinancialBase:
    ticker: str
    book_value_equity: float              # MDP, BV equity controladora
    net_income: float                     # MDP, NI 12M atribuible a controladora
    shares_outstanding: float             # absoluto
    dividends_paid: float = 0.0           # MDP, 12M (positivo)

    @property
    def book_value_per_share(self) -> float:
        return self.book_value_equity * 1e6 / self.shares_outstanding if self.shares_outstanding > 0 else 0.0

    @property
    def eps(self) -> float:
        return self.net_income * 1e6 / self.shares_outstanding if self.shares_outstanding > 0 else 0.0

    @property
    def roe(self) -> float:
        return self.net_income / self.book_value_equity if self.book_value_equity else 0.0

    @property
    def implied_payout(self) -> float:
        return self.dividends_paid / self.net_income if self.net_income > 0 else 0.0

    @classmethod
    def from_parser_result(cls, res):
        return cls(
            ticker=res.info.ticker,
            book_value_equity=res.balance.equity_controlling / 1e6,
            net_income=res.income.net_income_controlling / 1e6 if res.income.net_income_controlling else res.income.net_income / 1e6,
            shares_outstanding=res.informative.shares_outstanding,
            dividends_paid=abs(res.cashflow.dividends_paid) / 1e6,
        )


@dataclass
class FinancialOutput:
    base: FinancialBase
    assumptions: FinancialAssumptions
    cost_of_equity: float
    # Justified P/B
    justified_pb: float
    pb_value_per_share: float
    pb_upside: float
    # Excess Returns
    sum_pv_excess: float
    pv_terminal: float
    er_total_value: float
    er_value_per_share: float
    er_upside: float


# -------------------------------------------------------------------
def justified_pb(roe: float, growth: float, cost_of_equity: float) -> float:
    """Gordon-style justified P/B = (ROE - g) / (Re - g)."""
    if cost_of_equity <= growth + 0.001:
        return 0.0
    return (roe - growth) / (cost_of_equity - growth)


def value_financial(
    base: FinancialBase,
    assumptions: FinancialAssumptions,
) -> FinancialOutput:
    """Calcula ambos metodos y devuelve FinancialOutput."""
    a = assumptions
    re = cost_of_equity_capm(a.risk_free, a.levered_beta, a.erp)

    # -------- 1) Justified P/B --------
    pb = justified_pb(a.roe, a.growth_terminal, re)
    pb_vps = pb * base.book_value_per_share
    pb_up = (pb_vps / a.market_price - 1) if a.market_price else 0.0

    # -------- 2) Excess Returns Model --------
    # BV_t = BV_{t-1} * (1 + g_t * (1 - payout))   <- retencion de utilidades
    # NI_t = ROE * BV_{t-1}
    # Excess_t = (ROE - Re) * BV_{t-1}
    # PV = sum Excess_t / (1+Re)^t
    # Terminal: tras Y_n, ROE estable, g terminal, valor = Excess_{n+1} / (Re - g_terminal)
    bv = [base.book_value_equity]
    excess_returns = []
    pv_excess = []

    n = a.forecast_years
    high_n = a.high_growth_years
    retention = 1 - a.payout_ratio  # fraccion de NI que se reinvierte (aumenta BV)
    # Asumimos ROE constante en a.roe (simplificacion); en modelos completos converge
    roe = a.roe

    for t in range(1, n + 1):
        # Growth fade lineal de Y6-Y10 desde growth_high hacia growth_terminal
        if t <= high_n:
            g = a.growth_high
        else:
            step = t - high_n
            steps_remaining = n - high_n
            g = a.growth_high + (a.growth_terminal - a.growth_high) * (step / steps_remaining)

        # BV evoluciona por retencion: BV_t = BV_{t-1} + retained_earnings_t
        # ni_t = roe * bv[t-1]; retained = ni_t * retention
        ni_t = roe * bv[-1]
        retained = ni_t * retention
        bv_new = bv[-1] + retained
        bv.append(bv_new)

        excess = (roe - re) * bv[-2]    # excess returns earned during year t
        excess_returns.append(excess)
        pv_excess.append(excess / (1 + re) ** t)

    sum_pv = sum(pv_excess)

    # Terminal value (Gordon sobre excess returns)
    excess_t11 = (roe - re) * bv[-1]
    if re > a.growth_terminal + 0.001:
        tv_excess = excess_t11 / (re - a.growth_terminal)
    else:
        tv_excess = 0.0
    pv_tv = tv_excess / (1 + re) ** n

    # Total value
    er_total = base.book_value_equity + sum_pv + pv_tv
    er_vps = er_total * 1e6 / base.shares_outstanding if base.shares_outstanding > 0 else 0.0
    er_up = (er_vps / a.market_price - 1) if a.market_price else 0.0

    return FinancialOutput(
        base=base,
        assumptions=a,
        cost_of_equity=re,
        justified_pb=pb,
        pb_value_per_share=pb_vps,
        pb_upside=pb_up,
        sum_pv_excess=sum_pv,
        pv_terminal=pv_tv,
        er_total_value=er_total,
        er_value_per_share=er_vps,
        er_upside=er_up,
    )


def value_financial_from_parser(
    res,
    market_price: float,
    risk_free: float = RF_MX_DEFAULT,
    erp: float = ERP_MX_DEFAULT,
    levered_beta: float = 1.10,
    growth_high: float = 0.06,
    growth_terminal: float = 0.03,
) -> FinancialOutput:
    """Convenience: arma base + assumptions desde un ParseResult del parser."""
    base = FinancialBase.from_parser_result(res)
    payout = base.implied_payout
    payout = min(max(payout, 0.20), 0.80)  # clamp razonable
    assumptions = FinancialAssumptions(
        roe=base.roe,
        growth_high=growth_high,
        growth_terminal=growth_terminal,
        payout_ratio=payout,
        risk_free=risk_free,
        erp=erp,
        levered_beta=levered_beta,
        market_price=market_price,
    )
    return value_financial(base, assumptions)
