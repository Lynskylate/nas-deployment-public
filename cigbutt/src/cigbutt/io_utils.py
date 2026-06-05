from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import (
    DividendNormalization,
    FactCheckResult,
    FinancialPeriod,
    MarketSnapshot,
    PillarMetrics,
    QualitativeAssessment,
    SourceAttribution,
    StrategySuggestion,
    SubtypeAssessment,
    WarningClass,
)
from .utils import dataclass_to_dict


def merge_market_fallbacks(values: Dict[str, Any], supplemental: Dict[str, Any], keys: Iterable[str]) -> Dict[str, Any]:
    merged = dict(values)
    for key in keys:
        if merged.get(key) is None and supplemental.get(key) is not None:
            merged[key] = supplemental.get(key)
    return merged


def write_csv_row(path: str, row: Dict[str, Any]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(row.keys()))
        writer.writeheader()
        writer.writerow(row)


def write_csv_rows(path: str, rows: List[Dict[str, Any]], preferred_headers: Optional[List[str]] = None) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers: List[str] = []
    if preferred_headers:
        headers.extend(preferred_headers)
    for row in rows:
        for key in row.keys():
            if key not in headers:
                headers.append(key)

    if not headers:
        headers = preferred_headers or ["message"]
        rows = [{"message": "no_rows"}]

    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_csv_row(
    ticker: str,
    market: str,
    analysis_date: str,
    latest_period: FinancialPeriod,
    previous_period: FinancialPeriod,
    market_snapshot: MarketSnapshot,
    qualitative: QualitativeAssessment,
    latest_metrics: PillarMetrics,
    previous_metrics: PillarMetrics,
    metric_comparison: Dict[str, Dict[str, Optional[float]]],
    subtype: SubtypeAssessment,
    fact_check: FactCheckResult,
    strategy: StrategySuggestion,
    dividend_norm: DividendNormalization,
    assumptions: List[str],
    attributions: List[SourceAttribution],
) -> Dict[str, Any]:
    warning_data_items = [f"#{item.number}:{item.title}" for item in fact_check.items if item.warning_class == WarningClass.DATA]
    warning_risk_items = [f"#{item.number}:{item.title}" for item in fact_check.items if item.warning_class == WarningClass.RISK]
    veto_items = [f"#{item.number}:{item.title}" for item in fact_check.items if item.decision.value == "VETO"]

    row: Dict[str, Any] = {
        "analysis_date": analysis_date,
        "ticker": ticker,
        "market": market,
        "latest_period": latest_period.period_label,
        "latest_period_end": latest_period.period_end,
        "previous_period": previous_period.period_label,
        "previous_period_end": previous_period.period_end,
        "accounting_standard": latest_period.accounting_standard,
        "price": market_snapshot.price,
        "price_date": market_snapshot.price_date,
        "market_cap": market_snapshot.market_cap,
        "shares_outstanding": market_snapshot.shares_outstanding,
        "pb_mrq": market_snapshot.pb_mrq,
        "dividend_yield_ttm": market_snapshot.dividend_yield_ttm,
        "t_level": latest_metrics.t_level,
        "t0_nav_latest": latest_metrics.t0_nav,
        "t1_nav_latest": latest_metrics.t1_nav,
        "t2_nav_latest": latest_metrics.t2_nav,
        "t0_nav_prev": previous_metrics.t0_nav,
        "t1_nav_prev": previous_metrics.t1_nav,
        "t2_nav_prev": previous_metrics.t2_nav,
        "fcf_latest": latest_metrics.fcf,
        "burn_rate_latest": latest_metrics.burn_rate,
        "fcf_conversion_latest": latest_metrics.fcf_conversion,
        "pillar_two_pass_count": latest_metrics.pillar_two_pass_count,
        "pillar_two_pass": latest_metrics.pillar_two_pass,
        "subtype": subtype.subtype,
        "mixed_labels": ";".join(subtype.mixed_labels),
        "subtype_rationale": " | ".join(subtype.rationale),
        "factcheck_base_rating": fact_check.base_rating,
        "factcheck_final_rating": fact_check.final_rating,
        "warning_data_count": fact_check.warning_data_count,
        "warning_risk_count": fact_check.warning_risk_count,
        "veto_count": fact_check.veto_count,
        "bonus_points": fact_check.bonus_points,
        "warning_data_items": "|".join(warning_data_items),
        "warning_risk_items": "|".join(warning_risk_items),
        "veto_items": "|".join(veto_items),
        "entry_threshold": strategy.entry_threshold,
        "position_limit": strategy.position_limit,
        "stop_loss_hard": strategy.stop_loss_hard,
        "return_conservative": strategy.conservative_return,
        "return_base": strategy.base_return,
        "return_optimistic": strategy.optimistic_return,
        "irr_3y": strategy.irr_3y,
        "strategy_notes": " | ".join(strategy.notes),
        "dividend_latest": dividend_norm.latest,
        "dividend_previous": dividend_norm.previous,
        "dividend_normalized_base": dividend_norm.normalized_base,
        "dividend_qoq_change": dividend_norm.qoq_change,
        "dividend_vs_base_change": dividend_norm.vs_base_change,
        "dividend_classification": dividend_norm.classification,
        "dividend_note": dividend_norm.note,
        "business_model": qualitative.business_model,
        "cyclicality": qualitative.cyclicality,
        "pricing_power": qualitative.pricing_power,
        "moat": qualitative.moat,
        "governance_score": qualitative.governance_score,
        "governance_notes": " | ".join(qualitative.governance_notes),
        "metric_delta_t0_nav": metric_comparison["t0_nav"]["delta"],
        "metric_delta_t1_nav": metric_comparison["t1_nav"]["delta"],
        "metric_delta_t2_nav": metric_comparison["t2_nav"]["delta"],
        "metric_delta_fcf": metric_comparison["fcf"]["delta"],
        "metric_delta_burn_rate": metric_comparison["burn_rate"]["delta"],
        "metric_delta_fcf_conversion": metric_comparison["fcf_conversion"]["delta"],
        "assumptions": " | ".join(assumptions),
        "data_sources_json": json.dumps([dataclass_to_dict(item) for item in attributions], ensure_ascii=False),
    }
    return row
