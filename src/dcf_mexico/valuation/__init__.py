# Imports core (necesarios para el motor DCF — si fallan, app no funciona)
from .wacc import (  # noqa: F401
    cost_of_equity_capm,
    relever_beta,
    unlever_beta,
    synthetic_rating,
    compute_wacc,
    WACCResult,
)
from .dcf_fcff import (  # noqa: F401
    DCFAssumptions,
    DCFOutput,
    CompanyBase,
    project_company,
)
from .sensitivity import tornado, matrix  # noqa: F401
from .runner import value_one, ValuationRow, assumptions_from_config  # noqa: F401
from .financial import (  # noqa: F401
    FinancialAssumptions,
    FinancialBase,
    FinancialOutput,
    value_financial,
    value_financial_from_parser,
    justified_pb,
)

# Imports opcionales — si fallan, el resto sigue funcionando.
# Esto evita que un bug en un sub-módulo (como excel_export que depende
# de openpyxl, o dupont que es analytics extra) tire toda la app.
try:
    from .dupont import (  # noqa: F401
        DuPontResult,
        compute_dupont,
        dupont_from_parser,
    )
except Exception as _e:
    import sys as _sys
    print(f"[valuation] dupont no disponible: "
          f"{type(_e).__name__}: {_e}", file=_sys.stderr)

try:
    from .excel_export import export_dcf_to_excel  # noqa: F401
except Exception as _e:
    import sys as _sys
    print(f"[valuation] excel_export no disponible: "
          f"{type(_e).__name__}: {_e}", file=_sys.stderr)
