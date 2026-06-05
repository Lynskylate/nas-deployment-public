from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..io_utils import build_csv_row, merge_market_fallbacks, write_csv_row, write_csv_rows
from ..markets import (
    EastMoneyHKClient,
    build_dividend_continuous_years,
    build_period_from_cn_main_indicator,
    build_period_from_main_indicator,
    build_period_from_us_main_indicator,
    normalize_cn_secucode,
    normalize_hk_secucode,
    normalize_provider_ticker,
    normalize_us_secucode,
    select_latest_two_rows,
)
from ..models import MarketSnapshot, OwnershipProfile
from ..providers import ProviderRouter
from ..trace import DebugTracer
from ..utils import dataclass_to_dict, load_periods, parse_date, to_float
from .factcheck import run_fact_check
from .metrics import compare_metrics, compute_pillar_metrics, evaluate_pillar_two, normalize_dividend_cut
from .qualitative import run_qualitative_assessment
from .subtype import assess_subtype, build_strategy


REQUIRED_FIELDS = ["price", "price_date", "market_cap", "shares_outstanding", "pb_mrq", "dividend_yield_ttm"]


def run_analysis(
    ticker: str,
    market: str,
    financial_paths: List[str],
    supplemental_path: Optional[str],
    out_csv: str,
    out_debug_json: Optional[str],
    out_trace_json: Optional[str],
    inventory_haircut: float,
    dividend_tax_rate: float,
    debug: bool,
) -> Dict[str, Any]:
    tracer = DebugTracer(enabled=debug)
    tracer.log("init", "analysis start", {"ticker": ticker, "market": market})

    periods = load_periods(financial_paths)
    tracer.log(
        "step1_data_extract",
        "loaded financial periods",
        {"count": len(periods), "period_labels": [period.period_label for period in periods]},
    )
    latest = periods[0]
    previous = periods[1]

    supplemental: Dict[str, Any] = {}
    if supplemental_path:
        supplemental = json.loads(Path(supplemental_path).read_text(encoding="utf-8"))
        if not isinstance(supplemental, dict):
            raise ValueError("Supplemental JSON must be an object")
    tracer.log(
        "step1_data_extract",
        "supplemental loaded",
        {
            "provided": bool(supplemental_path),
            "keys_preview": sorted(list(supplemental.keys()))[:20],
        },
    )

    router = ProviderRouter()
    fetched = router.fetch_fields(ticker, market, REQUIRED_FIELDS)
    tracer.log(
        "step2_market_fetch",
        "market fields fetched",
        {
            "resolved_fields": sorted(list(fetched.values.keys())),
            "missing_fields": fetched.missing_fields,
        },
    )

    merged_market = merge_market_fallbacks(fetched.values, supplemental, REQUIRED_FIELDS)
    tracer.log(
        "step2_market_fetch",
        "supplemental fallback applied",
        {
            "fallback_fields": [key for key in REQUIRED_FIELDS if key not in fetched.values and key in supplemental],
        },
    )
    snapshot = MarketSnapshot(
        ticker=ticker,
        market=market,
        price=to_float(merged_market.get("price")),
        price_date=str(merged_market.get("price_date")) if merged_market.get("price_date") is not None else None,
        market_cap=to_float(merged_market.get("market_cap")),
        shares_outstanding=to_float(merged_market.get("shares_outstanding")),
        pb_mrq=to_float(merged_market.get("pb_mrq")),
        dividend_yield_ttm=to_float(merged_market.get("dividend_yield_ttm")),
    )

    ownership = OwnershipProfile(
        largest_shareholder_ratio=to_float(supplemental.get("largest_shareholder_ratio")),
        ultimate_controller=supplemental.get("ultimate_controller"),
        controller_level=supplemental.get("controller_level"),
        controller_ratio=to_float(supplemental.get("controller_ratio")),
    )

    qualitative = run_qualitative_assessment(
        ticker,
        market,
        {
            "business_summary": supplemental.get("business_summary"),
            "latest_announcements": supplemental.get("latest_announcements", []),
            "controller": supplemental.get("ultimate_controller"),
            "known_risks": supplemental.get("known_risks", []),
        },
    )
    tracer.log(
        "step3_4_qualitative",
        "qualitative block completed",
        {
            "fallback_mode": "LLM unavailable" in qualitative.business_model,
            "governance_score": qualitative.governance_score,
        },
    )

    latest_metrics = compute_pillar_metrics(latest, snapshot, inventory_haircut)
    previous_metrics = compute_pillar_metrics(previous, snapshot, inventory_haircut)
    p2_count, p2_pass, ocf_three_pos = evaluate_pillar_two(latest_metrics, periods)
    latest_metrics.pillar_two_pass_count = p2_count
    latest_metrics.pillar_two_pass = p2_pass
    latest_metrics.ocf_three_year_positive = ocf_three_pos
    tracer.log(
        "step5_pillars",
        "pillar metrics computed",
        {
            "t_level": latest_metrics.t_level,
            "pillar_two_pass_count": p2_count,
            "pillar_two_pass": p2_pass,
            "missing_metrics": latest_metrics.missing,
        },
    )

    net_cash_positive = supplemental.get("net_cash_positive")
    if net_cash_positive is None and latest_metrics.cash_pool is not None and latest_metrics.interest_bearing_debt is not None:
        net_cash_positive = latest_metrics.cash_pool > latest_metrics.interest_bearing_debt

    subtype = assess_subtype(
        market=market,
        pillar_metrics=latest_metrics,
        pb_mrq=snapshot.pb_mrq,
        dividend_yield_ttm=snapshot.dividend_yield_ttm,
        continuous_dividend_years=int(supplemental["continuous_dividend_years"]) if supplemental.get("continuous_dividend_years") is not None else None,
        holding_value_coverage=to_float(supplemental.get("holding_value_coverage")),
        parent_discount_rate=to_float(supplemental.get("parent_discount_rate")),
        parent_holding_ratio=to_float(supplemental.get("parent_holding_ratio")),
        net_cash_positive=bool(net_cash_positive) if net_cash_positive is not None else None,
        catalyst_probability=to_float(supplemental.get("catalyst_probability")),
    )
    tracer.log(
        "step6_subtype",
        "subtype assessed",
        {"subtype": subtype.subtype, "mixed_labels": subtype.mixed_labels},
    )

    fact_check = run_fact_check(latest, latest_metrics, ownership, supplemental)
    tracer.log(
        "step7_factcheck",
        "fact check completed",
        {
            "base_rating": fact_check.base_rating,
            "final_rating": fact_check.final_rating,
            "warning_data_count": fact_check.warning_data_count,
            "warning_risk_count": fact_check.warning_risk_count,
            "veto_count": fact_check.veto_count,
        },
    )
    strategy = build_strategy(snapshot.price, snapshot.pb_mrq, snapshot.dividend_yield_ttm, latest_metrics, subtype, dividend_tax_rate)
    tracer.log(
        "step8_strategy",
        "strategy generated",
        {
            "entry_threshold": strategy.entry_threshold,
            "position_limit": strategy.position_limit,
        },
    )

    dividends: List[float] = []
    for value in supplemental.get("dividend_history", []):
        parsed = to_float(value)
        if parsed is not None:
            dividends.append(parsed)
    dividend_norm = normalize_dividend_cut(dividends)

    comparison = compare_metrics(latest_metrics, previous_metrics)

    assumptions: List[str] = []
    if fetched.missing_fields:
        assumptions.append("部分实时字段未获取到，已按WARNING-Data处理")
    if latest.is_interim:
        assumptions.append("中报现金流按×2年化，存在季节性偏差")

    analysis_day = date.today().isoformat()
    csv_row = build_csv_row(
        ticker=ticker,
        market=market,
        analysis_date=analysis_day,
        latest_period=latest,
        previous_period=previous,
        market_snapshot=snapshot,
        qualitative=qualitative,
        latest_metrics=latest_metrics,
        previous_metrics=previous_metrics,
        metric_comparison=comparison,
        subtype=subtype,
        fact_check=fact_check,
        strategy=strategy,
        dividend_norm=dividend_norm,
        assumptions=assumptions,
        attributions=fetched.attributions,
    )
    write_csv_row(out_csv, csv_row)
    tracer.log("step9_output", "csv written", {"out_csv": out_csv})

    debug_payload = {
        "analysis_date": analysis_day,
        "ticker": ticker,
        "market": market,
        "periods": [dataclass_to_dict(period) for period in periods],
        "market_snapshot": dataclass_to_dict(snapshot),
        "ownership": dataclass_to_dict(ownership),
        "qualitative": dataclass_to_dict(qualitative),
        "latest_metrics": dataclass_to_dict(latest_metrics),
        "previous_metrics": dataclass_to_dict(previous_metrics),
        "subtype": dataclass_to_dict(subtype),
        "fact_check": dataclass_to_dict(fact_check),
        "strategy": dataclass_to_dict(strategy),
        "dividend_normalization": dataclass_to_dict(dividend_norm),
        "metric_comparison": comparison,
        "assumptions": assumptions,
        "fetch_outcome": dataclass_to_dict(fetched),
        "trace_events": dataclass_to_dict(tracer.events),
    }

    if out_debug_json:
        Path(out_debug_json).write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tracer.log("debug", "debug json written", {"out_debug_json": out_debug_json})

    tracer.dump(out_trace_json)

    return {
        "csv_path": out_csv,
        "debug_json_path": out_debug_json,
        "trace_json_path": out_trace_json,
        "row": csv_row,
        "debug": debug_payload,
    }


