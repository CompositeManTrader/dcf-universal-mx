try:
    from .bloomberg import (  # noqa: F401
        build_all_sheets,
        gaap_highlights,
        income_statement_gaap,
        balance_sheet_standardized,
        cash_flow_standardized,
        enterprise_value_table,
        BLOOMBERG_HEADER,
    )
except Exception as _e:
    import sys as _sys
    print(f"[view] bloomberg no disponible: "
          f"{type(_e).__name__}: {_e}", file=_sys.stderr)
    BLOOMBERG_HEADER = "In Millions of MXN"
    def _stub(*a, **kw):
        raise ImportError("view.bloomberg failed to load — see logs")
    build_all_sheets = _stub
    gaap_highlights = _stub
    income_statement_gaap = _stub
    balance_sheet_standardized = _stub
    cash_flow_standardized = _stub
    enterprise_value_table = _stub
