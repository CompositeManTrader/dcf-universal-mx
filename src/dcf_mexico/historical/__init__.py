# Imports core
from .series import (  # noqa: F401
    HistoricalSeries,
    load_historical,
    PeriodSnapshot,
)

# Imports opcionales con fallback (evitar cascada de errors)
try:
    from .panel import (  # noqa: F401
        build_historical_bloomberg,
        build_metric_timeseries,
        compute_growth_stats,
    )
except Exception as _e:
    import sys as _sys
    print(f"[historical] panel no disponible: "
          f"{type(_e).__name__}: {_e}", file=_sys.stderr)

try:
    from .financial_panels import (  # noqa: F401
        build_income_panel,
        build_bs_panel,
        build_cf_panel,
        format_panel,
    )
except Exception as _e:
    import sys as _sys
    print(f"[historical] financial_panels no disponible: "
          f"{type(_e).__name__}: {_e}", file=_sys.stderr)

try:
    from .bloomberg_layouts import (  # noqa: F401
        build_income_adjusted_panel,
        build_bs_standardized_panel,
        build_cf_standardized_panel,
    )
except Exception as _e:
    import sys as _sys
    print(f"[historical] bloomberg_layouts no disponible: "
          f"{type(_e).__name__}: {_e}", file=_sys.stderr)
