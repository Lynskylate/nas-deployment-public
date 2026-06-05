from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, Dict, Optional, Tuple

from ..models import Confidence
from ..utils import to_float
from .base import BaseDataProvider, ProviderResult


class TradingViewStockScreenProvider(BaseDataProvider):
    name = "tradingview_stockscreen"

    def __init__(self) -> None:
        try:
            from tradingview_screener import Query, col  # type: ignore

            self._Query = Query
            self._col = col
            self._enabled = True
        except Exception:
            self._Query = None
            self._col = None
            self._enabled = False
        self._timeout = float(os.getenv("TRADINGVIEW_TIMEOUT_SECONDS", "8"))
        self._cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return self._enabled

    @staticmethod
    def _tradingview_ticker(ticker: str, market: str) -> str:
        market_code = market.upper().strip()
        value = str(ticker or "").strip().upper()
        if not value:
            return ""
        if ":" in value:
            return value

        code = value
        suffix = ""
        if "." in value:
            code, suffix = value.split(".", 1)
            suffix = suffix.upper()

        if market_code in {"US", "NASDAQ", "NYSE", "AMEX"} or suffix in {"US", "NASDAQ", "NYSE", "AMEX"}:
            exchange = market_code if market_code in {"NASDAQ", "NYSE", "AMEX"} else "NASDAQ"
            if suffix in {"NASDAQ", "NYSE", "AMEX"}:
                exchange = suffix
            code = code.replace("-", ".")
            return f"{exchange}:{code}"

        if market_code in {"HK", "HKG"} or suffix == "HK":
            code = re.sub(r"\D", "", code)
            if not code:
                return ""
            return f"HKEX:{str(int(code))}"

        if market_code in {"CN", "A", "ASHARE", "SH", "SZ", "BJ", "SS"} or suffix in {"SH", "SZ", "BJ", "SS"}:
            code = re.sub(r"\D", "", code).zfill(6)
            if not code:
                return ""
            if suffix in {"SH", "SS"} or (not suffix and code.startswith(("5", "6", "9"))):
                return f"SSE:{code}"
            if suffix == "BJ" or (not suffix and code.startswith(("4", "8"))):
                return f"BSE:{code}"
            return f"SZSE:{code}"

        return value

    def _fetch_row(self, ticker: str, market: str) -> Dict[str, Any]:
        key = (market.upper().strip(), ticker.upper().strip())
        if key in self._cache:
            return self._cache[key]
        if not self.enabled() or not self._Query or not self._col:
            self._cache[key] = {}
            return {}

        tv_ticker = self._tradingview_ticker(ticker, market)
        if not tv_ticker:
            self._cache[key] = {}
            return {}

        columns = [
            "name",
            "close",
            "market_cap_basic",
            "price_book_fq",
            "dividend_yield_recent",
            "currency",
        ]
        try:
            _, frame = (
                self._Query().select(*columns).set_tickers(tv_ticker).limit(3).get_scanner_data(timeout=self._timeout)
            )
        except Exception:
            self._cache[key] = {}
            return {}

        if frame is None or getattr(frame, "empty", True):
            self._cache[key] = {}
            return {}

        records = frame.to_dict(orient="records")
        selected = records[0] if records else {}
        self._cache[key] = selected if isinstance(selected, dict) else {}
        return self._cache[key]

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        row = self._fetch_row(ticker, market)
        if not row:
            return None

        key_map = {
            "price": "close",
            "market_cap": "market_cap_basic",
            "pb_mrq": "price_book_fq",
            "dividend_yield_ttm": "dividend_yield_recent",
        }
        if field_name == "price_date":
            value = date.today().isoformat() if to_float(row.get("close")) is not None else None
            if value is None:
                return None
            return ProviderResult(
                field_name=field_name,
                value=value,
                source=self.name,
                source_url="https://scanner.tradingview.com/",
                as_of=value,
                confidence=Confidence.LOW,
            )

        source_key = key_map.get(field_name)
        if not source_key:
            return None
        value = to_float(row.get(source_key))
        if value is None:
            return None
        if field_name == "dividend_yield_ttm" and value > 1:
            value /= 100.0
        return ProviderResult(
            field_name=field_name,
            value=value,
            source=self.name,
            source_url="https://scanner.tradingview.com/",
            as_of=date.today().isoformat(),
            currency=str(row.get("currency") or ""),
            confidence=Confidence.LOW,
        )
