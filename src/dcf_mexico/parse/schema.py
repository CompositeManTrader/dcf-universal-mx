"""Estructuras tipadas para los EEFF parseados del XBRL CNBV."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import pandas as pd


@dataclass
class CompanyInfo:
    ticker: str = ""
    entity_name: str = ""
    period_end: str = ""               # YYYY-MM-DD
    quarter: str = ""                  # 1..4
    fiscal_year: int = 0
    currency: str = "MXN"
    rounding: str = ""                 # "Pesos", "Miles", "Millones"
    issuer_type: str = ""              # ICS, BM, CB, SF, SA, FI...
    is_financial: bool = False


@dataclass
class BalanceSheet:
    """Valores en unidades originales del XBRL (ver CompanyInfo.rounding)."""
    # ACTIVOS
    cash: float = 0.0                               # Efectivo y equivalentes
    accounts_receivable: float = 0.0
    inventories: float = 0.0
    other_current_assets: float = 0.0
    total_current_assets: float = 0.0
    ppe: float = 0.0                                # Propiedad, planta y equipo
    intangibles: float = 0.0
    goodwill: float = 0.0
    right_of_use_assets: float = 0.0                # IFRS 16
    investments_in_associates: float = 0.0
    deferred_tax_assets: float = 0.0
    other_non_current_assets: float = 0.0
    total_non_current_assets: float = 0.0
    total_assets: float = 0.0
    # PASIVOS
    short_term_debt: float = 0.0                    # Otros pasivos financieros CP
    short_term_lease: float = 0.0                   # Arrendamiento CP
    accounts_payable: float = 0.0
    other_current_liabilities: float = 0.0
    total_current_liabilities: float = 0.0
    long_term_debt: float = 0.0
    long_term_lease: float = 0.0
    deferred_tax_liabilities: float = 0.0
    other_non_current_liabilities: float = 0.0
    total_non_current_liabilities: float = 0.0
    total_liabilities: float = 0.0
    # CAPITAL
    equity_controlling: float = 0.0                 # Participacion controladora
    minority_interest: float = 0.0
    total_equity: float = 0.0

    @property
    def total_financial_debt(self) -> float:
        return self.short_term_debt + self.long_term_debt

    @property
    def total_lease_debt(self) -> float:
        return self.short_term_lease + self.long_term_lease

    @property
    def total_debt_with_leases(self) -> float:
        return self.total_financial_debt + self.total_lease_debt

    @property
    def net_debt(self) -> float:
        return self.total_debt_with_leases - self.cash

    @property
    def working_capital(self) -> float:
        return (self.accounts_receivable + self.inventories) - self.accounts_payable

    @property
    def invested_capital(self) -> float:
        return self.equity_controlling + self.total_debt_with_leases - self.cash


@dataclass
class IncomeStatement:
    """Acumulado del periodo (NO trimestre individual).

    Para los valores PURE QUARTER (3 meses cerrando en period_end),
    ver `IncomeStatementQuarter` (camp 'quarter' en ParseResult).
    """
    revenue: float = 0.0
    cost_of_sales: float = 0.0
    gross_profit: float = 0.0
    operating_expenses: float = 0.0          # = selling + g&a + general (sumados)
    selling_expenses: float = 0.0            # Gastos de venta (separado)
    ga_expenses: float = 0.0                 # Gastos de administracion (separado)
    other_operating_income: float = 0.0      # Otros ingresos (positivo)
    other_operating_expense: float = 0.0     # Otros gastos (positivo)
    other_operating: float = 0.0             # = other_op_income - other_op_expense (legacy)
    ebit: float = 0.0
    interest_income: float = 0.0
    interest_expense: float = 0.0
    fx_result: float = 0.0
    associates_result: float = 0.0
    pretax_income: float = 0.0
    tax_expense: float = 0.0
    net_income: float = 0.0
    net_income_controlling: float = 0.0
    net_income_minority: float = 0.0

    @property
    def gross_margin(self) -> float:
        return self.gross_profit / self.revenue if self.revenue else 0.0

    @property
    def operating_margin(self) -> float:
        return self.ebit / self.revenue if self.revenue else 0.0

    @property
    def net_margin(self) -> float:
        return self.net_income / self.revenue if self.revenue else 0.0

    @property
    def effective_tax_rate(self) -> float:
        if self.pretax_income > 0:
            r = self.tax_expense / self.pretax_income
            return r if 0.0 <= r <= 0.50 else 0.30
        return 0.30


@dataclass
class IncomeStatementQuarter:
    """Income statement del TRIMESTRE PURO (3 meses, no acumulado).

    Viene de col 1 de hoja 310000 del XBRL CNBV ('Trimestre Actual').
    Para Q1, equivale a income (acumulado=trimestre). Para Q2/Q3/Q4 difiere.
    """
    revenue: float = 0.0
    cost_of_sales: float = 0.0
    gross_profit: float = 0.0
    operating_expenses: float = 0.0
    selling_expenses: float = 0.0
    ga_expenses: float = 0.0
    other_operating_income: float = 0.0
    other_operating_expense: float = 0.0
    other_operating: float = 0.0
    ebit: float = 0.0
    interest_income: float = 0.0
    interest_expense: float = 0.0
    fx_result: float = 0.0
    associates_result: float = 0.0
    pretax_income: float = 0.0
    tax_expense: float = 0.0
    net_income: float = 0.0
    net_income_controlling: float = 0.0
    net_income_minority: float = 0.0


@dataclass
class CashFlow:
    """Acumulado del periodo."""
    cfo: float = 0.0                                # Flujo de operacion
    capex_ppe: float = 0.0                          # Compras PPE (positivo = outflow)
    capex_intangibles: float = 0.0
    sales_of_ppe: float = 0.0                       # Ventas PPE (positivo = inflow)
    acquisitions: float = 0.0
    cfi: float = 0.0                                # Flujo de inversion (puede ser negativo)
    debt_issued: float = 0.0
    debt_repaid: float = 0.0
    dividends_paid: float = 0.0
    cff: float = 0.0
    net_change_cash: float = 0.0
    disposal_loss_gain: float = 0.0                 # (-) Pérdida (utilidad) por disposicion de activos
                                                     # CNBV: positivo = perdida, negativo = ganancia
                                                     # Bloomberg: Disposal of Assets (positivo = gain to abnormal)

    @property
    def capex_gross(self) -> float:
        return self.capex_ppe + self.capex_intangibles

    @property
    def capex_net(self) -> float:
        return self.capex_gross - self.sales_of_ppe

    @property
    def fcff_simple(self) -> float:
        """Aproximacion: CFO - Capex neto. Para FCFF formal usar valuation/dcf_fcff.py."""
        return self.cfo - self.capex_net


@dataclass
class Informative:
    shares_outstanding: float = 0.0                 # Suma de todas las series
    shares_by_series: dict = field(default_factory=dict)
    da_12m: float = 0.0                             # D&A 12 meses (de 700003)
    da_quarter: float = 0.0                         # D&A del TRIMESTRE puro (700002 col 1)
    revenue_12m: float = 0.0
    revenue_12m_prior: float = 0.0
    ebit_12m: float = 0.0
    ebit_12m_prior: float = 0.0
    num_employees: float = 0.0                      # 700000 "Numero de empleados"
    num_workers: float = 0.0                        # 700000 "Numero de obreros"
    # Hoja 800200 Notas - Analisis de ingresos y gastos
    deferred_tax_acum: float = 0.0                  # row 29 "Impuesto diferido" acumulado
    deferred_tax_quarter: float = 0.0               # row 29 col 1 trimestre
    current_tax_acum: float = 0.0                   # row 28 "Impuesto causado" acumulado
    current_tax_quarter: float = 0.0                # row 28 col 1 trimestre
    interest_earned_acum: float = 0.0               # row 14 "Intereses ganados" acumulado
    interest_earned_quarter: float = 0.0            # row 14 col 1 trimestre
    fx_gain_acum: float = 0.0                       # row 15 "Utilidad por fluctuacion cambiaria" acum
    fx_gain_quarter: float = 0.0                    # row 15 col 1 trimestre
    # Hoja 800005 Distribucion de ingresos por productos
    sales_local_acum: float = 0.0                   # Mexico (acumulado)
    sales_export_acum: float = 0.0                  # USA + RoW (acumulado)


@dataclass
class DCFInputs:
    """Snapshot consolidado para alimentar el modelo Damodaran."""
    ticker: str = ""
    period_end: str = ""
    currency: str = "MXN"
    units: str = "MDP"                              # Millones de pesos
    # Resultados (12M)
    revenue: float = 0.0
    revenue_prior: float = 0.0
    revenue_growth: float = 0.0
    ebit: float = 0.0
    operating_margin: float = 0.0
    da: float = 0.0
    capex_gross: float = 0.0
    capex_net: float = 0.0
    interest_expense: float = 0.0
    pretax_income: float = 0.0
    tax_expense: float = 0.0
    effective_tax_rate: float = 0.30
    marginal_tax_rate: float = 0.30
    net_income: float = 0.0
    # Balance
    cash: float = 0.0
    financial_debt: float = 0.0
    lease_debt: float = 0.0
    total_debt: float = 0.0
    equity_bv: float = 0.0
    minority_interest: float = 0.0
    non_operating_assets: float = 0.0
    total_assets: float = 0.0
    invested_capital: float = 0.0
    # Otros
    shares_outstanding: float = 0.0
    sales_to_capital: float = 0.0
    interest_coverage: float = 0.0
    # Llenar manualmente
    market_price: Optional[float] = None
    risk_free_rate: Optional[float] = None          # M-BONO 10Y
    erp_mexico: Optional[float] = None              # Rf US + CRP MX

    def to_series(self) -> pd.Series:
        return pd.Series(asdict(self))


@dataclass
class ValidationReport:
    ok: bool = True
    issues: list = field(default_factory=list)

    def add(self, severity: str, msg: str):
        self.issues.append(f"[{severity}] {msg}")
        if severity == "ERROR":
            self.ok = False
