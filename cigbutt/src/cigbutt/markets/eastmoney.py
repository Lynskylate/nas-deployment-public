from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..models import FinancialPeriod
from ..utils import get_json, parse_date, to_float
from .normalize import normalize_cn_secucode, normalize_hk_secucode, normalize_us_secucode


class EastMoneyHKClient:
    QUOTE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
    DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    def __init__(self, timeout: int = 25, pause_seconds: float = 0.04) -> None:
        self.timeout = timeout
        self.pause_seconds = pause_seconds
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            )
        }

    def _fetch_json_with_retry(self, url: str, params: Dict[str, Any], retries: int = 3) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        for attempt in range(retries):
            payload = get_json(url, params=params, headers=self.headers, timeout=self.timeout)
            if payload:
                if payload.get("success") is False and payload.get("message"):
                    time.sleep(self.pause_seconds * (attempt + 1))
                    continue
                return payload
            time.sleep(self.pause_seconds * (attempt + 1))
        return payload

    def fetch_hk_universe(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        page_size = 100
        while True:
            payload = self._fetch_json_with_retry(
                self.QUOTE_URL,
                {
                    "pn": page,
                    "pz": page_size,
                    "po": 1,
                    "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": "m:128+t:3,m:128+t:4,m:128+t:1,m:128+t:2",
                    "fields": "f12,f14,f2,f3,f20,f21,f23",
                },
            )
            diff = payload.get("data", {}).get("diff", []) if isinstance(payload, dict) else []
            if not diff:
                break

            for item in diff:
                code = str(item.get("f12", "")).zfill(5)
                secucode = normalize_hk_secucode(code)
                if not secucode:
                    continue
                rows.append(
                    {
                        "code": code,
                        "secucode": secucode,
                        "name": str(item.get("f14", "")),
                        "price": to_float(item.get("f2")),
                        "market_cap": to_float(item.get("f20")),
                        "pb_mrq": to_float(item.get("f23")),
                    }
                )
                if limit and len(rows) >= limit:
                    return rows

            if len(diff) < page_size:
                break
            page += 1
            time.sleep(self.pause_seconds)

        return rows

    def fetch_cn_universe(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        page_size = 200
        while True:
            payload = self._fetch_json_with_retry(
                self.QUOTE_URL,
                {
                    "pn": page,
                    "pz": page_size,
                    "po": 1,
                    "np": 1,
                    "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                    "fltt": 2,
                    "invt": 2,
                    "fid": "f3",
                    "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
                    "fields": "f12,f14,f2,f3,f20,f21,f23",
                },
            )
            diff = payload.get("data", {}).get("diff", []) if isinstance(payload, dict) else []
            if not diff:
                break

            for item in diff:
                security_code = str(item.get("f12", "")).zfill(6)
                secucode = normalize_cn_secucode(security_code)
                if not secucode:
                    continue
                rows.append(
                    {
                        "code": security_code,
                        "secucode": secucode,
                        "name": str(item.get("f14", "")),
                        "price": to_float(item.get("f2")),
                        "market_cap": to_float(item.get("f20")),
                        "pb_mrq": to_float(item.get("f23")),
                    }
                )
                if limit and len(rows) >= limit:
                    return rows

            if len(diff) < page_size:
                break
            page += 1
            time.sleep(self.pause_seconds)
        return rows

    def fetch_cn_quote_snapshot(self, secucode: str) -> Dict[str, Any]:
        norm = normalize_cn_secucode(secucode)
        if not norm:
            return {}
        code, suffix = norm.split(".", 1)
        market_id = "1" if suffix == "SH" else "0"
        payload = self._fetch_json_with_retry(
            "https://push2.eastmoney.com/api/qt/stock/get",
            {
                "secid": f"{market_id}.{code}",
                "fields": "f57,f58,f43,f116,f117,f167",
            },
        )
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if not isinstance(data, dict):
            return {}
        price_raw = to_float(data.get("f43"))
        pb_raw = to_float(data.get("f167"))
        return {
            "code": str(data.get("f57") or code).zfill(6),
            "name": str(data.get("f58") or ""),
            "price": (price_raw / 100.0) if price_raw is not None else None,
            "market_cap": to_float(data.get("f116")),
            "market_cap_float": to_float(data.get("f117")),
            "pb_mrq": (pb_raw / 100.0) if pb_raw is not None else None,
        }

    def fetch_main_indicators(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        page_size = 500
        while True:
            payload = self._fetch_json_with_retry(
                self.DATACENTER_URL,
                {
                    "reportName": "RPT_HKF10_FN_MAININDICATOR",
                    "columns": (
                        "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,DATE_TYPE_CODE,REPORT_TYPE,"
                        "PB_TTM,DIVIDEND_RATE,TOTAL_LIABILITIES,TOTAL_ASSETS,TOTAL_PARENT_EQUITY,"
                        "NETCASH_OPERATE,NETCASH_INVEST,HOLDER_PROFIT,END_CASH,ISSUED_COMMON_SHARES,TOTAL_MARKET_CAP"
                    ),
                    "sortColumns": "REPORT_DATE",
                    "sortTypes": "-1",
                    "pageNumber": page,
                    "pageSize": page_size,
                },
            )
            data = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
            if not data:
                break
            rows.extend([item for item in data if isinstance(item, dict)])
            if len(data) < page_size:
                break
            page += 1
            time.sleep(self.pause_seconds)
        return rows

    def fetch_cn_main_indicators(self, since_date: str = "2024-01-01") -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        page_size = 500
        filter_text = f"(REPORT_DATE>='{since_date}')"
        while True:
            payload = self._fetch_json_with_retry(
                self.DATACENTER_URL,
                {
                    "reportName": "RPT_F10_FINANCE_MAINFINADATA",
                    "columns": (
                        "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,REPORT_TYPE,CURRENCY,"
                        "PARENTNETPROFIT,NETCASH_OPERATE_PK,NETCASH_INVEST_PK,LIABILITY,TOTAL_ASSETS_PK,"
                        "TOTAL_SHARE,BPS,NOTICE_DATE,UPDATE_DATE,ORG_TYPE"
                    ),
                    "filter": filter_text,
                    "sortColumns": "REPORT_DATE",
                    "sortTypes": "-1",
                    "pageNumber": page,
                    "pageSize": page_size,
                },
            )
            data = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
            if not data:
                break
            rows.extend([item for item in data if isinstance(item, dict)])
            if len(data) < page_size:
                break
            page += 1
            time.sleep(self.pause_seconds)
        return rows

    def fetch_us_main_indicators(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        page_size = 500
        while True:
            payload = self._fetch_json_with_retry(
                self.DATACENTER_URL,
                {
                    "reportName": "RPT_USF10_DATA_MAININDICATOR",
                    "columns": (
                        "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,REPORT_DATE,STD_REPORT_DATE,ORG_TYPE,"
                        "CURRENCY,CURRENCY_ABBR,HOLDER_PROFIT,TURNOVER,TOTAL_MARKET_CAP,ISSUED_COMMON_SHARES,"
                        "PB,BVPS,DIVIDEND_RATE,DPS_USD"
                    ),
                    "sortColumns": "REPORT_DATE",
                    "sortTypes": "-1",
                    "pageNumber": page,
                    "pageSize": page_size,
                },
            )
            data = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
            if not data:
                break
            rows.extend([item for item in data if isinstance(item, dict)])
            if len(data) < page_size:
                break
            page += 1
            time.sleep(self.pause_seconds)
        return rows

    def fetch_annual_dividends(self, since_year: int = 2010) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 1
        page_size = 500
        filter_text = f'(REPORT_TYPE="年度分配")(YEAR>="{since_year}")'
        while True:
            payload = self._fetch_json_with_retry(
                self.DATACENTER_URL,
                {
                    "reportName": "RPT_HKF10_MAIN_DIVBASIC",
                    "columns": "SECUCODE,YEAR,REPORT_TYPE,NOTICE_DATE,PLAN_EXPLAIN",
                    "filter": filter_text,
                    "sortColumns": "NOTICE_DATE",
                    "sortTypes": "-1",
                    "pageNumber": page,
                    "pageSize": page_size,
                },
            )
            data = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
            if not data:
                break
            rows.extend([item for item in data if isinstance(item, dict)])
            if len(data) < page_size:
                break
            page += 1
            time.sleep(self.pause_seconds)
        return rows


def build_period_from_main_indicator(row: Dict[str, Any]) -> FinancialPeriod:
    netcash_invest = to_float(row.get("NETCASH_INVEST"))
    capex_proxy = None
    if netcash_invest is not None:
        capex_proxy = -netcash_invest if netcash_invest < 0 else 0.0

    report_date = str(row.get("REPORT_DATE") or "")
    period_end = report_date[:10] if report_date else "1970-01-01"
    report_type = str(row.get("REPORT_TYPE") or period_end)
    date_type_code = str(row.get("DATE_TYPE_CODE") or "")
    is_interim = date_type_code != "001"

    metrics: Dict[str, float] = {}
    value_map = {
        "cash_and_equivalents": to_float(row.get("END_CASH")),
        "short_term_investments": None,
        "term_deposits": None,
        "short_term_debt": None,
        "long_term_debt": None,
        "total_liabilities": to_float(row.get("TOTAL_LIABILITIES")),
        "accounts_receivable": None,
        "inventory": None,
        "other_current_assets": None,
        "operating_cash_flow": to_float(row.get("NETCASH_OPERATE")),
        "capital_expenditure": capex_proxy,
        "net_income": to_float(row.get("HOLDER_PROFIT")),
        "restricted_cash": None,
        "goodwill": None,
        "total_assets": to_float(row.get("TOTAL_ASSETS")),
        "intangible_assets": None,
        "equity": to_float(row.get("TOTAL_PARENT_EQUITY")),
    }
    for key, value in value_map.items():
        if value is not None:
            metrics[key] = value

    return FinancialPeriod(
        period_label=report_type,
        period_end=period_end,
        accounting_standard="HKFRS",
        currency="HKD",
        is_interim=is_interim,
        metrics=metrics,
    )


def build_period_from_cn_main_indicator(row: Dict[str, Any]) -> FinancialPeriod:
    report_date = str(row.get("REPORT_DATE") or "")
    period_end = report_date[:10] if report_date else "1970-01-01"
    report_type = str(row.get("REPORT_TYPE") or period_end)
    is_interim = "年报" not in report_type

    total_assets = to_float(row.get("TOTAL_ASSETS_PK"))
    liabilities = to_float(row.get("LIABILITY"))
    net_income = to_float(row.get("PARENTNETPROFIT"))
    ocf = to_float(row.get("NETCASH_OPERATE_PK"))
    invest_cash = to_float(row.get("NETCASH_INVEST_PK"))
    capex_proxy = None
    if invest_cash is not None:
        capex_proxy = -invest_cash if invest_cash < 0 else 0.0

    cash_proxy = None
    if total_assets is not None and liabilities is not None:
        cash_proxy = total_assets

    metrics: Dict[str, float] = {}
    value_map = {
        "cash_and_equivalents": cash_proxy,
        "short_term_investments": None,
        "term_deposits": None,
        "short_term_debt": None,
        "long_term_debt": None,
        "total_liabilities": liabilities,
        "accounts_receivable": None,
        "inventory": None,
        "other_current_assets": None,
        "operating_cash_flow": ocf,
        "capital_expenditure": capex_proxy,
        "net_income": net_income,
        "restricted_cash": None,
        "goodwill": None,
        "total_assets": total_assets,
        "intangible_assets": None,
        "equity": (total_assets - liabilities) if total_assets is not None and liabilities is not None else None,
    }
    for key, value in value_map.items():
        if value is not None:
            metrics[key] = value

    return FinancialPeriod(
        period_label=report_type,
        period_end=period_end,
        accounting_standard="CN-GAAP",
        currency=str(row.get("CURRENCY") or "CNY"),
        is_interim=is_interim,
        metrics=metrics,
    )


def build_period_from_us_main_indicator(row: Dict[str, Any]) -> FinancialPeriod:
    report_date = str(row.get("REPORT_DATE") or "")
    period_end = report_date[:10] if report_date else "1970-01-01"
    std_report_date = str(row.get("STD_REPORT_DATE") or "")
    report_type = "US_MAIN"
    is_interim = True
    if std_report_date and std_report_date.endswith("-12-31 00:00:00"):
        is_interim = False

    shares = to_float(row.get("ISSUED_COMMON_SHARES"))
    pb = to_float(row.get("PB"))
    market_cap = to_float(row.get("TOTAL_MARKET_CAP"))
    equity_est = None
    if shares is not None:
        bvps = to_float(row.get("BVPS"))
        if bvps is not None:
            equity_est = bvps * shares
    if equity_est is None and market_cap is not None and pb not in (None, 0):
        equity_est = market_cap / pb

    metrics: Dict[str, float] = {}
    value_map = {
        "cash_and_equivalents": equity_est,
        "short_term_investments": None,
        "term_deposits": None,
        "short_term_debt": None,
        "long_term_debt": None,
        "total_liabilities": 0.0 if equity_est is not None else None,
        "accounts_receivable": None,
        "inventory": None,
        "other_current_assets": None,
        "operating_cash_flow": None,
        "capital_expenditure": None,
        "net_income": to_float(row.get("HOLDER_PROFIT")),
        "restricted_cash": None,
        "goodwill": None,
        "total_assets": equity_est,
        "intangible_assets": None,
        "equity": equity_est,
    }
    for key, value in value_map.items():
        if value is not None:
            metrics[key] = value

    currency = str(row.get("CURRENCY_ABBR") or row.get("CURRENCY") or "USD")
    return FinancialPeriod(
        period_label=report_type,
        period_end=period_end,
        accounting_standard="US-GAAP",
        currency=currency,
        is_interim=is_interim,
        metrics=metrics,
    )


def select_latest_two_rows(rows: List[Dict[str, Any]]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    if len(rows) < 2:
        return None
    sorted_rows = sorted(rows, key=lambda r: parse_date(str(r.get("REPORT_DATE") or "1970-01-01")), reverse=True)
    unique: List[Dict[str, Any]] = []
    seen_dates: set[str] = set()
    for row in sorted_rows:
        report_date = str(row.get("REPORT_DATE") or "")
        if report_date in seen_dates:
            continue
        unique.append(row)
        seen_dates.add(report_date)
        if len(unique) == 2:
            break
    if len(unique) < 2:
        return None
    return unique[0], unique[1]
