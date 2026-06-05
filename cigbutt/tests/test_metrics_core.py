from cigbutt.models import FinancialPeriod, MarketSnapshot
from cigbutt.strategy.metrics import compute_pillar_metrics


def test_compute_pillar_metrics_t0() -> None:
    period = FinancialPeriod(
        period_label="FY2025",
        period_end="2025-12-31",
        accounting_standard="HKFRS",
        currency="HKD",
        is_interim=False,
        metrics={
            "cash_and_equivalents": 1000.0,
            "short_term_investments": 200.0,
            "total_liabilities": 100.0,
            "short_term_debt": 20.0,
            "long_term_debt": 10.0,
            "operating_cash_flow": 120.0,
            "capital_expenditure": 20.0,
            "net_income": 80.0,
        },
    )
    snapshot = MarketSnapshot(
        ticker="0005.HK",
        market="HK",
        price=60.0,
        market_cap=500.0,
        shares_outstanding=10.0,
    )
    result = compute_pillar_metrics(period, snapshot)
    assert result.t_level == "T0"
    assert result.t0_nav is not None and result.t0_nav > 0
    assert result.fcf == 100.0