def run_e2e(project_root: Optional[Path], out_csv: str, out_debug_json: Optional[str], out_trace_json: Optional[str], debug: bool) -> Dict[str, Any]:
    if project_root is None:
        project_root = Path(__file__).resolve().parents[3]

    sample_dir = project_root / "examples"
    fy = sample_dir / "sample_financials_fy2024.json"
    h1 = sample_dir / "sample_financials_h12025.json"
    sup = sample_dir / "sample_supplemental.json"

    if not (fy.exists() and h1.exists() and sup.exists()):
        raise FileNotFoundError("Sample files not found for e2e test")

    result = run_analysis(
        ticker="01502.HK",
        market="HK",
        financial_paths=[str(fy), str(h1)],
        supplemental_path=str(sup),
        out_csv=out_csv,
        out_debug_json=out_debug_json,
        out_trace_json=out_trace_json,
        inventory_haircut=0.7,
        dividend_tax_rate=0.10,
        debug=debug,
    )

    row = result["row"]
    required_non_empty = ["ticker", "market", "latest_period", "subtype", "factcheck_final_rating"]
    for key in required_non_empty:
        if not row.get(key):
            raise RuntimeError(f"E2E failed: missing required output field `{key}`")

    csv_path = Path(out_csv)
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        raise RuntimeError("E2E failed: output CSV not created or empty")

    return result


