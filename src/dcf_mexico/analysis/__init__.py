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

__all__ = [
    "compute_all_ratios", "RatioInfo", "RATIO_CATEGORIES",
    "InputSuggestion", "compute_all_input_suggestions",
    "compute_sales_to_capital", "compute_revenue_growth",
    "compute_op_margin", "compute_effective_tax_rate",
    "compute_probability_of_failure",
]
