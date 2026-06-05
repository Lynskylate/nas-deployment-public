from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class FMPProvider(BaseDataProvider):
    name = "fmp"

    def __init__(self) -> None:
        self.api_key = os.getenv("FMP_API_KEY")
        self._quote_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _quote(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._quote_cache:
            payload = get_json(
                f"https://financialmodelingprep.com/api/v3/quote/{ticker}",
                params={"apikey": self.api_key},
            )
            self._quote_cache[ticker] = payload[0] if isinstance(payload, list) and payload else {}
        return self._quote_cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None
        row = self._quote(ticker)
        if not row:
            return None

        key_map = {
            "price": "price",
            "market_cap": "marketCap",
            "shares_outstanding": "sharesOutstanding",
            "pb_mrq": "priceToBookRatio",
            "dividend_yield_ttm": "dividendYield",
            "price_date": "timestamp",
        }
        source_key = key_map.get(field_name)
        if not source_key:
            return None
        raw = row.get(source_key)
        if raw is None:
            return None

        if field_name == "price_date":
            return ProviderResult(field_name, str(raw), self.name, "https://site.financialmodelingprep.com/developer/docs")

        value = to_float(raw)
        if value is None:
            return None
        if field_name == "dividend_yield_ttm" and value > 1:
            value /= 100.0
        return ProviderResult(field_name, value, self.name, "https://site.financialmodelingprep.com/developer/docs")
