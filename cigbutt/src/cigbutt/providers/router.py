from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from ..models import Confidence, SourceAttribution
from .akshare_provider import AkShareProvider
from .alpha_vantage_provider import AlphaVantageProvider
from .base import FetchOutcome, ProviderResult
from .eodhd_provider import EODHDProvider
from .finnhub_provider import FinnhubProvider
from .fmp_provider import FMPProvider
from .openfigi_provider import OpenFIGIProvider
from .polygon_provider import PolygonProvider
from .sec_provider import SECProvider
from .sina_provider import SinaFinanceProvider
from .tradingview_provider import TradingViewStockScreenProvider
from .twelvedata_provider import TwelveDataProvider
from .yfinance_provider import YFinanceProvider


DEFAULT_FIELD_PRIORITY: Dict[str, List[str]] = {
    "price": [
        "sinafinance",
        "yfinance",
        "finnhub",
        "fmp",
        "twelve_data",
        "eodhd",
        "polygon",
        "akshare",
        "tradingview_stockscreen",
    ],
    "price_date": ["sinafinance", "yfinance", "finnhub", "eodhd", "polygon", "fmp", "tradingview_stockscreen"],
    "market_cap": [
        "sinafinance",
        "yfinance",
        "finnhub",
        "fmp",
        "eodhd",
        "polygon",
        "twelve_data",
        "akshare",
        "tradingview_stockscreen",
    ],
    "shares_outstanding": ["sinafinance", "yfinance", "finnhub", "fmp", "polygon", "sec_edgar"],
    "pb_mrq": ["tradingview_stockscreen", "yfinance", "finnhub", "fmp", "eodhd", "twelve_data", "akshare"],
    "dividend_yield_ttm": [
        "tradingview_stockscreen",
        "yfinance",
        "finnhub",
        "fmp",
        "alpha_vantage",
        "eodhd",
        "twelve_data",
    ],
    "figi": ["openfigi"],
}

MARKET_FIELD_PRIORITY: Dict[str, Dict[str, List[str]]] = {
    "CN": {
        "price": ["sinafinance", "akshare", "yfinance", "tradingview_stockscreen"],
        "price_date": ["sinafinance", "akshare", "yfinance", "tradingview_stockscreen"],
        "market_cap": ["akshare", "tradingview_stockscreen", "yfinance", "sinafinance"],
        "pb_mrq": ["akshare", "tradingview_stockscreen", "yfinance"],
    },
    "HK": {
        "price": ["sinafinance", "yfinance", "tradingview_stockscreen"],
        "price_date": ["sinafinance", "yfinance", "tradingview_stockscreen"],
        "market_cap": ["yfinance", "tradingview_stockscreen", "sinafinance"],
        "pb_mrq": ["tradingview_stockscreen", "yfinance"],
    },
    "US": {
        "price": ["sinafinance", "yfinance", "tradingview_stockscreen", "finnhub", "fmp"],
        "price_date": ["sinafinance", "yfinance", "tradingview_stockscreen", "finnhub"],
        "market_cap": ["sinafinance", "yfinance", "tradingview_stockscreen", "finnhub", "fmp", "eodhd", "polygon"],
        "pb_mrq": ["tradingview_stockscreen", "yfinance", "finnhub", "fmp", "eodhd"],
        "dividend_yield_ttm": ["tradingview_stockscreen", "yfinance", "finnhub", "fmp"],
        "shares_outstanding": ["sinafinance", "sec_edgar", "yfinance", "finnhub", "fmp", "polygon"],
    },
}


class ProviderRouter:
    def __init__(self) -> None:
        providers = [
            SinaFinanceProvider(),
            YFinanceProvider(),
            TradingViewStockScreenProvider(),
            AlphaVantageProvider(),
            FinnhubProvider(),
            PolygonProvider(),
            FMPProvider(),
            TwelveDataProvider(),
            EODHDProvider(),
            SECProvider(),
            OpenFIGIProvider(),
            AkShareProvider(),
        ]
        self.providers_by_name = {provider.name: provider for provider in providers}

    def probe(self) -> List[Dict[str, object]]:
        return [{"provider": name, "enabled": provider.enabled()} for name, provider in self.providers_by_name.items()]

    def _fetch_single_field(self, ticker: str, market: str, field_name: str) -> Tuple[Optional[ProviderResult], List[str]]:
        market_priority = MARKET_FIELD_PRIORITY.get(market.upper(), {}).get(field_name)
        priority = market_priority or DEFAULT_FIELD_PRIORITY.get(field_name) or list(self.providers_by_name.keys())
        chain: List[str] = []
        for provider_name in priority:
            provider = self.providers_by_name.get(provider_name)
            if not provider:
                continue
            if not provider.enabled():
                chain.append(f"{provider_name}:disabled")
                continue
            chain.append(provider_name)
            try:
                result = provider.fetch_field(ticker=ticker, market=market, field_name=field_name)
            except Exception:
                result = None
            if result is not None and result.value is not None:
                return result, chain
        return None, chain

    def fetch_fields(self, ticker: str, market: str, fields: Iterable[str]) -> FetchOutcome:
        values: Dict[str, object] = {}
        attributions: List[SourceAttribution] = []
        missing: List[str] = []

        for field_name in fields:
            result, chain = self._fetch_single_field(ticker, market, field_name)
            if result is None:
                missing.append(field_name)
                attributions.append(
                    SourceAttribution(
                        field_name=field_name,
                        value=None,
                        source="UNRESOLVED",
                        confidence=Confidence.LOW,
                        fallback_chain=chain,
                    )
                )
                continue

            values[field_name] = result.value
            attributions.append(
                SourceAttribution(
                    field_name=field_name,
                    value=result.value,
                    source=result.source,
                    source_url=result.source_url,
                    as_of=result.as_of,
                    currency=result.currency,
                    confidence=result.confidence,
                    fallback_chain=chain,
                )
            )

        return FetchOutcome(values=values, attributions=attributions, missing_fields=missing)
