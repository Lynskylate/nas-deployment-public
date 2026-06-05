from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class EODHDProvider(BaseDataProvider):
    name = "eodhd"

    def __init__(self) -> None:
        self.api_key = os.getenv("EODHD_API_KEY")
        self._rt_cache: Dict[str, Dict[str, Any]] = {}
        self._fund_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _real_time(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._rt_cache:
            self._rt_cache[ticker] = get_json(
                f"https://eodhistoricaldata.com/api/real-time/{ticker}",
                params={"api_token": self.api_key, "fmt": "json"},
            )
        return self._rt_cache[ticker]

    def _fund(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._fund_cache:
            self._fund_cache[ticker] = get_json(
                f"https://eodhistoricaldata.com/api/fundamentals/{ticker}",
                params={"api_token": self.api_key, "fmt": "json"},
            )
        return self._fund_cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None

        if field_name in {"price", "price_date"}:
            row = self._real_time(ticker)
            ts = row.get("timestamp")
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else None
            if field_name == "price_date":
                if not as_of:
                    return None
                return ProviderResult(field_name, as_of, self.name, "https://eodhistoricaldata.com/financial-apis/")
            value = to_float(row.get("close"))
            if value is None:
                return None
            return ProviderResult(field_name, value, self.name, "https://eodhistoricaldata.com/financial-apis/", as_of)

        fund = self._fund(ticker)
        highlights = fund.get("Highlights", {}) if isinstance(fund, dict) else {}
        valuation = fund.get("Valuation", {}) if isinstance(fund, dict) else {}
        candidates = {
            "market_cap": [highlights.get("MarketCapitalization")],
            "shares_outstanding": [highlights.get("SharesOutstanding")],
            "pb_mrq": [valuation.get("PriceBookMRQ"), highlights.get("PriceBookMRQ")],
            "dividend_yield_ttm": [highlights.get("DividendYield")],
        }.get(field_name)
        if not candidates:
            return None

        for candidate in candidates:
            value = to_float(candidate)
            if value is None:
                continue
            if field_name == "dividend_yield_ttm" and value > 1:
                value /= 100.0
            return ProviderResult(field_name, value, self.name, "https://eodhistoricaldata.com/financial-apis/")
        return None
