from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class AlphaVantageProvider(BaseDataProvider):
    name = "alpha_vantage"

    def __init__(self) -> None:
        self.api_key = os.getenv("ALPHA_VANTAGE_API_KEY")
        self._overview_cache: Dict[str, Dict[str, Any]] = {}
        self._quote_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _overview(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._overview_cache:
            self._overview_cache[ticker] = get_json(
                "https://www.alphavantage.co/query",
                params={"function": "OVERVIEW", "symbol": ticker, "apikey": self.api_key},
            )
        return self._overview_cache[ticker]

    def _quote(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._quote_cache:
            payload = get_json(
                "https://www.alphavantage.co/query",
                params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": self.api_key},
            )
            self._quote_cache[ticker] = payload.get("Global Quote", {}) if isinstance(payload, dict) else {}
        return self._quote_cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None

        if field_name == "price":
            quote = self._quote(ticker)
            value = to_float(quote.get("05. price"))
            if value is None:
                return None
            return ProviderResult(
                field_name=field_name,
                value=value,
                source=self.name,
                source_url="https://www.alphavantage.co/documentation/",
                as_of=quote.get("07. latest trading day"),
            )

        key_map = {
            "market_cap": "MarketCapitalization",
            "shares_outstanding": "SharesOutstanding",
            "pb_mrq": "PriceToBookRatio",
            "dividend_yield_ttm": "DividendYield",
        }
        source_key = key_map.get(field_name)
        if not source_key:
            return None

        overview = self._overview(ticker)
        value = to_float(overview.get(source_key))
        if value is None:
            return None
        return ProviderResult(field_name, value, self.name, "https://www.alphavantage.co/documentation/")
