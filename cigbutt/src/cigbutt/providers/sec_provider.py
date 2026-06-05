from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..models import Confidence
from ..utils import get_json, to_float
from .base import BaseDataProvider, ProviderResult


class SECProvider(BaseDataProvider):
    name = "sec_edgar"

    def __init__(self) -> None:
        self.user_agent = os.getenv("SEC_USER_AGENT") or "cigbutt-single/1.0"
        self._ticker_map: Optional[Dict[str, str]] = None
        self._facts_cache: Dict[str, Dict[str, Any]] = {}

    def enabled(self) -> bool:
        return True

    def _headers(self) -> Dict[str, str]:
        return {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}

    def _map(self) -> Dict[str, str]:
        if self._ticker_map is not None:
            return self._ticker_map
        payload = get_json("https://www.sec.gov/files/company_tickers.json", headers=self._headers())
        mapping: Dict[str, str] = {}
        if isinstance(payload, dict):
            for row in payload.values():
                ticker = str(row.get("ticker", "")).upper()
                cik = str(row.get("cik_str", "")).strip()
                if ticker and cik:
                    mapping[ticker] = cik.zfill(10)
        self._ticker_map = mapping
        return mapping

    def _facts(self, ticker: str) -> Dict[str, Any]:
        norm = ticker.upper().split(".")[0]
        if norm not in self._facts_cache:
            cik = self._map().get(norm)
            if not cik:
                self._facts_cache[norm] = {}
            else:
                self._facts_cache[norm] = get_json(
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                    headers=self._headers(),
                )
        return self._facts_cache[norm]

    @staticmethod
    def _latest_unit_value(units: Dict[str, Any]) -> Optional[float]:
        latest = None
        latest_end = ""
        for rows in units.values():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                value = to_float(row.get("val"))
                end_date = str(row.get("end", ""))
                if value is None:
                    continue
                if end_date >= latest_end:
                    latest = value
                    latest_end = end_date
        return latest

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if market.upper() not in {"US", "NASDAQ", "NYSE"}:
            return None
        if field_name != "shares_outstanding":
            return None

        facts = self._facts(ticker)
        if not facts:
            return None

        dei_units = (
            facts.get("facts", {})
            .get("dei", {})
            .get("EntityCommonStockSharesOutstanding", {})
            .get("units", {})
        )
        value = self._latest_unit_value(dei_units)
        if value is None:
            us_units = (
                facts.get("facts", {})
                .get("us-gaap", {})
                .get("CommonStockSharesOutstanding", {})
                .get("units", {})
            )
            value = self._latest_unit_value(us_units)
        if value is None:
            return None
        return ProviderResult(
            field_name,
            value,
            self.name,
            "https://data.sec.gov/api/xbrl/companyfacts/",
            confidence=Confidence.HIGH,
        )
