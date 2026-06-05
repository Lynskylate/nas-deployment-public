from __future__ import annotations

import re
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from ..models import Confidence
from ..utils import to_float
from .base import BaseDataProvider, ProviderResult


class SinaFinanceProvider(BaseDataProvider):
    name = "sinafinance"
    QUOTE_URL = "https://hq.sinajs.cn/list="

    def __init__(self) -> None:
        self._cache: Dict[str, List[str]] = {}
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://finance.sina.com.cn",
        }

    def enabled(self) -> bool:
        return True

    @staticmethod
    def _normalized_market(market: str, ticker: str) -> str:
        market_code = market.upper().strip()
        if market_code in {"NASDAQ", "NYSE", "AMEX", "US"}:
            return "US"
        if market_code in {"HK", "HKG"}:
            return "HK"
        if market_code in {"CN", "A", "ASHARE", "SH", "SZ", "BJ", "SS"}:
            return "CN"

        if "." in ticker:
            suffix = ticker.split(".", 1)[1].upper()
            if suffix in {"US", "NASDAQ", "NYSE", "AMEX"}:
                return "US"
            if suffix in {"HK"}:
                return "HK"
            if suffix in {"SH", "SZ", "BJ", "SS"}:
                return "CN"
        return market_code

    @staticmethod
    def _to_sina_symbol(ticker: str, market: str) -> str:
        market_code = SinaFinanceProvider._normalized_market(market, ticker)
        value = str(ticker or "").strip()
        if not value:
            return ""

        if market_code == "US":
            if ":" in value:
                value = value.split(":", 1)[1]
            if "." in value:
                value = value.split(".", 1)[0]
            value = value.replace("-", "_").lower()
            return f"gb_{value}" if value else ""

        if market_code == "HK":
            code = value.split(".", 1)[0]
            code = re.sub(r"\D", "", code).zfill(5)
            return f"hk{code}" if code else ""

        code = value
        suffix = ""
        if "." in value:
            code, suffix = value.split(".", 1)
            suffix = suffix.upper()
        code = re.sub(r"\D", "", code).zfill(6)
        if not code:
            return ""

        if suffix == "SS":
            suffix = "SH"
        if suffix in {"SH", "SZ", "BJ"}:
            return f"{suffix.lower()}{code}"
        if code.startswith(("5", "6", "9")):
            return f"sh{code}"
        if code.startswith(("4", "8")):
            return f"bj{code}"
        return f"sz{code}"

    def _fetch_row(self, ticker: str, market: str) -> List[str]:
        symbol = self._to_sina_symbol(ticker, market)
        if not symbol:
            return []
        if symbol in self._cache:
            return self._cache[symbol]

        request = urllib.request.Request(f"{self.QUOTE_URL}{symbol}", headers=self._headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = response.read()
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout):
            self._cache[symbol] = []
            return []

        text = raw.decode("gbk", errors="ignore")
        if "\"" not in text:
            self._cache[symbol] = []
            return []
        content = text.split("\"", 2)[1]
        if not content:
            self._cache[symbol] = []
            return []
        values = [item.strip() for item in content.split(",")]
        self._cache[symbol] = values
        return values

    @staticmethod
    def _parse_date_text(value: str) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        if " " in text:
            text = text.split(" ", 1)[0]
        text = text.replace("/", "-")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            return text
        return None

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        values = self._fetch_row(ticker, market)
        if not values:
            return None

        market_code = self._normalized_market(market, ticker)
        as_of: Optional[str] = None
        currency = {"US": "USD", "HK": "HKD", "CN": "CNY"}.get(market_code)

        if market_code == "CN":
            if field_name == "price":
                value = to_float(values[3] if len(values) > 3 else None)
            elif field_name == "price_date":
                as_of = self._parse_date_text(values[30] if len(values) > 30 else "")
                value = as_of
            else:
                return None
            as_of = as_of or self._parse_date_text(values[30] if len(values) > 30 else "")

        elif market_code == "HK":
            if field_name == "price":
                value = to_float(values[6] if len(values) > 6 else None)
            elif field_name == "price_date":
                as_of = self._parse_date_text(values[17] if len(values) > 17 else "")
                value = as_of
            else:
                return None
            as_of = as_of or self._parse_date_text(values[17] if len(values) > 17 else "")

        else:
            if field_name == "price":
                value = to_float(values[1] if len(values) > 1 else None)
            elif field_name == "price_date":
                as_of = self._parse_date_text(values[3] if len(values) > 3 else "")
                value = as_of
            elif field_name == "market_cap":
                value = to_float(values[12] if len(values) > 12 else None)
            elif field_name == "shares_outstanding":
                value = to_float(values[30] if len(values) > 30 else None)
            else:
                return None
            as_of = as_of or self._parse_date_text(values[3] if len(values) > 3 else "")

        if value is None:
            return None

        return ProviderResult(
            field_name=field_name,
            value=value,
            source=self.name,
            source_url=self.QUOTE_URL,
            as_of=as_of,
            currency=currency,
            confidence=Confidence.LOW,
        )
