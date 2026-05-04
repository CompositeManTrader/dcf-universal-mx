"""Analisis financiero: ratios, margenes, multiplos, decomposiciones, auto-inputs DCF."""
from .ratios import compute_all_ratios, RatioInfo, RATIO_CATEGORIES
from .dcf_inputs_auto import (
    InputSuggestion,
    compute_all_input_suggestions,
    compute_sales_to_capital,
    compute_revenue_growth,
    compute_op_margin,
    compute_effective_tax_rate,
    compute_probability_of_failure,
)
from .sector_benchmarks import (
    SectorBenchmark,
    SECTOR_DATA,
    TICKER_TO_SECTOR,
    get_sector,
    list_sectors,
    get_sector_by_id,
)
from .dcf_input_validator import (
    InputValidation,
    QualityScore,
    ScenarioOutput,
    ScenarioSet,
    validate_all_inputs,
    generate_scenarios,
)
from .vertical_horizontal import (
    FinancialChange,
    Significance,
    Direction,
    vertical_income,
    vertical_balance,
    vertical_cashflow,
    horizontal_income,
    horizontal_balance,
    horizontal_cashflow,
    detect_changes,
    categorize_changes,
    changes_to_table,
)

__all__ = [
    "compute_all_ratios", "RatioInfo", "RATIO_CATEGORIES",
    "InputSuggestion", "compute_all_input_suggestions",
    "compute_sales_to_capital", "compute_revenue_growth",
    "compute_op_margin", "compute_effective_tax_rate",
    "compute_probability_of_failure",
    "SectorBenchmark", "SECTOR_DATA", "TICKER_TO_SECTOR",
    "get_sector", "list_sectors", "get_sector_by_id",
    "InputValidation", "QualityScore",
    "ScenarioOutput", "ScenarioSet",
    "validate_all_inputs", "generate_scenarios",
    # Vertical & Horizontal
    "FinancialChange", "Significance", "Direction",
    "vertical_income", "vertical_balance", "vertical_cashflow",
    "horizontal_income", "horizontal_balance", "horizontal_cashflow",
    "detect_changes", "categorize_changes", "changes_to_table",
]
