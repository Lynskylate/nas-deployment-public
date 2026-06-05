from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from ..models import Confidence
from .base import BaseDataProvider, ProviderResult


class OpenFIGIProvider(BaseDataProvider):
    name = "openfigi"

    def __init__(self) -> None:
        self.api_key = os.getenv("OPENFIGI_API_KEY")

    def enabled(self) -> bool:
        return bool(self.api_key)

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled() or field_name != "figi":
            return None

        payload = [{"idType": "TICKER", "idValue": ticker.split(".")[0], "exchCode": market.upper()}]
        request = urllib.request.Request(
            url="https://api.openfigi.com/v3/mapping",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "X-OPENFIGI-APIKEY": self.api_key},
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            return None

        if not isinstance(raw, list) or not raw:
            return None
        rows = raw[0].get("data", [])
        if not rows:
            return None
        figi = rows[0].get("figi")
        if not figi:
            return None
        return ProviderResult(
            field_name,
            figi,
            self.name,
            "https://www.openfigi.com/api/documentation",
            confidence=Confidence.HIGH,
        )
