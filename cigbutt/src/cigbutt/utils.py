from __future__ import annotations

import csv
import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .models import FinancialPeriod


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_json(
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 20,
) -> Dict[str, Any]:
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        join_char = "&" if "?" in url else "?"
        url = f"{url}{join_char}{query}"

    request = urllib.request.Request(url=url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8")
            return json.loads(text)
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        socket.timeout,
        json.JSONDecodeError,
        http.client.HTTPException,
        ConnectionResetError,
    ):
        return {}


def as_percent(value: Optional[float]) -> str:
    if value is None:
        return ""
    return f"{value * 100:.4f}%"


def dataclass_to_dict(instance: Any) -> Any:
    if isinstance(instance, list):
        return [dataclass_to_dict(item) for item in instance]
    if isinstance(instance, dict):
        return {k: dataclass_to_dict(v) for k, v in instance.items()}
    if hasattr(instance, "__dataclass_fields__"):
        return {k: dataclass_to_dict(getattr(instance, k)) for k in instance.__dataclass_fields__.keys()}
    if isinstance(instance, Enum):
        return instance.value
    return instance


def parse_date(date_text: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(date_text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Unsupported date format: {date_text}")


def load_periods(paths: Iterable[str]) -> List[FinancialPeriod]:
    periods: List[FinancialPeriod] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {path}")

        if path.suffix.lower() == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload = [payload]
            if not isinstance(payload, list):
                raise ValueError(f"Invalid JSON shape in {path}")

            for item in payload:
                if not isinstance(item, dict):
                    continue
                metrics = {
                    key: float(value)
                    for key, value in item.get("metrics", {}).items()
                    if to_float(value) is not None
                }
                periods.append(
                    FinancialPeriod(
                        period_label=str(item.get("period_label", path.stem)),
                        period_end=str(item.get("period_end")),
                        accounting_standard=str(item.get("accounting_standard", "UNKNOWN")),
                        currency=str(item.get("currency", "UNKNOWN")),
                        is_interim=bool(item.get("is_interim", False)),
                        metrics=metrics,
                    )
                )
        elif path.suffix.lower() == ".csv":
            meta: Dict[str, str] = {}
            metrics: Dict[str, float] = {}
            with path.open("r", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                for row in reader:
                    if not row:
                        continue
                    kind = row[0].strip().lower()
                    if kind == "metric" and len(row) >= 3 and to_float(row[2]) is not None:
                        metrics[row[1].strip()] = float(row[2])
                    elif len(row) >= 2:
                        meta[kind] = row[1].strip()
            periods.append(
                FinancialPeriod(
                    period_label=meta.get("period_label", path.stem),
                    period_end=meta.get("period_end", "1970-01-01"),
                    accounting_standard=meta.get("accounting_standard", "UNKNOWN"),
                    currency=meta.get("currency", "UNKNOWN"),
                    is_interim=meta.get("is_interim", "false").lower() == "true",
                    metrics=metrics,
                )
            )
        else:
            raise ValueError(f"Unsupported input type: {path}")

    if len(periods) < 2:
        raise ValueError("At least two financial periods are required")

    periods.sort(key=lambda item: parse_date(item.period_end), reverse=True)
    return periods
