from cigbutt.models import FinancialPeriod, OwnershipProfile, PillarMetrics
from cigbutt.strategy.factcheck import run_fact_check


def test_factcheck_with_empty_supplemental() -> None:
    latest = FinancialPeriod(
        period_label="FY2025",
        period_end="2025-12-31",
        accounting_standard="HKFRS",
        currency="HKD",
        is_interim=False,
        metrics={"cash_and_equivalents": 100.0, "total_assets": 500.0, "equity": 200.0},
    )
    pillar = PillarMetrics(cash_pool=100.0, total_liabilities=50.0)
    result = run_fact_check(latest, pillar, OwnershipProfile(), {})
    assert len(result.items) == 21
    assert result.warning_data_count >= 1
