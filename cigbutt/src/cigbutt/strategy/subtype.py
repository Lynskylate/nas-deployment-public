from __future__ import annotations

from typing import List, Optional

from ..models import PillarMetrics, StrategySuggestion, SubtypeAssessment


def market_key(market: str) -> str:
    upper = market.upper()
    if upper in {"HK", "HKEX"}:
        return "HK"
    if upper in {"CN", "A", "ASHARE", "SZ", "SH"}:
        return "CN"
    if upper in {"US", "NASDAQ", "NYSE"}:
        return "US"
    return "HK"


def assess_subtype(
    market: str,
    pillar_metrics: PillarMetrics,
    pb_mrq: Optional[float],
    dividend_yield_ttm: Optional[float],
    continuous_dividend_years: Optional[int],
    holding_value_coverage: Optional[float],
    parent_discount_rate: Optional[float],
    parent_holding_ratio: Optional[float],
    net_cash_positive: Optional[bool],
    catalyst_probability: Optional[float],
) -> SubtypeAssessment:
    floors = {"HK": 0.06, "CN": 0.04, "US": 0.05}
    floor = floors[market_key(market)]

    rationale: List[str] = []
    mixed: List[str] = []

    a_core = (
        pb_mrq is not None
        and pb_mrq <= 0.5
        and dividend_yield_ttm is not None
        and dividend_yield_ttm >= floor
        and continuous_dividend_years is not None
        and continuous_dividend_years >= 5
    )

    b_core = (
        holding_value_coverage is not None
        and holding_value_coverage >= 0.30
        and parent_discount_rate is not None
        and parent_discount_rate >= 0.30
        and parent_holding_ratio is not None
        and parent_holding_ratio >= 0.10
        and net_cash_positive is True
    )

    c_core = (
        catalyst_probability is not None
        and catalyst_probability >= 0.50
        and (pillar_metrics.t0_nav is not None or pillar_metrics.t1_nav is not None or pillar_metrics.t2_nav is not None)
    )

    subtype = "UNCLASSIFIED"
    if a_core:
        subtype = "A"
        rationale.append("A型核心条件满足")
    elif b_core:
        subtype = "B"
        rationale.append("B型核心条件满足")
    elif c_core:
        subtype = "C1/C2"
        rationale.append("C型核心条件满足")
    else:
        rationale.append("A/B/C核心条件未完全满足")

    if a_core and holding_value_coverage is not None and holding_value_coverage >= 0.50:
        mixed.append("A+B")
        rationale.append("A+B混合标签触发")
    if c_core and holding_value_coverage is not None and holding_value_coverage >= 0.50:
        mixed.append("C+B")
        rationale.append("C+B混合标签触发")

    return SubtypeAssessment(subtype=subtype, rationale=rationale, mixed_labels=mixed, b_discount_rate=parent_discount_rate, c_probability=catalyst_probability)


def build_strategy(
    current_price: Optional[float],
    current_pb: Optional[float],
    dividend_yield_ttm: Optional[float],
    pillar: PillarMetrics,
    subtype: SubtypeAssessment,
    dividend_tax_rate: float,
) -> StrategySuggestion:
    entry = None
    cap = None
    notes: List[str] = []

    if pillar.t_level == "T0" and pillar.t0_nav is not None:
        entry = pillar.t0_nav * 0.85
        cap = 0.10
    elif pillar.t_level == "T1" and pillar.t1_nav is not None:
        entry = pillar.t1_nav * 0.80
        cap = 0.08
    elif pillar.t_level == "T2" and pillar.t2_nav is not None:
        entry = pillar.t2_nav * 0.70
        cap = 0.05

    if subtype.subtype.startswith("C"):
        cap = min(cap or 0.05, 0.08)
        notes.append("事件驱动类型采用更紧仓位")

    conservative = base = optimistic = irr_3y = None
    if current_pb not in (None, 0):
        conservative = 0.60 / current_pb - 1
        base = 0.80 / current_pb - 1
        optimistic = 1.00 / current_pb - 1
        if dividend_yield_ttm is not None:
            div_after_tax = dividend_yield_ttm * (1 - dividend_tax_rate)
            total_3y = base * 0.70 + div_after_tax * 3
            irr_3y = (1 + total_3y) ** (1 / 3) - 1 if total_3y > -0.99 else None

    if entry is not None and current_price is not None:
        if current_price <= entry:
            notes.append("当前价格低于或接近阈值，可40/30/30分批建仓")
        else:
            notes.append("当前价格高于入场阈值，继续等待")

    notes.append("硬止损：-25%；C1可使用-20%")

    return StrategySuggestion(
        entry_threshold=entry,
        position_limit=cap,
        conservative_return=conservative,
        base_return=base,
        optimistic_return=optimistic,
        irr_3y=irr_3y,
        notes=notes,
    )
