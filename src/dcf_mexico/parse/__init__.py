# IMPORTANTE: cargar schema PRIMERO. Sin 'from __future__ import
# annotations', si xbrl_reader (que también hace `from .schema`) se
# carga antes que schema, Python re-entra parse/__init__.py para
# resolver el `.` relativo y se forma un circular import.
from .schema import (  # noqa: F401
    CompanyInfo, BalanceSheet, IncomeStatement, IncomeStatementQuarter,
    CashFlow, DCFInputs,
)
from .xbrl_reader import parse_xbrl, ParseResult  # noqa: F401
