from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Optional

from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class PolygonProvider(BaseDataProvider):
    name = "polygon"

    def __init__(self) -> None:
        self.api_key = os.getenv("POLYGON_API_KEY")
        self._prev_cache: Dict[str, Dict[str, Any]] = {}
        self._ref_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _prev(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._prev_cache:
            self._prev_cache[ticker] = get_json(
                f"https://api.polygon.io/v2/aggs/ticker/{ticker}/prev",
                params={"adjusted": "true", "apiKey": self.api_key},
            )
        return self._prev_cache[ticker]

    def _ref(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._ref_cache:
            payload = get_json(
                f"https://api.polygon.io/v3/reference/tickers/{ticker}",
                params={"apiKey": self.api_key},
            )
            self._ref_cache[ticker] = payload.get("results", {}) if isinstance(payload, dict) else {}
        return self._ref_cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None

        if field_name in {"price", "price_date"}:
            payload = self._prev(ticker)
            rows = payload.get("results", []) if isinstance(payload, dict) else []
            if not rows:
                return None
            row = rows[0]
            timestamp = row.get("t")
            as_of = datetime.utcfromtimestamp(int(timestamp) / 1000).strftime("%Y-%m-%d") if timestamp else None
            if field_name == "price_date":
                if not as_of:
                    return None
                return ProviderResult(field_name, as_of, self.name, "https://polygon.io/docs")
            value = to_float(row.get("c"))
            if value is None:
                return None
            return ProviderResult(field_name, value, self.name, "https://polygon.io/docs", as_of)

        ref = self._ref(ticker)
        key_map = {
            "market_cap": "market_cap",
            "shares_outstanding": "weighted_shares_outstanding",
        }
        source_key = key_map.get(field_name)
        if not source_key:
            return None
        value = to_float(ref.get(source_key))
        if value is None and field_name == "shares_outstanding":
            value = to_float(ref.get("share_class_shares_outstanding"))
        if value is None:
            return None
        return ProviderResult(field_name, value, self.name, "https://polygon.io/docs")
