from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..models import Confidence
from ..utils import get_json
from .base import BaseDataProvider, ProviderResult


class YFinanceProvider(BaseDataProvider):
    name = "yfinance"

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }

    def enabled(self) -> bool:
        return True

    def _load_quote(self, ticker: str) -> Dict[str, Any]:
        if ticker not in self._cache:
            rows: List[Dict[str, Any]] = []
            for quote_url in (
                "https://query1.finance.yahoo.com/v7/finance/quote",
                "https://query2.finance.yahoo.com/v7/finance/quote",
            ):
                payload = get_json(quote_url, params={"symbols": ticker}, headers=self._headers)
                candidate_rows = payload.get("quoteResponse", {}).get("result", []) if isinstance(payload, dict) else []
                if candidate_rows:
                    rows = [row for row in candidate_rows if isinstance(row, dict)]
                    break
            self._cache[ticker] = rows[0] if rows else {}
        return self._cache[ticker]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        row = self._load_quote(ticker)
        if not row:
            return None

        key_map = {
            "price": "regularMarketPrice",
            "market_cap": "marketCap",
            "shares_outstanding": "sharesOutstanding",
            "pb_mrq": "priceToBook",
            "dividend_yield_ttm": "trailingAnnualDividendYield",
        }

        ts = row.get("regularMarketTime")
        as_of = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d") if ts else None

        if field_name == "price_date":
            if not as_of:
                return None
            return ProviderResult(
                field_name,
                as_of,
                self.name,
                "https://query1.finance.yahoo.com/v7/finance/quote",
                as_of,
                confidence=Confidence.MEDIUM,
            )

        mapped = key_map.get(field_name)
        if not mapped:
            return None
        value = row.get(mapped)
        if value is None:
            return None
        return ProviderResult(
            field_name=field_name,
            value=value,
            source=self.name,
            source_url="https://query1.finance.yahoo.com/v7/finance/quote",
            as_of=as_of,
            currency=row.get("currency"),
            confidence=Confidence.MEDIUM,
        )
