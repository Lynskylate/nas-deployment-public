from __future__ import annotations

from typing import Any, Dict, List


def normalize_hk_secucode(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if text.endswith(".HK"):
        code = text.split(".", 1)[0]
    else:
        code = text
    if code.isdigit():
        code = code.zfill(5)
    return f"{code}.HK"


def normalize_cn_secucode(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        code, suffix = text.split(".", 1)
        if code.isdigit():
            code = code.zfill(6)
        return f"{code}.{suffix}"
    code = text
    if not code.isdigit():
        return ""
    code = code.zfill(6)
    if code.startswith(("5", "6", "9")):
        suffix = "SH"
    elif code.startswith(("4", "8")):
        suffix = "BJ"
    else:
        suffix = "SZ"
    return f"{code}.{suffix}"


def normalize_us_secucode(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        return ""
    if "." in text:
        left, right = text.split(".", 1)
        return f"{left.strip().upper()}.{right.strip().upper()}"
    return text


def normalize_provider_ticker(ticker: str, market: str) -> str:
    market_code = market.upper().strip()
    if market_code == "HK":
        secucode = normalize_hk_secucode(ticker)
        if not secucode:
            return ""
        code = secucode.split(".", 1)[0].lstrip("0").zfill(4)
        return f"{code}.HK"
    if market_code == "CN":
        secucode = normalize_cn_secucode(ticker)
        if not secucode:
            return ""
        code, suffix = secucode.split(".", 1)
        if suffix == "SH":
            suffix = "SS"
        return f"{code}.{suffix}"
    if market_code == "US":
        secucode = normalize_us_secucode(ticker)
        if not secucode:
            return ""
        if ":" in secucode:
            secucode = secucode.split(":", 1)[1]
        if "." in secucode:
            code, suffix = secucode.split(".", 1)
            if suffix in {"US", "NASDAQ", "NYSE", "AMEX"}:
                return code
        return secucode
    return str(ticker or "").strip().upper()


def is_dividend_paid(plan_explain: str) -> bool:
    text = str(plan_explain or "").strip()
    if not text:
        return False
    lowered = text.lower()
    negative_tokens = ["未派发", "不派", "不宣派", "无股息", "nil", "no dividend"]
    return not any(token in lowered for token in negative_tokens)


def build_dividend_continuous_years(dividend_rows: List[Dict[str, Any]]) -> Dict[str, int]:
    yearly_paid: Dict[str, Dict[int, bool]] = {}
    for row in dividend_rows:
        secucode = normalize_hk_secucode(row.get("SECUCODE"))
        year_text = str(row.get("YEAR", "")).strip()
        if not secucode or not year_text.isdigit():
            continue
        year = int(year_text)
        paid = is_dividend_paid(str(row.get("PLAN_EXPLAIN", "")))
        per_code = yearly_paid.setdefault(secucode, {})
        per_code[year] = bool(per_code.get(year, False) or paid)

    out: Dict[str, int] = {}
    for secucode, year_map in yearly_paid.items():
        if not year_map:
            out[secucode] = 0
            continue
        current_year = max(year_map.keys())
        streak = 0
        while year_map.get(current_year, False):
            streak += 1
            current_year -= 1
        out[secucode] = streak
    return out
