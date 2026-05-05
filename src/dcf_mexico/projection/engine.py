"""
Motor de proyección de Estados Financieros (driver-based, integrado con DCF).

Filosofía:
- Los DRIVERS (revenue growth, gross margin, OpEx %, CapEx %, etc.) se calculan
  del histórico (auto-fill) o el analista los edita.
- A partir de drivers + base actual, se proyecta:
    Income Statement: Revenue → COGS → GP → OpEx → EBIT → NI
    Cash Flow: NI + D&A - CapEx - ΔWC = FCFF
    Balance Sheet (simplificado): cash + AR + Inv - AP + PPE = activos
- El FCFF resultante se usa DIRECTAMENTE en el DCF (un solo modelo coherente).

Uso:
    drivers = ProjectionDrivers.from_history(series)   # auto-fill
    drivers.gross_margin_path[0] = 0.58                 # editar
    base = BaseFinancials.from_snapshot(series.annual[-1])
    result = project_financials(base, drivers, horizon=5)
    print(result.income_statement_table())
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Dict
import statistics
import pandas as pd


# ============================================================================
# Datos base (anchor year actual)
# ============================================================================

@dataclass
class BaseFinancials:
    """Snapshot del año-ancla (típicamente último FY actual)."""
    year: int
    # Income Statement
    revenue: float
    cogs: float
    gross_profit: float
    opex: float                       # Selling + G&A + Other op
    ebit: float
    da: float                         # D&A 12M
    interest_expense: float           # Gastos financieros (positivo)
    pretax_income: float
    tax_expense: float
    net_income: float
    net_income_controlling: float
    # Balance Sheet
    cash: float
    accounts_receivable: float
    inventories: float
    accounts_payable: float
    ppe_net: float                    # PPE neto
    intangibles: float
    total_debt: float                 # Deuda financiera + leases
    equity_controlling: float
    total_assets: float
    # Cash Flow (acum)
    cfo: float
    capex: float                      # CapEx PPE + Intangibles (positivo = outflow)
    dividends_paid: float             # positivo
    # Misc
    shares_outstanding: float

    @classmethod
    def from_snapshot(cls, snap, fx_mult: float = 1.0) -> "BaseFinancials":
        """Construye desde un PeriodSnapshot. Valores en MDP."""
        p = snap.parsed
        inc, bs, cf, inf = p.income, p.balance, p.cashflow, p.informative
        m = fx_mult / 1_000_000

        return cls(
            year=snap.year,
            revenue=(inc.revenue or 0) * m * 1_000_000 / 1_000_000,
            cogs=(inc.cost_of_sales or 0) * fx_mult / 1_000_000,
            gross_profit=(inc.gross_profit or 0) * fx_mult / 1_000_000,
            opex=(inc.operating_expenses or 0) * fx_mult / 1_000_000,
            ebit=(inc.ebit or 0) * fx_mult / 1_000_000,
            da=(inf.da_12m or 0) * fx_mult / 1_000_000,
            interest_expense=abs(inc.interest_expense or 0) * fx_mult / 1_000_000,
            pretax_income=(inc.pretax_income or 0) * fx_mult / 1_000_000,
            tax_expense=(inc.tax_expense or 0) * fx_mult / 1_000_000,
            net_income=(inc.net_income or 0) * fx_mult / 1_000_000,
            net_income_controlling=(inc.net_income_controlling or inc.net_income or 0) * fx_mult / 1_000_000,
            # BS
            cash=(bs.cash or 0) * fx_mult / 1_000_000,
            accounts_receivable=(bs.accounts_receivable or 0) * fx_mult / 1_000_000,
            inventories=(bs.inventories or 0) * fx_mult / 1_000_000,
            accounts_payable=(bs.accounts_payable or 0) * fx_mult / 1_000_000,
            ppe_net=(bs.ppe or 0) * fx_mult / 1_000_000,
            intangibles=(bs.intangibles or 0) * fx_mult / 1_000_000,
            total_debt=bs.total_debt_with_leases * fx_mult / 1_000_000,
            equity_controlling=(bs.equity_controlling or 0) * fx_mult / 1_000_000,
            total_assets=(bs.total_assets or 0) * fx_mult / 1_000_000,
            # CF
            cfo=(cf.cfo or 0) * fx_mult / 1_000_000,
            capex=((cf.capex_ppe or 0) + (cf.capex_intangibles or 0)) * fx_mult / 1_000_000,
            dividends_paid=abs(cf.dividends_paid or 0) * fx_mult / 1_000_000,
            shares_outstanding=inf.shares_outstanding or 0,
        )


# ============================================================================
# Drivers de proyección (paths año por año)
# ============================================================================

@dataclass
class ProjectionDrivers:
    """Paths de drivers, longitud = horizon (años proyectados).

    Los paths se interpretan así:
      revenue_growth_path[0] = growth Y1 (vs base)
      revenue_growth_path[i] = growth Y_{i+1}
      etc.

    Construir con .from_history() para auto-fill desde histórico.
    """
    horizon: int                                     # años proyectados
    revenue_growth_path: List[float]                 # decimal (0.05 = 5%)
    gross_margin_path: List[float]                   # GM = (Rev - COGS)/Rev (display)
    opex_pct_revenue_path: List[float]               # OpEx / Revenue (display)
    ebit_margin_path: List[float]                    # EBIT/Revenue (DRIVER PRIMARIO)
    da_pct_revenue_path: List[float]                 # D&A / Revenue
    tax_rate_path: List[float]                       # Effective tax
    capex_pct_revenue_path: List[float]              # CapEx / Revenue
    # Working Capital (DIO/DSO/DPO en días)
    dio_days_path: List[float]                       # Inv / COGS × 365
    dso_days_path: List[float]                       # AR / Revenue × 365
    dpo_days_path: List[float]                       # AP / COGS × 365
    # Financiamiento
    interest_rate_on_debt: float = 0.10              # tasa promedio
    debt_change_pct_path: Optional[List[float]] = None   # change in debt as % of revenue (e.g. -1% = paying down)
    payout_ratio_path: Optional[List[float]] = None  # dividends / NI

    @classmethod
    def from_history(cls, series, horizon: int = 5,
                       fx_mult: float = 1.0,
                       smoothing: str = "median") -> "ProjectionDrivers":
        """Auto-calcula drivers desde el histórico anual.

        smoothing:
          - 'median': mediana de últimos N años (default, robusto)
          - 'last': último valor observado
          - 'avg': promedio últimos N años
        """
        snaps = series.annual
        if len(snaps) < 2:
            # Fallback: defaults Damodaran
            return cls._default(horizon)

        # Calcular ratios históricos
        gm_hist, opex_hist, ebit_margin_hist, da_hist, tax_hist, capex_hist = [], [], [], [], [], []
        dio_hist, dso_hist, dpo_hist = [], [], []
        growth_hist = []

        for i, s in enumerate(snaps):
            inc = s.parsed.income
            bs = s.parsed.balance
            cf = s.parsed.cashflow
            inf = s.parsed.informative
            rev = (inc.revenue or 0)
            if rev <= 0:
                continue
            cogs = (inc.cost_of_sales or 0)
            opex = (inc.operating_expenses or 0)
            da = (inf.da_12m or 0)
            ebit = (inc.ebit or 0)
            pbt = (inc.pretax_income or 0)
            tax = (inc.tax_expense or 0)
            capex = (cf.capex_ppe or 0) + (cf.capex_intangibles or 0)

            gm_hist.append((rev - cogs) / rev if rev > 0 else 0.40)
            opex_hist.append(opex / rev if rev > 0 else 0.20)
            ebit_margin_hist.append(ebit / rev if rev > 0 else 0.15)
            da_hist.append(da / rev if rev > 0 else 0.03)
            if pbt > 0 and tax >= 0:
                t_eff = tax / pbt
                if 0 <= t_eff <= 0.50:
                    tax_hist.append(t_eff)
            capex_hist.append(capex / rev if rev > 0 else 0.04)

            # WC days
            if cogs > 0:
                dio_hist.append((bs.inventories or 0) / cogs * 365)
                dpo_hist.append((bs.accounts_payable or 0) / cogs * 365)
            if rev > 0:
                dso_hist.append((bs.accounts_receivable or 0) / rev * 365)

            if i > 0:
                prev_rev = (snaps[i - 1].parsed.income.revenue or 0)
                if prev_rev > 0:
                    growth_hist.append((rev - prev_rev) / prev_rev)

        # Aplicar smoothing
        def _smooth(vals: List[float], default: float) -> float:
            if not vals:
                return default
            if smoothing == "last":
                return vals[-1]
            if smoothing == "avg":
                return sum(vals) / len(vals)
            return statistics.median(vals)

        gm_target = _smooth(gm_hist, 0.40)
        opex_target = _smooth(opex_hist, 0.20)
        ebit_margin_target = _smooth(ebit_margin_hist, 0.15)
        da_target = _smooth(da_hist, 0.03)
        tax_target = _smooth(tax_hist, 0.27)
        capex_target = _smooth(capex_hist, 0.04)
        dio_target = _smooth(dio_hist, 90.0)
        dso_target = _smooth(dso_hist, 60.0)
        dpo_target = _smooth(dpo_hist, 60.0)

        # Growth: usar último observado para Y1, mediana para Y2-N (mean reversion)
        growth_y1 = growth_hist[-1] if growth_hist else 0.05
        growth_long = _smooth(growth_hist, 0.05)
        # Path: Y1 = último, Y2..YN fade lineal a long-term
        growth_path = [growth_y1]
        for i in range(1, horizon):
            t = i / max(horizon - 1, 1)
            growth_path.append(growth_y1 * (1 - t) + growth_long * t)

        # Margin path: Y1 = current, target = mediana, fade gradual hacia Y_horizon
        gm_y1 = gm_hist[-1] if gm_hist else gm_target
        opex_y1 = opex_hist[-1] if opex_hist else opex_target
        ebit_margin_y1 = ebit_margin_hist[-1] if ebit_margin_hist else ebit_margin_target
        da_y1 = da_hist[-1] if da_hist else da_target
        capex_y1 = capex_hist[-1] if capex_hist else capex_target
        dio_y1 = dio_hist[-1] if dio_hist else dio_target
        dso_y1 = dso_hist[-1] if dso_hist else dso_target
        dpo_y1 = dpo_hist[-1] if dpo_hist else dpo_target

        def _fade(y1: float, target: float, n: int) -> List[float]:
            return [y1 * (1 - i/max(n-1, 1)) + target * i/max(n-1, 1) for i in range(n)]

        return cls(
            horizon=horizon,
            revenue_growth_path=growth_path,
            gross_margin_path=_fade(gm_y1, gm_target, horizon),
            opex_pct_revenue_path=_fade(opex_y1, opex_target, horizon),
            ebit_margin_path=_fade(ebit_margin_y1, ebit_margin_target, horizon),
            da_pct_revenue_path=_fade(da_y1, da_target, horizon),
            tax_rate_path=[tax_target] * horizon,
            capex_pct_revenue_path=_fade(capex_y1, capex_target, horizon),
            dio_days_path=_fade(dio_y1, dio_target, horizon),
            dso_days_path=_fade(dso_y1, dso_target, horizon),
            dpo_days_path=_fade(dpo_y1, dpo_target, horizon),
            interest_rate_on_debt=0.10,
            payout_ratio_path=[0.30] * horizon,
        )

    @classmethod
    def _default(cls, horizon: int) -> "ProjectionDrivers":
        """Defaults Damodaran genéricos cuando no hay histórico."""
        return cls(
            horizon=horizon,
            revenue_growth_path=[0.05] * horizon,
            gross_margin_path=[0.40] * horizon,
            opex_pct_revenue_path=[0.20] * horizon,
            ebit_margin_path=[0.15] * horizon,
            da_pct_revenue_path=[0.03] * horizon,
            tax_rate_path=[0.30] * horizon,
            capex_pct_revenue_path=[0.04] * horizon,
            dio_days_path=[90.0] * horizon,
            dso_days_path=[60.0] * horizon,
            dpo_days_path=[60.0] * horizon,
            interest_rate_on_debt=0.10,
            payout_ratio_path=[0.30] * horizon,
        )


# ============================================================================
# Año proyectado (output)
# ============================================================================

@dataclass
class ProjectedYear:
    year: int
    # Income Statement
    revenue: float
    cogs: float
    gross_profit: float
    gross_margin: float
    opex: float
    ebit: float
    op_margin: float
    da: float
    interest_expense: float
    pretax_income: float
    tax_expense: float
    tax_rate: float
    net_income: float
    # Balance Sheet (year-end)
    cash: float
    accounts_receivable: float
    inventories: float
    accounts_payable: float
    working_capital: float          # AR + Inv - AP
    ppe_net: float
    total_debt: float
    equity: float
    total_assets: float
    # Cash Flow
    cfo: float
    capex: float
    delta_wc: float
    fcff: float
    fcfe: float
    dividends_paid: float
    net_change_cash: float
    # Drivers usados (transparencia)
    revenue_growth_used: float


# ============================================================================
# Motor de proyección
# ============================================================================

@dataclass
class ProjectionResult:
    base: BaseFinancials
    drivers: ProjectionDrivers
    years: List[ProjectedYear]

    def income_statement_table(self) -> pd.DataFrame:
        """Tabla: filas=conceptos, cols=Y0 (base) + Y1..YN."""
        rows = [
            ("Revenue",          [self.base.revenue] + [y.revenue for y in self.years]),
            ("Revenue Growth",   ["—"] + [f"{y.revenue_growth_used*100:+.1f}%" for y in self.years]),
            ("(-) COGS",         [self.base.cogs] + [y.cogs for y in self.years]),
            ("Gross Profit",     [self.base.gross_profit] + [y.gross_profit for y in self.years]),
            ("Gross Margin",     [f"{(self.base.gross_profit/self.base.revenue)*100:.1f}%" if self.base.revenue else "—"]
                                 + [f"{y.gross_margin*100:.1f}%" for y in self.years]),
            ("(-) OpEx (Selling+G&A)", [self.base.opex] + [y.opex for y in self.years]),
            ("(-) Other Op Items", [self.base.gross_profit - self.base.opex - self.base.ebit]
                                  + [(y.gross_profit - y.opex - y.ebit) for y in self.years]),
            ("EBIT",             [self.base.ebit] + [y.ebit for y in self.years]),
            ("Op Margin",        [f"{(self.base.ebit/self.base.revenue)*100:.1f}%" if self.base.revenue else "—"]
                                 + [f"{y.op_margin*100:.1f}%" for y in self.years]),
            ("(-) Interest Exp", [self.base.interest_expense] + [y.interest_expense for y in self.years]),
            ("Pretax Income",    [self.base.pretax_income] + [y.pretax_income for y in self.years]),
            ("(-) Tax",          [self.base.tax_expense] + [y.tax_expense for y in self.years]),
            ("Tax Rate",         [f"{(self.base.tax_expense/self.base.pretax_income)*100:.1f}%" if self.base.pretax_income > 0 else "—"]
                                 + [f"{y.tax_rate*100:.1f}%" for y in self.years]),
            ("Net Income",       [self.base.net_income] + [y.net_income for y in self.years]),
        ]
        cols = [f"{self.base.year}A"] + [f"{y.year}E" for y in self.years]
        # Format numerics to 1 decimal
        def _fmt(v):
            if isinstance(v, (int, float)):
                return f"{v:>10,.1f}"
            return str(v)
        data = {col: [] for col in cols}
        labels = []
        for label, vals in rows:
            labels.append(label)
            for i, c in enumerate(cols):
                data[c].append(_fmt(vals[i]))
        df = pd.DataFrame(data, index=labels, dtype=object)
        return df

    def cash_flow_table(self) -> pd.DataFrame:
        rows = [
            ("Net Income",       [self.base.net_income] + [y.net_income for y in self.years]),
            ("(+) D&A",          [self.base.da] + [y.da for y in self.years]),
            ("(-) ΔWorking Cap", [0.0] + [y.delta_wc for y in self.years]),
            ("Cash from Ops",    [self.base.cfo] + [y.cfo for y in self.years]),
            ("(-) CapEx",        [-self.base.capex] + [-y.capex for y in self.years]),
            ("FCFF",             [self.base.cfo - self.base.capex] + [y.fcff for y in self.years]),
            ("FCFE",             ["—"] + [y.fcfe for y in self.years]),
            ("(-) Dividends",    [-self.base.dividends_paid] + [-y.dividends_paid for y in self.years]),
            ("Net Change Cash",  ["—"] + [y.net_change_cash for y in self.years]),
        ]
        cols = [f"{self.base.year}A"] + [f"{y.year}E" for y in self.years]
        def _fmt(v):
            if isinstance(v, (int, float)):
                return f"{v:>10,.1f}"
            return str(v)
        data = {col: [] for col in cols}
        labels = []
        for label, vals in rows:
            labels.append(label)
            for i, c in enumerate(cols):
                data[c].append(_fmt(vals[i]))
        return pd.DataFrame(data, index=labels, dtype=object)

    def balance_sheet_table(self) -> pd.DataFrame:
        rows = [
            ("Cash",                  [self.base.cash] + [y.cash for y in self.years]),
            ("Accounts Receivable",   [self.base.accounts_receivable] + [y.accounts_receivable for y in self.years]),
            ("Inventories",           [self.base.inventories] + [y.inventories for y in self.years]),
            ("PPE Net",               [self.base.ppe_net] + [y.ppe_net for y in self.years]),
            ("Total Assets (approx)", [self.base.total_assets] + [y.total_assets for y in self.years]),
            ("Accounts Payable",      [self.base.accounts_payable] + [y.accounts_payable for y in self.years]),
            ("Total Debt",            [self.base.total_debt] + [y.total_debt for y in self.years]),
            ("Equity",                [self.base.equity_controlling] + [y.equity for y in self.years]),
            ("Working Capital",       [self.base.accounts_receivable + self.base.inventories - self.base.accounts_payable]
                                       + [y.working_capital for y in self.years]),
        ]
        cols = [f"{self.base.year}A"] + [f"{y.year}E" for y in self.years]
        def _fmt(v):
            if isinstance(v, (int, float)):
                return f"{v:>10,.1f}"
            return str(v)
        data = {col: [] for col in cols}
        labels = []
        for label, vals in rows:
            labels.append(label)
            for i, c in enumerate(cols):
                data[c].append(_fmt(vals[i]))
        return pd.DataFrame(data, index=labels, dtype=object)

    def fcff_for_dcf(self) -> List[float]:
        """Devuelve la lista de FCFF años proyectados. Para alimentar DCF directo."""
        return [y.fcff for y in self.years]


def project_financials(
    base: BaseFinancials,
    drivers: ProjectionDrivers,
    horizon: Optional[int] = None,
) -> ProjectionResult:
    """Proyecta los EEFF a horizon años usando los drivers.

    Lógica:
    1. Revenue_t = Revenue_{t-1} × (1 + growth_t)
    2. COGS_t = Revenue_t × (1 - GM_t)
    3. OpEx_t = Revenue_t × opex_pct_t
    4. EBIT_t = Revenue_t - COGS_t - OpEx_t  (consistencia, no Rev × margin)
    5. D&A_t = Revenue_t × da_pct_t
    6. Interest_t = Total_Debt_{t-1} × interest_rate
    7. Tax_t = max(0, Pretax_t × tax_rate_t)
    8. NI_t = Pretax_t - Tax_t
    9. CapEx_t = Revenue_t × capex_pct_t
    10. WC_t = AR_t + Inv_t - AP_t (con DIO/DSO/DPO targets)
    11. ΔWC_t = WC_t - WC_{t-1}
    12. CFO_t = NI_t + D&A_t - ΔWC_t (indirect method simplificado)
    13. FCFF_t = CFO_t - CapEx_t (después de impuestos, BB-style)
    14. FCFE_t = FCFF_t + Net Debt Change - Interest × (1-tax)
    """
    n = horizon or drivers.horizon
    years = []
    prev_revenue = base.revenue
    prev_wc = base.accounts_receivable + base.inventories - base.accounts_payable
    prev_debt = base.total_debt
    prev_cash = base.cash
    prev_ppe = base.ppe_net
    prev_equity = base.equity_controlling

    for i in range(n):
        year_label = base.year + i + 1
        g = drivers.revenue_growth_path[i]
        rev = prev_revenue * (1 + g)

        # EBIT como driver PRIMARIO (consistente con DCF Damodaran).
        # GP y OpEx se calculan para display pero NO determinan EBIT.
        gm = drivers.gross_margin_path[i]
        cogs = rev * (1 - gm)
        gp = rev - cogs

        opex_pct = drivers.opex_pct_revenue_path[i]
        opex = rev * opex_pct

        op_margin = drivers.ebit_margin_path[i]
        ebit = rev * op_margin

        da = rev * drivers.da_pct_revenue_path[i]
        # Interest sobre deuda BoP
        interest = prev_debt * drivers.interest_rate_on_debt

        pretax = ebit - interest
        tax_rate = drivers.tax_rate_path[i]
        tax = max(0, pretax * tax_rate) if pretax > 0 else 0
        ni = pretax - tax

        # CapEx
        capex = rev * drivers.capex_pct_revenue_path[i]

        # Working Capital con DIO/DSO/DPO
        ar = rev * drivers.dso_days_path[i] / 365
        inv = cogs * drivers.dio_days_path[i] / 365
        ap = cogs * drivers.dpo_days_path[i] / 365
        wc = ar + inv - ap
        delta_wc = wc - prev_wc

        # CFO indirect simplificado: NI + D&A - ΔWC
        cfo = ni + da - delta_wc

        # FCFF (BB-style): CFO - CapEx
        fcff = cfo - capex

        # Debt change & FCFE
        debt_change = 0.0
        if drivers.debt_change_pct_path:
            debt_change = rev * drivers.debt_change_pct_path[i]
        new_debt = prev_debt + debt_change
        fcfe = fcff + debt_change - interest * (1 - tax_rate)

        # Dividendos
        payout = drivers.payout_ratio_path[i] if drivers.payout_ratio_path else 0.30
        divs = max(0, ni * payout)

        # Net change in cash
        net_change_cash = cfo - capex + debt_change - divs

        # PPE: prev + capex - D&A
        ppe = prev_ppe + capex - da

        # Equity: prev + NI - dividends
        equity = prev_equity + ni - divs

        # Total assets: cash + AR + Inv + PPE + intangibles (mantenidos)
        total_assets = (prev_cash + net_change_cash) + ar + inv + ppe + base.intangibles

        years.append(ProjectedYear(
            year=year_label,
            revenue=rev, cogs=cogs, gross_profit=gp, gross_margin=gm,
            opex=opex, ebit=ebit, op_margin=op_margin,
            da=da, interest_expense=interest, pretax_income=pretax,
            tax_expense=tax, tax_rate=tax_rate, net_income=ni,
            cash=prev_cash + net_change_cash,
            accounts_receivable=ar, inventories=inv, accounts_payable=ap,
            working_capital=wc, ppe_net=ppe,
            total_debt=new_debt, equity=equity, total_assets=total_assets,
            cfo=cfo, capex=capex, delta_wc=delta_wc,
            fcff=fcff, fcfe=fcfe, dividends_paid=divs,
            net_change_cash=net_change_cash,
            revenue_growth_used=g,
        ))

        # Avanzar estados
        prev_revenue = rev
        prev_wc = wc
        prev_debt = new_debt
        prev_cash = prev_cash + net_change_cash
        prev_ppe = ppe
        prev_equity = equity

    return ProjectionResult(base=base, drivers=drivers, years=years)
