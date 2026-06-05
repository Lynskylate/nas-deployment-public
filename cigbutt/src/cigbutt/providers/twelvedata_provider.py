from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class TwelveDataProvider(BaseDataProvider):
    name = "twelve_data"

    def __init__(self) -> None:
        self.api_key = os.getenv("TWELVE_DATA_API_KEY")
        self._quote_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _quote(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._quote_cache:
            self._quote_cache[ticker] = get_json(
                "https://api.twelvedata.com/quote",
                params={"symbol": ticker, "apikey": self.api_key},
            )
        return self._quote_cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None
        row = self._quote(ticker)
        if not row or row.get("status") == "error":
            return None

        key_map = {
            "price": "close",
            "market_cap": "market_cap",
            "shares_outstanding": "shares",
            "dividend_yield_ttm": "dividend_yield",
            "pb_mrq": "pb",
        }
        source_key = key_map.get(field_name)
        if not source_key:
            return None
        value = to_float(row.get(source_key))
        if value is None:
            return None
        if field_name == "dividend_yield_ttm" and value > 1:
            value /= 100.0
        return ProviderResult(field_name, value, self.name, "https://twelvedata.com/docs", row.get("datetime"))
