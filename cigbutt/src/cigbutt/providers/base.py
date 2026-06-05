from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Protocol

from ..models import Confidence, SourceAttribution


@dataclass
class ProviderResult:
    field_name: str
    value: float | str | int | None
    source: str
    source_url: Optional[str] = None
    as_of: Optional[str] = None
    currency: Optional[str] = None
    confidence: Confidence = Confidence.MEDIUM


class DataProvider(Protocol):
    name: str

    def enabled(self) -> bool:
        ...

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        ...


@dataclass
class FetchOutcome:
    values: Dict[str, object]
    attributions: List[SourceAttribution]
    missing_fields: List[str]


class BaseDataProvider:
    name: str = "base"

    def enabled(self) -> bool:
        raise NotImplementedError

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        raise NotImplementedError
