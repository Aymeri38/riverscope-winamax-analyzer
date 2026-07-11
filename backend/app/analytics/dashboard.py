"""Compatibility facade for callers that organize analytics by UI page."""

from .results import (
    calculate_dashboard,
    calculate_expresso_breakdown,
    calculate_hourly_gain,
    calculate_itm,
    calculate_place_rates,
    calculate_roi,
    calculate_results_by_stack,
    filter_tournaments,
    group_results,
    max_drawdown,
)

__all__ = [
    "calculate_dashboard",
    "calculate_expresso_breakdown",
    "calculate_hourly_gain",
    "calculate_itm",
    "calculate_place_rates",
    "calculate_roi",
    "calculate_results_by_stack",
    "filter_tournaments",
    "group_results",
    "max_drawdown",
]
