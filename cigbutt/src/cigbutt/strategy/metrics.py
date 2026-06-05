from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..models import DividendNormalization, FinancialPeriod, MarketSnapshot, PillarMetrics


def annualize_if_interim(value: Optional[float], is_interim: bool) -> Optional[float]:
    if value is None:
        return None
    return value * 2 if is_interim else value


def compute_cash_pool(period: FinancialPeriod) -> Optional[float]:
    cash = period.metric("cash_and_equivalents")
    short_inv = period.metric("short_term_investments")
    term_dep = period.metric("term_deposits")
    if cash is None and short_inv is None and term_dep is None:
        return None
    return (cash or 0.0) + (short_inv or 0.0) + (term_dep or 0.0)


def compute_interest_debt(period: FinancialPeriod) -> Optional[float]:
    short_debt = period.metric("short_term_debt")
    long_debt = period.metric("long_term_debt")
    if short_debt is None and long_debt is None:
        return None
    return (short_debt or 0.0) + (long_debt or 0.0)


def compute_t2_assets(period: FinancialPeriod, inventory_haircut: float) -> Optional[float]:
    cash_pool = compute_cash_pool(period)
    ar = period.metric("accounts_receivable")
    inventory = period.metric("inventory")
    other_current = period.metric("other_current_assets")
    if cash_pool is None and ar is None and inventory is None and other_current is None:
        return None
    return (cash_pool or 0.0) + (ar or 0.0) * 0.85 + (inventory or 0.0) * inventory_haircut + (other_current or 0.0) * 0.5


def compute_pillar_metrics(period: FinancialPeriod, market: MarketSnapshot, inventory_haircut: float = 0.7) -> PillarMetrics:
    missing: List[str] = []

    cash_pool = compute_cash_pool(period)
    total_liabilities = period.metric("total_liabilities")
    interest_debt = compute_interest_debt(period)
    shares = market.shares_outstanding
    market_cap = market.market_cap

    if cash_pool is None:
        missing.append("cash_pool")
    if total_liabilities is None:
        missing.append("total_liabilities")
    if interest_debt is None:
        missing.append("interest_bearing_debt")
    if shares is None:
        missing.append("shares_outstanding")
    if market_cap is None:
        missing.append("market_cap")

    t0_nav = t1_nav = t2_nav = None
    t2_assets = compute_t2_assets(period, inventory_haircut)

    if shares and shares > 0 and cash_pool is not None and total_liabilities is not None:
        t0_nav = (cash_pool - total_liabilities) / shares
    if shares and shares > 0 and cash_pool is not None and interest_debt is not None:
        t1_nav = (cash_pool - interest_debt) / shares
    if shares and shares > 0 and t2_assets is not None and total_liabilities is not None:
        t2_nav = (t2_assets - total_liabilities) / shares

    t_level = "NONE"
    if market_cap is not None:
        t0_buffer = (cash_pool - total_liabilities) if cash_pool is not None and total_liabilities is not None else None
        t1_buffer = (cash_pool - interest_debt) if cash_pool is not None and interest_debt is not None else None
        t2_buffer = (t2_assets - total_liabilities) if t2_assets is not None and total_liabilities is not None else None

        if t0_buffer is not None and t0_buffer > market_cap:
            t_level = "T0"
        elif t1_buffer is not None and t1_buffer > market_cap:
            t_level = "T1"
        elif t2_buffer is not None and t2_buffer > market_cap:
            t_level = "T2"

    ocf = annualize_if_interim(period.metric("operating_cash_flow"), period.is_interim)
    capex = annualize_if_interim(period.metric("capital_expenditure"), period.is_interim)
    net_income = annualize_if_interim(period.metric("net_income"), period.is_interim)

    fcf = ocf - capex if ocf is not None and capex is not None else None
    burn_rate = None
    if shares and shares > 0 and fcf is not None:
        if t_level == "T0" and t0_nav is not None:
            cushion = t0_nav * shares
            burn_rate = fcf / cushion if cushion else None
        elif t_level == "T1" and t1_nav is not None:
            cushion = t1_nav * shares
            burn_rate = fcf / cushion if cushion else None
        elif t_level == "T2" and t2_nav is not None:
            cushion = t2_nav * shares
            burn_rate = fcf / cushion if cushion else None

    fcf_conversion = fcf / net_income if fcf is not None and net_income not in (None, 0) else None

    return PillarMetrics(
        cash_pool=cash_pool,
        interest_bearing_debt=interest_debt,
        total_liabilities=total_liabilities,
        t0_nav=t0_nav,
        t1_nav=t1_nav,
        t2_nav=t2_nav,
        t_level=t_level,
        fcf=fcf,
        burn_rate=burn_rate,
        fcf_conversion=fcf_conversion,
        missing=sorted(set(missing)),
    )


def evaluate_pillar_two(latest_metrics: PillarMetrics, recent_periods: List[FinancialPeriod]) -> Tuple[int, bool, bool]:
    cond1 = bool(latest_metrics.fcf is not None and latest_metrics.fcf > 0)
    threshold = {"T0": 0.0, "T1": 0.05, "T2": 0.10}.get(latest_metrics.t_level or "", 0.10)
    cond2 = bool(latest_metrics.burn_rate is not None and latest_metrics.burn_rate >= threshold)

    three = recent_periods[:3]
    cond3 = len(three) == 3 and all((annualize_if_interim(p.metric("operating_cash_flow"), p.is_interim) or -1) > 0 for p in three)

    count = sum([cond1, cond2, cond3])
    return count, count >= 2, cond3


def compare_metrics(latest: PillarMetrics, previous: PillarMetrics) -> Dict[str, Dict[str, Optional[float]]]:
    keys = ["t0_nav", "t1_nav", "t2_nav", "fcf", "burn_rate", "fcf_conversion"]
    out: Dict[str, Dict[str, Optional[float]]] = {}
    for key in keys:
        latest_value = getattr(latest, key)
        previous_value = getattr(previous, key)
        delta = (latest_value / previous_value - 1) if latest_value is not None and previous_value not in (None, 0) else None
        out[key] = {"latest": latest_value, "previous": previous_value, "delta": delta}
    return out


def normalize_dividend_cut(dividends: List[float]) -> DividendNormalization:
    if len(dividends) < 2:
        return DividendNormalization(None, None, None, None, None, "INSUFFICIENT_DATA", "Dividend history shorter than 2 periods.")

    latest = dividends[-1]
    previous = dividends[-2]
    base_window = dividends[-4:-1] if len(dividends) >= 4 else dividends[:-1]
    normalized_base = sum(base_window) / len(base_window) if base_window else None

    qoq_change = (latest / previous - 1) if previous else None
    vs_base_change = (latest / normalized_base - 1) if normalized_base else None

    if normalized_base is None:
        cls = "INSUFFICIENT_DATA"
        note = "No normalized base."
    elif latest < normalized_base * 0.85:
        cls = "SUBSTANTIAL_CUT"
        note = "Latest dividend below 85% normalized base."
    elif latest >= normalized_base * 0.85 and previous and latest < previous * 0.70:
        cls = "HIGH_BASE_REVERSION"
        note = "YoY cut >30% while normalized base still acceptable."
    else:
        cls = "NOT_A_CUT"
        note = "No material cut vs normalized base."

    return DividendNormalization(latest, previous, normalized_base, qoq_change, vs_base_change, cls, note)
