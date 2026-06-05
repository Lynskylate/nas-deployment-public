from cigbutt.markets.normalize import normalize_provider_ticker


def test_normalize_provider_ticker_hk() -> None:
    assert normalize_provider_ticker("0005.HK", "HK") == "0005.HK"


def test_normalize_provider_ticker_cn() -> None:
    assert normalize_provider_ticker("600519.SH", "CN") == "600519.SS"


def test_normalize_provider_ticker_us() -> None:
    assert normalize_provider_ticker("AAPL.US", "US") == "AAPL"
