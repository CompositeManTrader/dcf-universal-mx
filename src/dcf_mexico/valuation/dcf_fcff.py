"""
Motor DCF FCFF estilo Damodaran (10 anios + terminal Gordon), adaptado a Mexico.

Convenciones:
  - Anio 1-5: fase de alto crecimiento (revenue growth = `revenue_growth_high`)
  - Anio 6-10: fade lineal de growth/margin/WACC hacia terminal
  - Anio 11+ (Gordon): terminal_growth, terminal_margin, terminal_wacc

Inputs en MDP (millones de pesos), todos los outputs en MDP excepto value/share.

FCFF_t = EBIT_t * (1 - tax_t) - Reinvestment_t
Reinvestment_t = (Revenue_t - Revenue_{t-1}) / sales_to_capital
Terminal_FV = FCFF_{11} / (WACC_terminal - g_terminal)
Equity = EV - Net Debt + Cash + Non-op assets - Minority interest
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import math

import pandas as pd

from .wacc import (
    compute_wacc,
    WACCResult,
    RF_MX_DEFAULT,
    ERP_MX_DEFAULT,
    MARGINAL_TAX_MX,
)


# ---------------------------------------------------------------------------
@dataclass
class DCFAssumptions:
    """Drivers que el analista debe definir. Estilo Damodaran fcffsimpleginzu.

    MODO SMOOTH (default):
      - Y1: revenue_growth_y1 (si None, usa revenue_growth_high)
      - Y2..Y_high_n: revenue_growth_high constante
      - Y(high_n+1)..Y10: fade lineal a terminal_growth
      - Margin: lineal de op_margin_y1 (o current) a target_op_margin
                en `year_of_margin_convergence` (default Damodaran = Y5)
      - Tax: lineal de effective_tax_base a marginal_tax_terminal Y6-Y10
      - WACC: lineal Y6-Y10 a terminal_wacc_override

    MODO PER-YEAR (override total): listas de longitud forecast_years.
    """
    # ===== BLOQUE A — Identification =====
    country: str = "Mexico"
    industry_us: str = ""                     # Para lookup beta (Hoja 13)
    industry_global: str = ""

    # ===== BLOQUE D — Value Drivers =====
    # Crecimiento (Damodaran separa Y1 de Y2-Y5)
    revenue_growth_y1: Optional[float] = None  # NEW Damodaran-style: si None, usa _high
    revenue_growth_high: float = 0.07          # Y2..Y_high_n compounded (default Y2-Y5)
    terminal_growth: float = 0.035             # Y11+ (cap a inflacion MX o riskfree)

    # Margen (Damodaran separa Y1 margin de target con year_of_convergence)
    op_margin_y1: Optional[float] = None       # NEW: si None, usa current margin del base
    target_op_margin: float = 0.20             # margen estable post-convergencia
    year_of_margin_convergence: int = 5        # NEW Damodaran default = 5

    # Eficiencia capital (Damodaran permite distinto Y1-5 vs Y6-10)
    sales_to_capital: float = 1.50             # default usado para Y1-5 si _y1_5 no set
    sales_to_capital_y1_5: Optional[float] = None  # NEW Damodaran-style
    sales_to_capital_y6_10: Optional[float] = None # NEW Damodaran-style

    # Tax
    effective_tax_base: float = 0.27
    marginal_tax_terminal: float = MARGINAL_TAX_MX

    # ===== BLOQUE E — WACC =====
    risk_free: float = RF_MX_DEFAULT
    erp: float = ERP_MX_DEFAULT
    unlevered_beta: float = 0.85               # Damodaran industry default
    terminal_wacc_override: Optional[float] = None

    # Mercado
    market_price: Optional[float] = None       # MXN por accion

    # Horizonte
    forecast_years: int = 10
    high_growth_years: int = 5

    # ===== Damodaran ASUNCIONES (defaults overrideables) =====
    # 1. Terminal ROIC = WACC (no value creation steady state) — Damodaran default
    override_terminal_roic: bool = False
    terminal_roic_override: float = 0.15       # solo se usa si override=True
    # 2. Probability of failure
    probability_of_failure: float = 0.0        # 0% por default (firm sana)
    failure_proceeds_pct: float = 0.50         # % del valor recuperable en quiebra
    failure_proceeds_basis: str = "V"          # "V" fair value o "B" book value capital
    # 3. NOL carryforward
    nol_carryforward: float = 0.0              # MDP de NOL al inicio Y1
    # 4. Reinvestment lag (ΔRev_t = f(Reinvest_{t-lag}))
    reinvestment_lag: int = 0                  # default 0 (no lag)
    # 5. Terminal riskfree override (si analista cree que tasas cambiaran)
    override_terminal_riskfree: bool = False
    terminal_riskfree_override: float = 0.04
    # 6. Trapped cash (cash en jurisdicciones con tax adicional)
    trapped_cash: float = 0.0                  # MDP
    trapped_cash_tax_rate: float = 0.0         # tax rate adicional o discount

    # ---- PER-YEAR OVERRIDES (si se llenan, anulan la curva smooth) ----
    revenue_growth_per_year: Optional[list] = None
    op_margin_per_year: Optional[list] = None
    tax_rate_per_year: Optional[list] = None
    wacc_per_year: Optional[list] = None
    sales_to_capital_per_year: Optional[list] = None

    def to_series(self) -> pd.Series:
        d = asdict(self)
        # Reduce listas a strings para que pandas las muestre limpio
        for k in ("revenue_growth_per_year", "op_margin_per_year",
                  "tax_rate_per_year", "wacc_per_year",
                  "sales_to_capital_per_year"):
            if d.get(k) is not None:
                d[k] = ", ".join(f"{v:.4f}" for v in d[k])
        return pd.Series(d)

    @property
    def effective_revenue_growth_y1(self) -> float:
        """Devuelve el growth Y1 efectivo (Damodaran o fallback a high)."""
        return self.revenue_growth_y1 if self.revenue_growth_y1 is not None else self.revenue_growth_high

    @property
    def effective_op_margin_y1(self) -> Optional[float]:
        """Devuelve el margin Y1 efectivo si esta definido."""
        return self.op_margin_y1


# ---------------------------------------------------------------------------
@dataclass
class CompanyBase:
    """Snapshot del estado actual a partir del parser."""
    ticker: str
    revenue: float                              # MDP, 12M
    ebit: float                                 # MDP, 12M
    interest_expense: float                     # MDP, 12M
    cash: float                                 # MDP
    financial_debt: float                       # MDP (incluye leases si se decide capitalizar)
    minority_interest: float                    # MDP
    non_operating_assets: float                 # MDP
    shares_outstanding: float                   # absoluto (no millones)
    effective_tax_rate: float
    equity_book: float = 0.0                    # MDP, BV equity controladora
    invested_capital: float = 0.0               # MDP, IC = equity + debt - cash (BS-based)

    @classmethod
    def from_parser_dcf(cls, dcf, include_leases_as_debt: bool = True,
                          currency_multiplier: float = 1.0):
        """currency_multiplier: aplicar a TODOS los flujos monetarios.
        Para empresas que reportan en USD, pasar fx_rate_usdmxn (~19.5) para
        que la valuacion final quede en MXN (compatible con precios BMV).
        Las acciones (shares) y tasas (%) NO se multiplican."""
        debt = dcf.total_debt if include_leases_as_debt else dcf.financial_debt
        m = currency_multiplier
        equity_bv = dcf.equity_bv * m
        ic = (equity_bv + debt * m - dcf.cash * m)
        return cls(
            ticker=dcf.ticker,
            revenue=dcf.revenue * m,
            ebit=dcf.ebit * m,
            interest_expense=dcf.interest_expense * m,
            cash=dcf.cash * m,
            financial_debt=debt * m,
            minority_interest=dcf.minority_interest * m,
            non_operating_assets=dcf.non_operating_assets * m,
            shares_outstanding=dcf.shares_outstanding,    # NO multiplicar (es count)
            effective_tax_rate=dcf.effective_tax_rate,    # NO multiplicar (ratio)
            equity_book=equity_bv,
            invested_capital=ic,
        )


# ---------------------------------------------------------------------------
@dataclass
class DCFOutput:
    base: CompanyBase
    assumptions: DCFAssumptions
    wacc_result: WACCResult
    # Series anuales (longitud = forecast_years)
    years: list = field(default_factory=list)
    revenue: list = field(default_factory=list)
    op_margin: list = field(default_factory=list)
    ebit: list = field(default_factory=list)
    tax_rate: list = field(default_factory=list)
    nopat: list = field(default_factory=list)
    delta_revenue: list = field(default_factory=list)
    reinvestment: list = field(default_factory=list)
    fcff: list = field(default_factory=list)
    wacc_yearly: list = field(default_factory=list)
    discount_factor: list = field(default_factory=list)
    pv_fcff: list = field(default_factory=list)
    # Terminal
    terminal_fcff: float = 0.0
    terminal_value: float = 0.0
    pv_terminal: float = 0.0
    terminal_wacc: float = 0.0
    # Agregados
    sum_pv_fcff: float = 0.0
    enterprise_value: float = 0.0
    equity_value: float = 0.0
    value_per_share: float = 0.0
    upside_pct: float = 0.0

    def projection_table(self) -> pd.DataFrame:
        df = pd.DataFrame({
            "Year":              self.years,
            "Revenue":           [round(x, 1) for x in self.revenue],
            "Op Margin":         [round(x, 4) for x in self.op_margin],
            "EBIT":              [round(x, 1) for x in self.ebit],
            "Tax rate":          [round(x, 4) for x in self.tax_rate],
            "NOPAT":             [round(x, 1) for x in self.nopat],
            "Δ Revenue":         [round(x, 1) for x in self.delta_revenue],
            "Reinvestment":      [round(x, 1) for x in self.reinvestment],
            "FCFF":              [round(x, 1) for x in self.fcff],
            "WACC":              [round(x, 4) for x in self.wacc_yearly],
            "Discount Factor":   [round(x, 4) for x in self.discount_factor],
            "PV FCFF":           [round(x, 1) for x in self.pv_fcff],
        })
        return df

    def summary_table(self) -> pd.DataFrame:
        a = self.assumptions
        # Terminal ROIC effective (lo que se uso)
        terminal_roic_used = a.terminal_roic_override if a.override_terminal_roic else self.terminal_wacc
        # Failure proceeds preview
        if a.probability_of_failure > 0:
            if a.failure_proceeds_basis == "B":
                book_cap = self.base.equity_book + self.base.financial_debt
                distress = book_cap * a.failure_proceeds_pct
            else:
                distress = (self.sum_pv_fcff + self.pv_terminal) * a.failure_proceeds_pct
        else:
            distress = 0.0

        rows = [
            ("Sum PV FCFF (10y)",       f"{self.sum_pv_fcff:>12,.1f} MDP"),
            ("Terminal FCFF (Y11)",     f"{self.terminal_fcff:>12,.1f} MDP"),
            ("Terminal Value (TV)",     f"{self.terminal_value:>12,.1f} MDP"),
            ("PV Terminal Value",       f"{self.pv_terminal:>12,.1f} MDP"),
            ("DCF Operating Value",     f"{(self.sum_pv_fcff + self.pv_terminal):>12,.1f} MDP"),
            ("(-) Probability Failure",
                f"  p={a.probability_of_failure:.2%}, basis={a.failure_proceeds_basis}, recover={a.failure_proceeds_pct:.0%} -> distress={distress:>10,.1f} MDP"),
            ("Enterprise Value (final)",f"{self.enterprise_value:>12,.1f} MDP"),
            ("(-) Net Debt",            f"{self.base.financial_debt - self.base.cash:>12,.1f} MDP"),
            ("(-) Minority Interest",   f"{self.base.minority_interest:>12,.1f} MDP"),
            ("(+) Non-op Assets",       f"{self.base.non_operating_assets:>12,.1f} MDP"),
            ("Equity Value",            f"{self.equity_value:>12,.1f} MDP"),
            ("Shares (mn)",             f"{self.base.shares_outstanding/1e6:>12,.2f}"),
            ("Value per share (MXN)",   f"{self.value_per_share:>12,.2f}"),
            ("Market price (MXN)",      f"{a.market_price or 0:>12,.2f}"),
            ("Upside / (Downside)",     f"{self.upside_pct:>12,.2%}"),
            ("--- WACC ---",            ""),
            ("Levered Beta",            f"{self.wacc_result.levered_beta:>12.3f}"),
            ("Cost of Equity",          f"{self.wacc_result.cost_equity:>12.2%}"),
            ("Pretax Cost of Debt",     f"{self.wacc_result.pretax_cost_debt:>12.2%}"),
            ("Synthetic Rating",        f"{self.wacc_result.rating:>12}"),
            ("Initial WACC",            f"{self.wacc_result.wacc:>12.2%}"),
            ("Terminal WACC",           f"{self.terminal_wacc:>12.2%}"),
            ("--- Terminal ROIC (Damodaran) ---", ""),
            ("Terminal ROIC used",
                f"{terminal_roic_used:>12.2%}  ({'OVERRIDE' if a.override_terminal_roic else 'Damodaran default = WACC_terminal'})"),
            ("Terminal Reinvest Rate",
                f"{(a.terminal_growth/terminal_roic_used if terminal_roic_used > 0 else 0):>12.2%}  (= g_terminal / ROIC_terminal)"),
        ]
        return pd.DataFrame(rows, columns=["Concepto", "Valor"])


# ---------------------------------------------------------------------------
def _interpolate(start: float, end: float, n_steps: int, step: int) -> float:
    """Interpolacion lineal: en step=0 -> start; en step=n_steps -> end."""
    if n_steps <= 0:
        return end
    return start + (end - start) * (step / n_steps)


def project_company(
    base: CompanyBase,
    assumptions: DCFAssumptions,
) -> DCFOutput:
    """Genera proyeccion 10y + terminal. Devuelve DCFOutput completo."""
    a = assumptions

    # 1) WACC inicial via bottom-up
    market_cap = (a.market_price or 0) * base.shares_outstanding / 1e6  # MDP
    if market_cap <= 0:
        # Fallback: usar BV equity para inicializar WACC
        market_cap = max(base.financial_debt, 1.0) * 1.5

    wacc_res = compute_wacc(
        market_cap=market_cap,
        total_debt=base.financial_debt,
        interest_coverage=base.ebit / max(base.interest_expense, 1e-6),
        unlevered_beta=a.unlevered_beta,
        risk_free=a.risk_free,
        erp=a.erp,
        marginal_tax=a.marginal_tax_terminal,
    )

    # Terminal WACC: por defecto NO fade (mismo WACC inicial).
    # Justificacion: con high Rf MX (9.5%) y ERP MX alto (6.8%), forzar beta=1
    # al terminal genera WACC > inicial, lo cual no tiene sentido economico.
    # El analista puede pasar `terminal_wacc_override` para fade explicito.
    terminal_wacc = a.terminal_wacc_override
    if terminal_wacc is None:
        terminal_wacc = wacc_res.wacc
    # Sanity: terminal WACC debe ser > terminal growth (Gordon estabilidad)
    if terminal_wacc <= a.terminal_growth + 0.005:
        terminal_wacc = a.terminal_growth + 0.02

    # 2) Setup forecast
    n = a.forecast_years
    high_n = a.high_growth_years
    base_margin = base.ebit / base.revenue if base.revenue else a.target_op_margin
    base_tax = base.effective_tax_rate

    out = DCFOutput(
        base=base,
        assumptions=a,
        wacc_result=wacc_res,
        terminal_wacc=terminal_wacc,
    )

    # ===== Helpers Damodaran-style =====
    # Y1 separado de Y2..Y_high; fade Y(high+1)..Y_n a terminal.
    def _g(t):
        """Revenue growth en año t (1-indexed). Damodaran-style:
           Y1 puede tener growth distinto; Y2..high_n compounded; fade despues."""
        if a.revenue_growth_per_year and len(a.revenue_growth_per_year) >= t:
            return float(a.revenue_growth_per_year[t-1])
        if t == 1 and a.revenue_growth_y1 is not None:
            return a.revenue_growth_y1
        if t <= high_n:
            return a.revenue_growth_high
        step = t - high_n
        steps_remaining = n - high_n
        return _interpolate(a.revenue_growth_high, a.terminal_growth, steps_remaining, step)

    def _m(t):
        """Op margin en año t. Damodaran-style: parte de op_margin_y1 (o base)
           y converge a target_op_margin en year_of_margin_convergence."""
        if a.op_margin_per_year and len(a.op_margin_per_year) >= t:
            return float(a.op_margin_per_year[t-1])
        start_margin = a.op_margin_y1 if a.op_margin_y1 is not None else base_margin
        conv_year = a.year_of_margin_convergence
        if t >= conv_year:
            return a.target_op_margin
        # Lineal de Y1 (start_margin) a Y_conv (target)
        return _interpolate(start_margin, a.target_op_margin, conv_year, t)

    def _tx(t):
        """Tax rate Damodaran-style: effective_base hasta Y5, fade Y6-Y10 a marginal."""
        if a.tax_rate_per_year and len(a.tax_rate_per_year) >= t:
            return float(a.tax_rate_per_year[t-1])
        if t <= high_n:
            return base_tax
        step = t - high_n
        steps_remaining = n - high_n
        return _interpolate(base_tax, a.marginal_tax_terminal, steps_remaining, step)

    def _w(t):
        """WACC Damodaran-style: initial hasta Y5, fade Y6-Y10 a terminal."""
        if a.wacc_per_year and len(a.wacc_per_year) >= t:
            return float(a.wacc_per_year[t-1])
        if t <= high_n:
            return wacc_res.wacc
        step = t - high_n
        steps_remaining = n - high_n
        return _interpolate(wacc_res.wacc, terminal_wacc, steps_remaining, step)

    def _s2c(t):
        """Sales-to-Capital Damodaran-style: distinto Y1-5 vs Y6-10."""
        if a.sales_to_capital_per_year and len(a.sales_to_capital_per_year) >= t:
            return float(a.sales_to_capital_per_year[t-1])
        if t <= high_n:
            return a.sales_to_capital_y1_5 if a.sales_to_capital_y1_5 is not None else a.sales_to_capital
        return a.sales_to_capital_y6_10 if a.sales_to_capital_y6_10 is not None else a.sales_to_capital

    prev_rev = base.revenue
    for t in range(1, n + 1):
        g = _g(t)
        rev_t = prev_rev * (1 + g)
        delta_rev = rev_t - prev_rev

        margin_t = _m(t)
        ebit_t = rev_t * margin_t

        tax_t = _tx(t)
        nopat_t = ebit_t * (1 - tax_t)

        s2c_t = _s2c(t)
        reinvest_t = delta_rev / s2c_t if s2c_t > 0 else 0.0
        fcff_t = nopat_t - reinvest_t

        wacc_t = _w(t)

        # Discount factor acumulado (anios discretos, mid-year omitido por simplicidad)
        if t == 1:
            df = 1 / (1 + wacc_t)
        else:
            df = out.discount_factor[-1] * (1 / (1 + wacc_t))

        pv = fcff_t * df

        out.years.append(t)
        out.revenue.append(rev_t)
        out.op_margin.append(margin_t)
        out.ebit.append(ebit_t)
        out.tax_rate.append(tax_t)
        out.nopat.append(nopat_t)
        out.delta_revenue.append(delta_rev)
        out.reinvestment.append(reinvest_t)
        out.fcff.append(fcff_t)
        out.wacc_yearly.append(wacc_t)
        out.discount_factor.append(df)
        out.pv_fcff.append(pv)

        prev_rev = rev_t

    # 3) Terminal Value (Gordon) — Damodaran-style
    rev_t11 = out.revenue[-1] * (1 + a.terminal_growth)
    delta_rev_t11 = rev_t11 - out.revenue[-1]
    ebit_t11 = rev_t11 * a.target_op_margin
    nopat_t11 = ebit_t11 * (1 - a.marginal_tax_terminal)

    # Damodaran default: Terminal ROIC = Terminal WACC (no value creation steady state)
    # Reinvestment = (g_terminal / ROIC_terminal) × NOPAT_t11
    if a.override_terminal_roic:
        # Analista define ROIC_terminal explicito (puede ser > WACC si moat duradero)
        terminal_roic = a.terminal_roic_override
    else:
        # Damodaran default: ROIC_terminal = WACC_terminal
        terminal_roic = terminal_wacc

    if terminal_roic > 0:
        reinvest_t11 = (a.terminal_growth / terminal_roic) * nopat_t11
    else:
        reinvest_t11 = delta_rev_t11 / a.sales_to_capital if a.sales_to_capital > 0 else 0.0

    fcff_t11 = nopat_t11 - reinvest_t11

    tv = fcff_t11 / (terminal_wacc - a.terminal_growth)
    pv_tv = tv * out.discount_factor[-1]

    out.terminal_fcff = fcff_t11
    out.terminal_value = tv
    out.pv_terminal = pv_tv

    # 4) Sum PV (operating value pre-failure adjustment)
    out.sum_pv_fcff = sum(out.pv_fcff)
    operating_value_dcf = out.sum_pv_fcff + pv_tv

    # 5) Probability of failure adjustment (Damodaran)
    # Final = (1-p) × DCF_value + p × failure_proceeds
    if a.probability_of_failure > 0:
        if a.failure_proceeds_basis == "B":
            # Book value of capital = Book Equity + Book Debt
            book_capital = (base.equity_book + base.financial_debt)
            distress_proceeds = book_capital * a.failure_proceeds_pct
        else:
            # Fair value (V): % del DCF operating value
            distress_proceeds = operating_value_dcf * a.failure_proceeds_pct
        operating_value_adj = (1 - a.probability_of_failure) * operating_value_dcf \
                            + a.probability_of_failure * distress_proceeds
    else:
        operating_value_adj = operating_value_dcf

    out.enterprise_value = operating_value_adj
    net_debt = base.financial_debt - base.cash
    # Trapped cash: si lo hay, se descuenta el tax adicional sobre el cash repatriado
    cash_value = base.cash
    if a.trapped_cash > 0 and a.trapped_cash_tax_rate > 0:
        # Restar tax adicional sobre cash trapped al hacer bridge
        cash_haircut = a.trapped_cash * a.trapped_cash_tax_rate
        net_debt += cash_haircut    # equivalente a reducir cash en bridge

    out.equity_value = (
        out.enterprise_value
        - net_debt
        - base.minority_interest
        + base.non_operating_assets
    )
    out.value_per_share = out.equity_value * 1e6 / base.shares_outstanding if base.shares_outstanding > 0 else 0.0

    if a.market_price and a.market_price > 0:
        out.upside_pct = out.value_per_share / a.market_price - 1.0

    return out
