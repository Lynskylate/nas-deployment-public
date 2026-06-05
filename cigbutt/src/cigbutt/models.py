from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Decision(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    VETO = "VETO"


class WarningClass(str, Enum):
    DATA = "WARNING-Data"
    RISK = "WARNING-Risk"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


@dataclass
class SourceAttribution:
    field_name: str
    value: Any
    source: str
    source_url: Optional[str] = None
    as_of: Optional[str] = None
    currency: Optional[str] = None
    confidence: Confidence = Confidence.MEDIUM
    fallback_chain: List[str] = field(default_factory=list)


@dataclass
class FinancialPeriod:
    period_label: str
    period_end: str
    accounting_standard: str
    currency: str
    is_interim: bool
    metrics: Dict[str, float]

    def metric(self, key: str) -> Optional[float]:
        value = self.metrics.get(key)
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None


@dataclass
class MarketSnapshot:
    ticker: str
    market: str
    price: Optional[float] = None
    price_date: Optional[str] = None
    market_cap: Optional[float] = None
    shares_outstanding: Optional[float] = None
    pb_mrq: Optional[float] = None
    dividend_yield_ttm: Optional[float] = None


@dataclass
class OwnershipProfile:
    largest_shareholder_ratio: Optional[float] = None
    ultimate_controller: Optional[str] = None
    controller_level: Optional[str] = None
    controller_ratio: Optional[float] = None


@dataclass
class PillarMetrics:
    cash_pool: Optional[float] = None
    interest_bearing_debt: Optional[float] = None
    total_liabilities: Optional[float] = None
    t0_nav: Optional[float] = None
    t1_nav: Optional[float] = None
    t2_nav: Optional[float] = None
    t_level: Optional[str] = None
    fcf: Optional[float] = None
    burn_rate: Optional[float] = None
    fcf_conversion: Optional[float] = None
    ocf_three_year_positive: bool = False
    pillar_two_pass_count: int = 0
    pillar_two_pass: bool = False
    missing: List[str] = field(default_factory=list)


@dataclass
class SubtypeAssessment:
    subtype: str = "UNCLASSIFIED"
    rationale: List[str] = field(default_factory=list)
    mixed_labels: List[str] = field(default_factory=list)
    b_discount_rate: Optional[float] = None
    c_probability: Optional[float] = None


@dataclass
class FactCheckItem:
    number: int
    title: str
    decision: Decision
    detail: str
    warning_class: Optional[WarningClass] = None


@dataclass
class FactCheckResult:
    items: List[FactCheckItem]
    warning_data_count: int
    warning_risk_count: int
    veto_count: int
    bonus_points: int
    base_rating: str
    final_rating: str


@dataclass
class StrategySuggestion:
    entry_threshold: Optional[float] = None
    position_limit: Optional[float] = None
    stop_loss_hard: float = -0.25
    conservative_return: Optional[float] = None
    base_return: Optional[float] = None
    optimistic_return: Optional[float] = None
    irr_3y: Optional[float] = None
    notes: List[str] = field(default_factory=list)


@dataclass
class QualitativeAssessment:
    business_model: str = ""
    cyclicality: str = ""
    pricing_power: str = ""
    moat: str = ""
    governance_score: Optional[float] = None
    governance_notes: List[str] = field(default_factory=list)


@dataclass
class DividendNormalization:
    latest: Optional[float]
    previous: Optional[float]
    normalized_base: Optional[float]
    qoq_change: Optional[float]
    vs_base_change: Optional[float]
    classification: str
    note: str


@dataclass
class DebugEvent:
    timestamp: str
    step: str
    message: str
    payload: Dict[str, Any] = field(default_factory=dict)
