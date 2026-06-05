"""Cigbutt standalone analysis library."""

from .cli import build_parser, main
from .llm import DashScopeCompatibleClient
from .models import (
    FactCheckResult,
    FinancialPeriod,
    MarketSnapshot,
    PillarMetrics,
    QualitativeAssessment,
)
from .providers import ProviderRouter
from .strategy import run_analysis, run_e2e, run_hk_scan, run_market_scan

__all__ = [
    "run_analysis",
    "run_e2e",
    "run_hk_scan",
    "run_market_scan",
    "build_parser",
    "main",
    "ProviderRouter",
    "DashScopeCompatibleClient",
    "FinancialPeriod",
    "MarketSnapshot",
    "PillarMetrics",
    "FactCheckResult",
    "QualitativeAssessment",
]
