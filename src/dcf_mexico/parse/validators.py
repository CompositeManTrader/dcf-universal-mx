"""Validaciones contables sobre los EEFF parseados."""
from dcf_mexico.parse.schema import BalanceSheet, IncomeStatement, ValidationReport


def _close(a: float, b: float, rel_tol: float = 0.005, abs_tol: float = 1.0) -> bool:
    if a == 0 and b == 0:
        return True
    return abs(a - b) <= max(abs_tol, rel_tol * max(abs(a), abs(b)))


def validate_balance(bs: BalanceSheet) -> ValidationReport:
    r = ValidationReport()

    # 1) Activo = Pasivo + Capital
    rhs = bs.total_liabilities + bs.total_equity
    if not _close(bs.total_assets, rhs):
        diff = bs.total_assets - rhs
        r.add("ERROR", f"A != L+E. A={bs.total_assets:,.0f}, L+E={rhs:,.0f}, diff={diff:,.0f}")

    # 2) Suma de circulante + no circulante = total activos
    if bs.total_current_assets and bs.total_non_current_assets:
        s = bs.total_current_assets + bs.total_non_current_assets
        if not _close(s, bs.total_assets):
            r.add("WARN", f"Activo CP+LP ({s:,.0f}) != Total ({bs.total_assets:,.0f})")

    # 3) Mismo para pasivos
    if bs.total_current_liabilities and bs.total_non_current_liabilities:
        s = bs.total_current_liabilities + bs.total_non_current_liabilities
        if not _close(s, bs.total_liabilities):
            r.add("WARN", f"Pasivo CP+LP ({s:,.0f}) != Total ({bs.total_liabilities:,.0f})")

    # 4) Equity = controladora + minoritario
    if bs.equity_controlling and bs.total_equity:
        s = bs.equity_controlling + bs.minority_interest
        if not _close(s, bs.total_equity):
            r.add("WARN", f"Equity controladora+minoritario ({s:,.0f}) != Total ({bs.total_equity:,.0f})")

    # 5) Sanity: activos positivos
    if bs.total_assets <= 0:
        r.add("ERROR", "Total de activos <= 0")

    return r


def validate_income(is_: IncomeStatement) -> ValidationReport:
    r = ValidationReport()

    if is_.revenue <= 0:
        r.add("ERROR", "Ingresos <= 0")

    # Gross profit = Revenue - COGS (COGS suele venir negativo en CNBV; revisar signo)
    # No forzamos check porque depende de la convencion de signo.

    # Net income = NI controladora + minoritario
    if is_.net_income and (is_.net_income_controlling or is_.net_income_minority):
        s = is_.net_income_controlling + is_.net_income_minority
        if not _close(s, is_.net_income):
            r.add("WARN", f"NI ctrl+minor ({s:,.0f}) != NI total ({is_.net_income:,.0f})")

    # Tax rate sanity
    etr = is_.effective_tax_rate
    if not (0.0 <= etr <= 0.50):
        r.add("WARN", f"Effective tax rate fuera de [0, 50%]: {etr:.2%}")

    return r


def merge_reports(*reports: ValidationReport) -> ValidationReport:
    out = ValidationReport()
    for rep in reports:
        out.issues.extend(rep.issues)
        if not rep.ok:
            out.ok = False
    return out