def run_market_scan(
    market: str,
    out_csv: str,
    out_all_csv: Optional[str],
    out_debug_json: Optional[str],
    out_trace_json: Optional[str],
    debug: bool,
    limit: Optional[int],
    inventory_haircut: float,
    dividend_tax_rate: float,
    annual_dividend_since_year: int,
) -> Dict[str, Any]:
    market_code = market.upper().strip()
    if market_code not in {"HK", "CN", "US"}:
        raise ValueError("market must be one of: HK, CN, US")

    tracer = DebugTracer(enabled=debug)
    analysis_day = date.today().isoformat()
    tracer.log("init", "market scan start", {"date": analysis_day, "market": market_code, "limit": limit})

    client = EastMoneyHKClient()
    universe: List[Dict[str, Any]] = []
    indicators_by_code: Dict[str, List[Dict[str, Any]]] = {}
    dividend_streaks: Dict[str, int] = {}

    def _row_date(row: Dict[str, Any]) -> datetime:
        return parse_date(str(row.get("REPORT_DATE") or "1970-01-01"))

    if market_code == "HK":
        indicators_raw = client.fetch_main_indicators()
        if not indicators_raw:
            raise RuntimeError("HK main indicator dataset is empty")

        sorted_indicators = sorted(indicators_raw, key=_row_date, reverse=True)
        latest_indicator_by_code: Dict[str, Dict[str, Any]] = {}
        for row in sorted_indicators:
            secucode = normalize_hk_secucode(row.get("SECUCODE"))
            if secucode and secucode not in latest_indicator_by_code:
                latest_indicator_by_code[secucode] = row

        quote_universe = client.fetch_hk_universe(limit=None)
        quote_by_code = {row["secucode"]: row for row in quote_universe if row.get("secucode")}
        for secucode, latest_row in latest_indicator_by_code.items():
            quote = quote_by_code.get(secucode, {})
            shares = to_float(latest_row.get("ISSUED_COMMON_SHARES"))
            indicator_market_cap = to_float(latest_row.get("TOTAL_MARKET_CAP"))
            indicator_price = (indicator_market_cap / shares) if indicator_market_cap and shares else None
            indicator_pb = to_float(latest_row.get("PB_TTM"))
            universe.append(
                {
                    "code": secucode.split(".", 1)[0],
                    "secucode": secucode,
                    "name": str(quote.get("name") or latest_row.get("SECURITY_NAME_ABBR") or ""),
                    "price": to_float(quote.get("price")) if quote else indicator_price,
                    "market_cap": to_float(quote.get("market_cap")) if quote else indicator_market_cap,
                    "pb_mrq": to_float(quote.get("pb_mrq")) if quote else indicator_pb,
                }
            )
        universe.sort(key=lambda row: row.get("secucode") or "")
        if limit is not None:
            universe = universe[: max(0, int(limit))]

        universe_codes = {row["secucode"] for row in universe if row.get("secucode")}
        indicators_filtered = [row for row in indicators_raw if normalize_hk_secucode(row.get("SECUCODE")) in universe_codes]
        for row in indicators_filtered:
            secucode = normalize_hk_secucode(row.get("SECUCODE"))
            if secucode:
                indicators_by_code.setdefault(secucode, []).append(row)

        dividend_rows = client.fetch_annual_dividends(since_year=annual_dividend_since_year)
        dividend_streaks = build_dividend_continuous_years(dividend_rows)
        tracer.log(
            "step3_dividend",
            "annual dividend history loaded",
            {"rows": len(dividend_rows), "covered_stocks": len(dividend_streaks)},
        )
        tracer.log(
            "step1_universe",
            "hk universe built",
            {
                "universe_count": len(universe),
                "indicator_universe_count": len(latest_indicator_by_code),
                "quote_universe_count": len(quote_universe),
            },
        )
        tracer.log(
            "step2_indicators",
            "hk indicators loaded",
            {"raw_rows": len(indicators_raw), "filtered_rows": len(indicators_filtered)},
        )

    elif market_code == "CN":
        indicators_raw = client.fetch_cn_main_indicators()
        if not indicators_raw:
            raise RuntimeError("CN main indicator dataset is empty")

        sorted_indicators = sorted(indicators_raw, key=_row_date, reverse=True)
        by_security: Dict[str, List[Dict[str, Any]]] = {}
        latest_by_security: Dict[str, Dict[str, Any]] = {}
        for row in sorted_indicators:
            security_code = str(row.get("SECURITY_CODE", "")).zfill(6)
            if security_code:
                by_security.setdefault(security_code, []).append(row)
                if security_code not in latest_by_security:
                    latest_by_security[security_code] = row

        quote_universe = client.fetch_cn_universe(limit=None)
        quote_by_security = {str(row.get("code", "")).zfill(6): row for row in quote_universe if row.get("code")}
        for security_code, latest_row in latest_by_security.items():
            quote = quote_by_security.get(security_code, {})
            secucode = normalize_cn_secucode(latest_row.get("SECUCODE") or security_code)
            if not secucode:
                continue

            shares = to_float(latest_row.get("TOTAL_SHARE"))
            bps = to_float(latest_row.get("BPS"))
            equity_proxy = (shares * bps) if shares not in (None, 0) and bps is not None else None
            market_cap_quote = to_float(quote.get("market_cap")) if quote else None
            market_cap = market_cap_quote if market_cap_quote not in (None, 0) else equity_proxy
            pb_quote = to_float(quote.get("pb_mrq")) if quote else None
            pb_proxy = (market_cap / equity_proxy) if market_cap not in (None, 0) and equity_proxy not in (None, 0) else None
            pb_value = pb_quote if pb_quote not in (None, 0) else pb_proxy
            price_quote = to_float(quote.get("price")) if quote else None
            price_proxy = (market_cap / shares) if market_cap not in (None, 0) and shares not in (None, 0) else None
            universe.append(
                {
                    "code": security_code,
                    "secucode": secucode,
                    "name": str(quote.get("name") or latest_row.get("SECURITY_NAME_ABBR") or ""),
                    "price": price_quote if price_quote is not None else price_proxy,
                    "market_cap": market_cap,
                    "pb_mrq": pb_value,
                }
            )
            indicators_by_code[secucode] = by_security.get(security_code, [])

        universe.sort(key=lambda row: row.get("secucode") or "")
        if limit is not None:
            universe = universe[: max(0, int(limit))]
            keep = {row["secucode"] for row in universe}
            indicators_by_code = {k: v for k, v in indicators_by_code.items() if k in keep}

        snapshot_refreshed = 0
        if not quote_universe and universe and limit is not None and int(limit) <= 500:
            for row in universe:
                snap = client.fetch_cn_quote_snapshot(str(row.get("secucode", "")))
                if not snap:
                    continue
                if snap.get("name"):
                    row["name"] = str(snap.get("name"))
                if snap.get("price") is not None:
                    row["price"] = to_float(snap.get("price"))
                if snap.get("market_cap") is not None:
                    row["market_cap"] = to_float(snap.get("market_cap"))
                if snap.get("pb_mrq") is not None and to_float(snap.get("pb_mrq")) not in (None, 0):
                    row["pb_mrq"] = to_float(snap.get("pb_mrq"))
                snapshot_refreshed += 1

        tracer.log(
            "step1_universe",
            "cn universe built",
            {
                "universe_count": len(universe),
                "indicator_rows": len(indicators_raw),
                "quote_universe_count": len(quote_universe),
                "snapshot_refreshed": snapshot_refreshed,
            },
        )
        tracer.log(
            "step2_indicators",
            "cn indicators grouped",
            {"grouped_stocks": len(indicators_by_code)},
        )

    else:
        indicators_raw = client.fetch_us_main_indicators()
        if not indicators_raw:
            raise RuntimeError("US main indicator dataset is empty")

        latest_by_code: Dict[str, Dict[str, Any]] = {}
        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for row in indicators_raw:
            secucode = normalize_us_secucode(row.get("SECUCODE"))
            if not secucode:
                continue
            grouped.setdefault(secucode, []).append(row)
            if secucode not in latest_by_code or _row_date(row) > _row_date(latest_by_code[secucode]):
                latest_by_code[secucode] = row

        for secucode, latest_row in latest_by_code.items():
            shares = to_float(latest_row.get("ISSUED_COMMON_SHARES"))
            market_cap = to_float(latest_row.get("TOTAL_MARKET_CAP"))
            price = (market_cap / shares) if market_cap is not None and shares not in (None, 0) else None
            universe.append(
                {
                    "code": str(latest_row.get("SECURITY_CODE", "")),
                    "secucode": secucode,
                    "name": str(latest_row.get("SECURITY_NAME_ABBR", "")),
                    "price": price,
                    "market_cap": market_cap,
                    "pb_mrq": to_float(latest_row.get("PB")),
                }
            )
            indicators_by_code[secucode] = grouped.get(secucode, [])

        universe.sort(key=lambda row: row.get("secucode") or "")
        if limit is not None:
            universe = universe[: max(0, int(limit))]
            keep = {row["secucode"] for row in universe}
            indicators_by_code = {k: v for k, v in indicators_by_code.items() if k in keep}

        tracer.log(
            "step1_universe",
            "us universe built",
            {
                "universe_count": len(universe),
                "indicator_rows": len(indicators_raw),
            },
        )
        tracer.log(
            "step2_indicators",
            "us indicators grouped",
            {"grouped_stocks": len(indicators_by_code)},
        )

    if not universe:
        raise RuntimeError(f"{market_code} universe is empty")

    all_rows: List[Dict[str, Any]] = []
    candidate_rows: List[Dict[str, Any]] = []
    skipped_no_period = 0
    skipped_no_market = 0
    provider_router = ProviderRouter()
    provider_enriched_rows = 0
    provider_enriched_fields = 0

    for quote in universe:
        secucode = str(quote.get("secucode", ""))
        code_rows = indicators_by_code.get(secucode, [])
        selected = select_latest_two_rows(code_rows)
        if not selected:
            if market_code in {"US", "CN"} and code_rows:
                sorted_rows = sorted(code_rows, key=_row_date, reverse=True)
                latest_row = sorted_rows[0]
                previous_row = sorted_rows[0]
            else:
                skipped_no_period += 1
                continue
        else:
            latest_row, previous_row = selected

        if market_code == "HK":
            latest_period = build_period_from_main_indicator(latest_row)
            previous_period = build_period_from_main_indicator(previous_row)
            shares_outstanding = to_float(latest_row.get("ISSUED_COMMON_SHARES"))
            pb_default = to_float(latest_row.get("PB_TTM"))
            dividend_rate = to_float(latest_row.get("DIVIDEND_RATE"))
            dividend_yield_ttm = (dividend_rate / 100.0) if dividend_rate is not None else None
            row_market_cap = to_float(latest_row.get("TOTAL_MARKET_CAP"))
        elif market_code == "CN":
            latest_period = build_period_from_cn_main_indicator(latest_row)
            previous_period = build_period_from_cn_main_indicator(previous_row)
            shares_outstanding = to_float(latest_row.get("TOTAL_SHARE"))
            pb_default = to_float(quote.get("pb_mrq"))
            dividend_yield_ttm = None
            row_market_cap = None
        else:
            latest_period = build_period_from_us_main_indicator(latest_row)
            previous_period = build_period_from_us_main_indicator(previous_row)
            shares_outstanding = to_float(latest_row.get("ISSUED_COMMON_SHARES"))
            pb_default = to_float(latest_row.get("PB"))
            dividend_rate = to_float(latest_row.get("DIVIDEND_RATE"))
            dividend_yield_ttm = (dividend_rate / 100.0) if dividend_rate is not None else None
            row_market_cap = to_float(latest_row.get("TOTAL_MARKET_CAP"))

        market_cap = to_float(quote.get("market_cap"))
        if market_cap in (None, 0):
            market_cap = row_market_cap
        pb_mrq = to_float(quote.get("pb_mrq"))
        if pb_mrq in (None, 0):
            pb_mrq = pb_default
        price = to_float(quote.get("price"))
        name = str(quote.get("name", "")) or str(latest_row.get("SECURITY_NAME_ABBR", ""))

        provider_ticker = normalize_provider_ticker(secucode, market_code)
        missing_fields: List[str] = []
        if price in (None, 0):
            missing_fields.append("price")
            missing_fields.append("price_date")
        if market_cap in (None, 0):
            missing_fields.append("market_cap")
        if shares_outstanding in (None, 0):
            missing_fields.append("shares_outstanding")

        if provider_ticker and missing_fields:
            unique_missing = sorted(set(missing_fields))
            enriched = provider_router.fetch_fields(provider_ticker, market_code, unique_missing)
            changed = 0

            fetched_price = to_float(enriched.values.get("price"))
            if price in (None, 0) and fetched_price is not None:
                price = fetched_price
                changed += 1

            fetched_cap = to_float(enriched.values.get("market_cap"))
            if market_cap in (None, 0) and fetched_cap is not None:
                market_cap = fetched_cap
                changed += 1

            fetched_shares = to_float(enriched.values.get("shares_outstanding"))
            if shares_outstanding in (None, 0) and fetched_shares is not None:
                shares_outstanding = fetched_shares
                changed += 1

            if changed > 0:
                provider_enriched_rows += 1
                provider_enriched_fields += changed

        if (market_cap in (None, 0)) and price not in (None, 0) and shares_outstanding not in (None, 0):
            market_cap = float(price) * float(shares_outstanding)

        if market_cap is None or market_cap <= 0:
            skipped_no_market += 1
            continue

        snapshot = MarketSnapshot(
            ticker=secucode,
            market=market_code,
            price=price,
            price_date=analysis_day,
            market_cap=market_cap,
            shares_outstanding=shares_outstanding,
            pb_mrq=pb_mrq,
            dividend_yield_ttm=dividend_yield_ttm,
        )

        latest_metrics = compute_pillar_metrics(latest_period, snapshot, inventory_haircut)
        previous_metrics = compute_pillar_metrics(previous_period, snapshot, inventory_haircut)
        p2_count, p2_pass, ocf_three_pos = evaluate_pillar_two(latest_metrics, [latest_period, previous_period])
        latest_metrics.pillar_two_pass_count = p2_count
        latest_metrics.pillar_two_pass = p2_pass
        latest_metrics.ocf_three_year_positive = ocf_three_pos

        continuous_dividend_years = int(dividend_streaks.get(secucode, 0))
        subtype = assess_subtype(
            market=market_code,
            pillar_metrics=latest_metrics,
            pb_mrq=pb_mrq,
            dividend_yield_ttm=dividend_yield_ttm,
            continuous_dividend_years=continuous_dividend_years,
            holding_value_coverage=None,
            parent_discount_rate=None,
            parent_holding_ratio=None,
            net_cash_positive=None,
            catalyst_probability=None,
        )
        fact_check = run_fact_check(latest_period, latest_metrics, OwnershipProfile(), {})
        strategy = build_strategy(price, pb_mrq, dividend_yield_ttm, latest_metrics, subtype, dividend_tax_rate)

        t_level_pass = latest_metrics.t_level in {"T0", "T1", "T2"}
        rating_pass = fact_check.final_rating in {"A", "B", "B+"}
        subtype_pass = subtype.subtype != "UNCLASSIFIED"
        quant_fallback_pass = bool(pb_mrq is not None and pb_mrq <= 0.50 and t_level_pass)
        is_candidate = bool(rating_pass and (subtype_pass and t_level_pass or quant_fallback_pass))
        candidate_reason = "STRICT_SUBTYPE" if subtype_pass and t_level_pass else ("QUANT_FALLBACK" if is_candidate else "")

        row = {
            "analysis_date": analysis_day,
            "market": market_code,
            "ticker": secucode,
            "name": name,
            "latest_period": latest_period.period_label,
            "latest_period_end": latest_period.period_end,
            "previous_period": previous_period.period_label,
            "previous_period_end": previous_period.period_end,
            "price": price,
            "market_cap": market_cap,
            "shares_outstanding": shares_outstanding,
            "pb_mrq": pb_mrq,
            "dividend_yield_ttm": dividend_yield_ttm,
            "continuous_dividend_years": continuous_dividend_years,
            "t_level": latest_metrics.t_level,
            "t0_nav_latest": latest_metrics.t0_nav,
            "t1_nav_latest": latest_metrics.t1_nav,
            "t2_nav_latest": latest_metrics.t2_nav,
            "fcf_latest": latest_metrics.fcf,
            "burn_rate_latest": latest_metrics.burn_rate,
            "pillar_two_pass_count": latest_metrics.pillar_two_pass_count,
            "pillar_two_pass": latest_metrics.pillar_two_pass,
            "subtype": subtype.subtype,
            "mixed_labels": ";".join(subtype.mixed_labels),
            "subtype_rationale": " | ".join(subtype.rationale),
            "factcheck_final_rating": fact_check.final_rating,
            "warning_risk_count": fact_check.warning_risk_count,
            "veto_count": fact_check.veto_count,
            "subtype_pass": subtype_pass,
            "quant_fallback_pass": quant_fallback_pass,
            "candidate_reason": candidate_reason,
            "entry_threshold": strategy.entry_threshold,
            "position_limit": strategy.position_limit,
            "return_base": strategy.base_return,
            "irr_3y": strategy.irr_3y,
            "missing_metrics": "|".join(latest_metrics.missing),
            "data_date_type_code": str(latest_row.get("DATE_TYPE_CODE", "")),
            "data_report_type": str(latest_row.get("REPORT_TYPE", "")),
            "is_candidate": bool(is_candidate),
        }

        all_rows.append(row)
        if is_candidate:
            candidate_rows.append(row)

    t_rank = {"T0": 0, "T1": 1, "T2": 2, "NONE": 3}
    candidate_rows.sort(
        key=lambda row: (
            t_rank.get(str(row.get("t_level", "NONE")), 4),
            row.get("pb_mrq") if row.get("pb_mrq") is not None else 999.0,
            -(row.get("dividend_yield_ttm") if row.get("dividend_yield_ttm") is not None else -1.0),
            row.get("market_cap") if row.get("market_cap") is not None else float("inf"),
        )
    )

    headers = [
        "analysis_date",
        "market",
        "ticker",
        "name",
        "latest_period_end",
        "previous_period_end",
        "price",
        "market_cap",
        "pb_mrq",
        "dividend_yield_ttm",
        "continuous_dividend_years",
        "t_level",
        "t0_nav_latest",
        "t1_nav_latest",
        "t2_nav_latest",
        "fcf_latest",
        "burn_rate_latest",
        "pillar_two_pass_count",
        "subtype",
        "factcheck_final_rating",
        "warning_risk_count",
        "veto_count",
        "subtype_pass",
        "quant_fallback_pass",
        "candidate_reason",
        "entry_threshold",
        "position_limit",
        "return_base",
        "irr_3y",
        "missing_metrics",
        "is_candidate",
    ]
    write_csv_rows(out_csv, candidate_rows, preferred_headers=headers)
    if out_all_csv:
        write_csv_rows(out_all_csv, all_rows, preferred_headers=headers)
    tracer.log(
        "step4_output",
        "market scan output written",
        {
            "market": market_code,
            "out_csv": out_csv,
            "out_all_csv": out_all_csv,
            "candidates": len(candidate_rows),
            "processed": len(all_rows),
            "skipped_no_period": skipped_no_period,
            "skipped_no_market": skipped_no_market,
            "provider_enriched_rows": provider_enriched_rows,
            "provider_enriched_fields": provider_enriched_fields,
        },
    )

    summary = {
        "analysis_date": analysis_day,
        "market": market_code,
        "universe_count": len(universe),
        "processed_count": len(all_rows),
        "candidate_count": len(candidate_rows),
        "skipped_no_period": skipped_no_period,
        "skipped_no_market": skipped_no_market,
        "provider_enriched_rows": provider_enriched_rows,
        "provider_enriched_fields": provider_enriched_fields,
        "out_csv": out_csv,
        "out_all_csv": out_all_csv,
        "criteria": {
            "subtype_not_unclassified": True,
            "t_level_required": ["T0", "T1", "T2"],
            "rating_allowed": ["A", "B", "B+"],
            "quant_fallback": {
                "t_level_required": ["T0", "T1", "T2"],
                "pb_mrq_le": 0.5,
                "used_when_subtype_unclassified": True,
            },
            "subtype_A_core": {
                "pb_mrq_le": 0.5,
                "dividend_yield_floor_hk": 0.06,
                "continuous_dividend_years_ge": 5,
            },
        },
    }
    debug_payload = {
        "summary": summary,
        "top_candidates_preview": candidate_rows[:50],
        "trace_events": dataclass_to_dict(tracer.events),
    }
    if out_debug_json:
        Path(out_debug_json).write_text(json.dumps(debug_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    tracer.dump(out_trace_json)
    return {
        "summary": summary,
        "csv_path": out_csv,
        "all_csv_path": out_all_csv,
        "debug_json_path": out_debug_json,
        "trace_json_path": out_trace_json,
    }


def run_hk_scan(
    out_csv: str,
    out_all_csv: Optional[str],
    out_debug_json: Optional[str],
    out_trace_json: Optional[str],
    debug: bool,
    limit: Optional[int],
    inventory_haircut: float,
    dividend_tax_rate: float,
    annual_dividend_since_year: int,
) -> Dict[str, Any]:
    return run_market_scan(
        market="HK",
        out_csv=out_csv,
        out_all_csv=out_all_csv,
        out_debug_json=out_debug_json,
        out_trace_json=out_trace_json,
        debug=debug,
        limit=limit,
        inventory_haircut=inventory_haircut,
        dividend_tax_rate=dividend_tax_rate,
        annual_dividend_since_year=annual_dividend_since_year,
    )
