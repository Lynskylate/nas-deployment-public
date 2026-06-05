from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class FinnhubProvider(BaseDataProvider):
    name = "finnhub"

    def __init__(self) -> None:
        self.api_key = os.getenv("FINNHUB_API_KEY")
        self._quote_cache: Dict[str, Dict[str, Any]] = {}
        self._metric_cache: Dict[str, Dict[str, Any]] = {}
        self._profile_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return bool(self.api_key)

    def _quote(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._quote_cache:
            self._quote_cache[ticker] = get_json(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": ticker, "token": self.api_key},
            )
        return self._quote_cache[ticker]

    def _metrics(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._metric_cache:
            payload = get_json(
                "https://finnhub.io/api/v1/stock/metric",
                params={"symbol": ticker, "metric": "all", "token": self.api_key},
            )
            self._metric_cache[ticker] = payload.get("metric", {}) if isinstance(payload, dict) else {}
        return self._metric_cache[ticker]

    def _profile(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._profile_cache:
            self._profile_cache[ticker] = get_json(
                "https://finnhub.io/api/v1/stock/profile2",
                params={"symbol": ticker, "token": self.api_key},
            )
        return self._profile_cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None

        if field_name in {"price", "price_date"}:
            quote = self._quote(ticker)
            ts = quote.get("t")
            as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else None
            if field_name == "price_date":
                if not as_of:
                    return None
                return ProviderResult(field_name, as_of, self.name, "https://finnhub.io/docs/api/quote", as_of)
            price = to_float(quote.get("c"))
            if price is None:
                return None
            return ProviderResult(field_name, price, self.name, "https://finnhub.io/docs/api/quote", as_of)

        if field_name in {"market_cap", "shares_outstanding"}:
            profile = self._profile(ticker)
            key = "marketCapitalization" if field_name == "market_cap" else "shareOutstanding"
            value = to_float(profile.get(key))
            if value is None:
                return None
            if field_name == "market_cap":
                value *= 1_000_000.0
            return ProviderResult(field_name, value, self.name, "https://finnhub.io/docs/api/company-profile2")

        metric_keys = {
            "pb_mrq": ["pbAnnual", "pbQuarterly"],
            "dividend_yield_ttm": ["dividendYieldIndicatedAnnual", "dividendYield5Y"],
        }.get(field_name)
        if not metric_keys:
            return None

        metrics = self._metrics(ticker)
        for key in metric_keys:
            value = to_float(metrics.get(key))
            if value is None:
                continue
            if field_name == "dividend_yield_ttm" and value > 1:
                value /= 100.0
            return ProviderResult(field_name, value, self.name, "https://finnhub.io/docs/api/company-basic-financials")
        return None
