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
    # AUDIT FIX: era float=0.27 pero project_company lo IGNORABA (usaba
    # siempre base.effective_tax_rate). Ahora Optional: si el analista lo
    # define (Input Sheet sec C), se usa; si None, cae a base.effective_tax_rate.
    effective_tax_base: Optional[float] = None
    marginal_tax_current: float = MARGINAL_TAX_MX   # BUG #13: usado en Hamada (current)
    marginal_tax_terminal: float = MARGINAL_TAX_MX  # usado en NOPAT terminal y fade

    # ===== BLOQUE E — WACC =====
    risk_free: float = RF_MX_DEFAULT
    erp: float = ERP_MX_DEFAULT
    unlevered_beta: float = 0.85               # Damodaran industry default
    terminal_wacc_override: Optional[float] = None
    country_debt_premium: float = 0.0          # BUG #5: editable desde Input Sheet sec E
                                                # (solo > 0 si rf es USD-denominated)

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
    # 7. Employee options (BUG #9: dilución del equity)
    # Damodaran: equity_value debe restar el valor de opciones outstanding.
    # Aproximación simple intrinsic value (Black-Scholes pendiente).
    options_count: float = 0.0                  # MILLONES de opciones outstanding
    options_strike: float = 0.0                 # MXN strike promedio

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
        Las acciones (shares) y tasas (%) NO se multiplican.

        ⚠️ Damodaran B14: BV equity = total (controladora + minority).
        Esto afecta Invested Capital y por ende ROIC. Antes usábamos
        sólo controladora — fix Nov 2025."""
        debt = dcf.total_debt if include_leases_as_debt else dcf.financial_debt
        m = currency_multiplier
        # B14: BV equity TOTAL (controladora + minority) por convención Damodaran
        equity_bv = (dcf.equity_bv + (dcf.minority_interest or 0)) * m
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
            equity_book=equity_bv,                          # = total equity (Damodaran B14)
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
    # ===== NEW Hoja 2: Implied / tracked variables =====
    nol_remaining: list = field(default_factory=list)        # NOL al CIERRE del año t
    nol_used: list = field(default_factory=list)              # NOL aplicado en el año t
    tax_shield: list = field(default_factory=list)            # Ahorro fiscal por NOL
    sales_to_capital_yearly: list = field(default_factory=list)  # S2C usado en año t
    invested_capital: list = field(default_factory=list)      # IC al CIERRE del año t
    roic_yearly: list = field(default_factory=list)           # NOPAT_t / IC_{t-1}
    # Terminal
    terminal_fcff: float = 0.0
    terminal_value: float = 0.0
    pv_terminal: float = 0.0
    terminal_wacc: float = 0.0
    terminal_roic: float = 0.0                                # NEW: ROIC terminal usado
    terminal_reinv_rate: float = 0.0                          # NEW: g/ROIC terminal
    # Agregados
    sum_pv_fcff: float = 0.0
    operating_value_dcf: float = 0.0                          # NEW: pre-failure adjustment
    distress_proceeds: float = 0.0                            # NEW: bridge desglosado
    enterprise_value: float = 0.0
    equity_value: float = 0.0
    value_per_share: float = 0.0
    upside_pct: float = 0.0
    # ===== Tracking warnings y overrides silenciosos (BUG #4, #12) =====
    terminal_wacc_sanity_overridden: bool = False             # True si sanity check forzó cambio
    terminal_wacc_sanity_reason: str = ""                     # explicación del override
    nol_unused_at_y10: float = 0.0                            # NOL > 0 al fin de forecast (BUG #12)
    options_value_subtracted: float = 0.0                     # BUG #9 employee options dilution

    def projection_table(self) -> pd.DataFrame:
        """Tabla principal Damodaran-style (12 columnas, año a año)."""
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

    def implied_table(self) -> pd.DataFrame:
        """Implied variables Damodaran-style (Hoja 2):
        Sales-to-capital, Invested Capital evolutivo, ROIC año a año + check vs WACC."""
        rows = []
        for i, t in enumerate(self.years):
            ic_t = self.invested_capital[i]
            roic_t = self.roic_yearly[i]
            wacc_t = self.wacc_yearly[i]
            spread = roic_t - wacc_t
            rows.append({
                "Year": t,
                "Sales/Capital": round(self.sales_to_capital_yearly[i], 4),
                "Invested Capital": round(ic_t, 1),
                "ROIC": round(roic_t, 4),
                "WACC": round(wacc_t, 4),
                "ROIC - WACC (bps)": int(round(spread * 10000)),
                "Value Creation": "✅ CREATES" if spread > 0 else ("➖ NEUTRAL" if abs(spread) < 0.005 else "❌ DESTROYS"),
            })
        # Terminal row
        rows.append({
            "Year": "Terminal",
            "Sales/Capital": "—",
            "Invested Capital": "—",
            "ROIC": round(self.terminal_roic, 4),
            "WACC": round(self.terminal_wacc, 4),
            "ROIC - WACC (bps)": int(round((self.terminal_roic - self.terminal_wacc) * 10000)),
            "Value Creation": "—" if abs(self.terminal_roic - self.terminal_wacc) < 0.0005
                              else ("✅" if self.terminal_roic > self.terminal_wacc else "❌"),
        })
        return pd.DataFrame(rows)

    def nol_table(self) -> pd.DataFrame:
        """NOL tracking Damodaran-style (Hoja 2). Solo si NOL > 0."""
        rows = []
        nol_initial = self.assumptions.nol_carryforward
        for i, t in enumerate(self.years):
            rows.append({
                "Year": t,
                "EBIT": round(self.ebit[i], 1),
                "NOL Used": round(self.nol_used[i], 1),
                "Tax Shield": round(self.tax_shield[i], 1),
                "NOL Remaining (EOY)": round(self.nol_remaining[i], 1),
            })
        return pd.DataFrame(rows)

    def bridge_table(self) -> pd.DataFrame:
        """Bridge desglosado EV → Equity Value (Damodaran-style).

        AUDIT FIX: cuando probability_of_failure > 0, el blend se hace a
        NIVEL EQUITY (no EV), asi que el bridge muestra explicitamente
        equity_going_concern, equity_distress y el blend — antes las filas
        (-debt +cash...) sobre el EV blend no sumaban al equity_value."""
        a = self.assumptions
        b = self.base
        net_debt = b.financial_debt - b.cash
        cash_haircut = a.trapped_cash * a.trapped_cash_tax_rate if a.trapped_cash > 0 else 0
        equity_gc = (self.operating_value_dcf - net_debt - cash_haircut
                     - b.minority_interest + b.non_operating_assets)
        rows = [
            ("Sum PV FCFF (10y)",              self.sum_pv_fcff),
            ("PV(Terminal Value)",             self.pv_terminal),
            ("DCF Operating Value",            self.operating_value_dcf),
            ("(-) Total Debt",                 -b.financial_debt),
            ("(+) Cash",                        b.cash),
            ("(-) Trapped Cash haircut",       -cash_haircut if cash_haircut > 0 else "n/a"),
            ("(-) Minority Interest",          -b.minority_interest),
            ("(+) Non-Operating Assets",        b.non_operating_assets),
            ("Equity (going concern)",          equity_gc),
        ]
        if a.probability_of_failure > 0:
            equity_distress = max(
                0.0,
                self.distress_proceeds - b.financial_debt - b.minority_interest,
            )
            rows += [
                ("Distress proceeds (total firm)",  self.distress_proceeds),
                ("Equity en distress (residual)",   equity_distress),
                (f"Blend: (1-p)×GC + p×distress (p={a.probability_of_failure:.1%})",
                                                    self.equity_value),
            ]
        rows += [
            ("(-) Employee options",            -self.options_value_subtracted
                                                  if self.options_value_subtracted > 0 else "n/a"),
            ("Equity Value",                    self.equity_value),
            ("÷ Shares (M)",                    b.shares_outstanding / 1e6),
            ("Estimated Value/Share (MXN)",     self.value_per_share),
            ("Market Price (MXN)",              a.market_price or 0),
            ("Upside / (Downside)",             f"{self.upside_pct:.2%}"),
        ]
        return pd.DataFrame(rows, columns=["Concepto", "Valor"])

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
        # BUG #6 fix: fallback usa BV equity (Damodaran-recommended proxy)
        # en lugar del arbitrario debt × 1.5.
        market_cap = max(base.equity_book, base.financial_debt * 0.5, 1.0)

    wacc_res = compute_wacc(
        market_cap=market_cap,
        total_debt=base.financial_debt,
        interest_coverage=base.ebit / max(base.interest_expense, 1e-6),
        unlevered_beta=a.unlevered_beta,
        risk_free=a.risk_free,
        erp=a.erp,
        # BUG #13 fix: Hamada usa marginal_tax_current (statutory hoy),
        # no marginal_tax_terminal (potencial cambio futuro).
        marginal_tax=a.marginal_tax_current,
        # BUG #5 fix: pasar country_debt_premium del Input Sheet
        country_debt_premium=a.country_debt_premium,
    )

    # Terminal WACC: 3 modos
    #   1. Override explícito (terminal_wacc_override)
    #   2. Override vía rf terminal (BUG #8: recomputar WACC con nuevo rf)
    #   3. Default: mismo WACC inicial (no fade)
    terminal_wacc_overridden = False
    terminal_wacc_reason = ""
    if a.terminal_wacc_override is not None:
        terminal_wacc = a.terminal_wacc_override
    elif a.override_terminal_riskfree:
        # BUG #8 fix: recomputar WACC terminal usando rf override.
        # Asume β terminal = 1.0 (mature company), D/E = current.
        wacc_terminal_res = compute_wacc(
            market_cap=market_cap,
            total_debt=base.financial_debt,
            interest_coverage=base.ebit / max(base.interest_expense, 1e-6),
            unlevered_beta=1.0,                               # mature → β=1
            risk_free=a.terminal_riskfree_override,
            erp=a.erp,
            marginal_tax=a.marginal_tax_terminal,
            country_debt_premium=a.country_debt_premium,
        )
        terminal_wacc = wacc_terminal_res.wacc
    else:
        terminal_wacc = wacc_res.wacc
    # Sanity: terminal WACC debe ser > terminal growth + buffer (Gordon estable)
    # BUG #4 fix: trackeamos el override para mostrar warning en UI
    if terminal_wacc <= a.terminal_growth + 0.005:
        original = terminal_wacc
        terminal_wacc = a.terminal_growth + 0.02
        terminal_wacc_overridden = True
        terminal_wacc_reason = (
            f"Original {original:.2%} ≤ g_terminal {a.terminal_growth:.2%} + 0.5%; "
            f"forzado a g + 2% = {terminal_wacc:.2%} para estabilidad Gordon. "
            f"Damodaran B68: g > rf + 1% rinde valuación inválida."
        )

    # 2) Setup forecast
    n = a.forecast_years
    high_n = a.high_growth_years
    base_margin = base.ebit / base.revenue if base.revenue else a.target_op_margin
    # BUG #3 fix: clamp effective_tax_rate a [0, 0.50] para evitar refunds
    # negativos o tax rates inflados que distorsionarían NOPAT.
    # AUDIT FIX: respetar a.effective_tax_base si el analista lo definio
    # en el Input Sheet (antes se ignoraba silenciosamente).
    _tax_source = (a.effective_tax_base
                   if a.effective_tax_base is not None
                   else base.effective_tax_rate)
    base_tax = max(0.0, min(0.50, _tax_source))

    out = DCFOutput(
        base=base,
        assumptions=a,
        wacc_result=wacc_res,
        terminal_wacc=terminal_wacc,
        terminal_wacc_sanity_overridden=terminal_wacc_overridden,
        terminal_wacc_sanity_reason=terminal_wacc_reason,
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

    # NOL tracking inicial
    nol_remaining = a.nol_carryforward
    # Invested Capital inicial (BS-based o derivado de S2C si no esta disponible)
    ic_prev = base.invested_capital if base.invested_capital > 0 else (
        base.revenue / a.sales_to_capital if a.sales_to_capital > 0 else 1.0
    )

    # ===== AUDIT FIX: reinvestment_lag ahora SI se implementa =====
    # Damodaran: la inversion de HOY genera el crecimiento de MAÑANA.
    # Con lag=L, Reinvestment_t se dimensiona con ΔRevenue_{t+L}.
    # Precomputamos el revenue path Y1..Y(n+L); mas alla de Y_n el growth
    # se extiende con terminal_growth.
    lag = max(0, int(getattr(a, "reinvestment_lag", 0) or 0))
    _rev_path = [base.revenue]          # indice 0 = año base
    for _t in range(1, n + lag + 1):
        _g_t = _g(_t) if _t <= n else a.terminal_growth
        _rev_path.append(_rev_path[-1] * (1 + _g_t))

    prev_rev = base.revenue
    for t in range(1, n + 1):
        g = _g(t)
        rev_t = prev_rev * (1 + g)
        delta_rev = rev_t - prev_rev

        margin_t = _m(t)
        ebit_t = rev_t * margin_t

        tax_t = _tx(t)

        # ===== NOL Logic (Damodaran #6) =====
        # NOL reduce taxable income; tax_shield = nol_used × tax_t
        # AUDIT FIX (EBIT negativo): antes nopat = ebit*(1-tax) generaba un
        # "refund" implicito del 30% de la perdida (irreal: el fisco no
        # devuelve efectivo) y el NOL no crecia. Damodaran ginzu: en años de
        # perdida tax=0 y la perdida SE ACUMULA al NOL para escudar
        # utilidades futuras.
        if ebit_t < 0:
            nol_used_t = 0
            tax_shield_t = 0
            nol_remaining += -ebit_t        # la perdida engorda el NOL
            nopat_t = ebit_t                 # sin beneficio fiscal inmediato
        elif nol_remaining > 0:
            nol_used_t = min(nol_remaining, ebit_t)
            taxable_inc = ebit_t - nol_used_t
            nol_remaining -= nol_used_t
            tax_paid_t = max(0, taxable_inc) * tax_t
            tax_shield_t = nol_used_t * tax_t
            nopat_t = ebit_t - tax_paid_t
        else:
            nol_used_t = 0
            tax_shield_t = 0
            nopat_t = ebit_t * (1 - tax_t)

        s2c_t = _s2c(t)
        # BUG #1 fix: clamp reinvest >= 0. Si revenue cae (g < 0), no se
        # "des-invierte" (las fábricas no se desconstruyen gratis). Damodaran:
        # en años de declive, reinvestment floor = 0 (a menos que se modele
        # explícitamente liquidación de PPE, que no es nuestro caso).
        # AUDIT FIX: con reinvestment_lag, dimensionar con ΔRev futuro.
        if lag > 0:
            delta_rev_for_reinv = _rev_path[t + lag] - _rev_path[t + lag - 1]
        else:
            delta_rev_for_reinv = delta_rev
        reinvest_t = max(0.0, delta_rev_for_reinv / s2c_t) if s2c_t > 0 else 0.0
        fcff_t = nopat_t - reinvest_t

        # ===== Invested Capital evolutivo (Hoja 2 implied) =====
        # IC_t = IC_{t-1} + Reinvestment_t
        ic_t = ic_prev + reinvest_t
        # ROIC_t = NOPAT_t / IC_{t-1} (capital al INICIO del año generado returns)
        roic_t = nopat_t / ic_prev if ic_prev > 0 else 0.0

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
        # NEW Hoja 2 series
        out.nol_remaining.append(nol_remaining)
        out.nol_used.append(nol_used_t)
        out.tax_shield.append(tax_shield_t)
        out.sales_to_capital_yearly.append(s2c_t)
        out.invested_capital.append(ic_t)
        out.roic_yearly.append(roic_t)

        prev_rev = rev_t
        ic_prev = ic_t

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
    out.terminal_roic = terminal_roic
    out.terminal_reinv_rate = (a.terminal_growth / terminal_roic) if terminal_roic > 0 else 0.0

    # 4) Sum PV (operating value pre-failure adjustment)
    out.sum_pv_fcff = sum(out.pv_fcff)
    operating_value_dcf = out.sum_pv_fcff + pv_tv
    out.operating_value_dcf = operating_value_dcf

    # BUG #12 fix: track NOL no agotado al final del forecast
    out.nol_unused_at_y10 = nol_remaining if nol_remaining > 0 else 0.0

    # 5) Probability of failure adjustment (Damodaran) — REFACTOR (BUG #7)
    # ANTES: aplicaba el blend (1-p)·DCF + p·distress al EV completo, luego
    # restaba debt íntegro al equity. Esto sobreestima equity en distress
    # porque debtholders cobran PRIMERO en quiebra; equity recupera residual.
    # AHORA: blend a nivel EQUITY: (1-p)·equity_DCF + p·equity_distress
    #   donde equity_distress = max(0, distress_proceeds_total − debt − minority).
    # Para CUERVO (low leverage) el efecto es chico; para CEMEX (high lev) es
    # material.
    net_debt = base.financial_debt - base.cash
    # BUG #11 fix: removida línea muerta `cash_value = base.cash`.
    if a.trapped_cash > 0 and a.trapped_cash_tax_rate > 0:
        cash_haircut = a.trapped_cash * a.trapped_cash_tax_rate
        net_debt += cash_haircut    # equivalente a reducir cash en bridge

    equity_dcf_pre_failure = (
        operating_value_dcf - net_debt - base.minority_interest
        + base.non_operating_assets
    )

    if a.probability_of_failure > 0:
        # Distress proceeds totales (cubren a TODOS los stakeholders)
        if a.failure_proceeds_basis == "B":
            book_capital = (base.equity_book + base.financial_debt)
            distress_proceeds = book_capital * a.failure_proceeds_pct
        else:
            distress_proceeds = operating_value_dcf * a.failure_proceeds_pct
        # Equity solo recupera lo que quede DESPUÉS de pagar debt + minority
        equity_distress = max(
            0.0,
            distress_proceeds - base.financial_debt - base.minority_interest,
        )
        # Blend a nivel equity (NO a nivel EV como antes)
        out.equity_value = (
            (1 - a.probability_of_failure) * equity_dcf_pre_failure
            + a.probability_of_failure * equity_distress
        )
        out.distress_proceeds = distress_proceeds
        # EV reportado para diagnóstico (blend tradicional)
        out.enterprise_value = (
            (1 - a.probability_of_failure) * operating_value_dcf
            + a.probability_of_failure * distress_proceeds
        )
    else:
        out.distress_proceeds = 0.0
        out.enterprise_value = operating_value_dcf
        out.equity_value = equity_dcf_pre_failure

    # BUG #9 fix: dilución por employee options (intrinsic value approx).
    # No usamos Black-Scholes (overkill para nuestros casos MX), sino el
    # value intrínseco simple: max(0, value_per_share_pre - strike) × N_options.
    # Para Damodaran completo se requiere B-S; documentamos limitación.
    options_value = 0.0
    n_opts = getattr(a, "options_count", 0.0) or 0.0
    if n_opts > 0:
        # Calculamos value_per_share PRE-options para evitar circularidad simple
        vps_pre = (out.equity_value * 1e6 / base.shares_outstanding
                     if base.shares_outstanding > 0 else 0.0)
        strike = getattr(a, "options_strike", 0.0) or 0.0
        intrinsic_per_option = max(0.0, vps_pre - strike)
        # n_opts viene en MILLONES (mismo unit que el Input Sheet)
        options_value = intrinsic_per_option * n_opts * 1e6 / 1e6  # MDP
        out.equity_value -= options_value
    out.options_value_subtracted = options_value

    out.value_per_share = (
        out.equity_value * 1e6 / base.shares_outstanding
        if base.shares_outstanding > 0 else 0.0
    )

    if a.market_price and a.market_price > 0:
        out.upside_pct = out.value_per_share / a.market_price - 1.0

    return out
