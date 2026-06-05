from __future__ import annotations

from typing import Optional

from ..models import Confidence
from ..utils import to_float
from .base import BaseDataProvider, ProviderResult


class AkShareProvider(BaseDataProvider):
    name = "akshare"

    def __init__(self) -> None:
        try:
            import akshare as ak  # type: ignore

            self._ak = ak
            self._enabled = True
        except Exception:
            self._ak = None
            self._enabled = False

    def enabled(self) -> bool:
        return self._enabled

    def fetch_field(self, ticker: str, market: str, field_name: str) -> Optional[ProviderResult]:
        if not self.enabled():
            return None
        if market.upper() not in {"CN", "A", "ASHARE", "SZ", "SH"}:
            return None
        if field_name not in {"price", "pb_mrq", "market_cap"}:
            return None

        code = ticker.split(".")[0]
        try:
            frame = self._ak.stock_zh_a_spot_em()
        except Exception:
            return None
        if frame is None or frame.empty:
            return None
        row = frame[frame["代码"].astype(str) == str(code)]
        if row.empty:
            return None
        record = row.iloc[0]
        key_map = {"price": "最新价", "pb_mrq": "市净率", "market_cap": "总市值"}
        value = to_float(record.get(key_map[field_name]))
        if value is None:
            return None
        return ProviderResult(field_name, value, self.name, "https://akshare.akfamily.xyz/", confidence=Confidence.LOW)
