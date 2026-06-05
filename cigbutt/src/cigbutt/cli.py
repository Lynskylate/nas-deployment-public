from __future__ import annotations

import argparse
import sys

from .commands import cmd_analyze, cmd_e2e_test, cmd_probe_providers, cmd_scan_hk, cmd_scan_market


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Cigbutt v1.7 workflow -> CSV")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe-providers", help="Probe provider enablement and optional fetch")
    probe.add_argument("--ticker", help="Ticker for sample fetch")
    probe.add_argument("--market", default="HK", help="Market code")
    probe.set_defaults(func=cmd_probe_providers)

    analyze = subparsers.add_parser("analyze", help="Run analysis and write CSV")
    analyze.add_argument("--ticker", required=True)
    analyze.add_argument("--market", required=True)
    analyze.add_argument("--financials", nargs="+", required=True, help="At least two financial files (json/csv)")
    analyze.add_argument("--supplemental", help="Supplemental JSON")
    analyze.add_argument("--out-csv", required=True)
    analyze.add_argument("--out-debug-json")
    analyze.add_argument("--out-trace-json")
    analyze.add_argument("--debug", action="store_true", help="Enable step-level trace logging")
    analyze.add_argument("--inventory-haircut", type=float, default=0.7)
    analyze.add_argument("--dividend-tax-rate", type=float, default=0.10)
    analyze.set_defaults(func=cmd_analyze)

    e2e = subparsers.add_parser("e2e-test", help="Run built-in end-to-end test and write CSV")
    e2e.add_argument("--out-csv", default="/tmp/cigbutt-e2e.csv")
    e2e.add_argument("--out-debug-json", default="/tmp/cigbutt-e2e-debug.json")
    e2e.add_argument("--out-trace-json", default="/tmp/cigbutt-e2e-trace.json")
    e2e.add_argument("--debug", action="store_true", help="Enable verbose e2e trace")
    e2e.set_defaults(func=cmd_e2e_test)

    scan = subparsers.add_parser("scan-hk", help="Scan HK universe and output cigbutt candidates CSV")
    scan.add_argument("--out-csv", default="/tmp/cigbutt-hk-candidates.csv")
    scan.add_argument("--out-all-csv", help="Optional full processed universe CSV")
    scan.add_argument("--out-debug-json")
    scan.add_argument("--out-trace-json")
    scan.add_argument("--debug", action="store_true", help="Enable step-level trace logging")
    scan.add_argument("--limit", type=int, help="Optional limit for quick runs")
    scan.add_argument("--inventory-haircut", type=float, default=0.7)
    scan.add_argument("--dividend-tax-rate", type=float, default=0.10)
    scan.add_argument("--annual-dividend-since-year", type=int, default=2010)
    scan.set_defaults(func=cmd_scan_hk)

    scan_market = subparsers.add_parser("scan-market", help="Scan selected market (HK/CN/US) and output candidates CSV")
    scan_market.add_argument("--market", choices=["HK", "CN", "US"], required=True)
    scan_market.add_argument("--out-csv", default="/tmp/cigbutt-market-candidates.csv")
    scan_market.add_argument("--out-all-csv", help="Optional full processed universe CSV")
    scan_market.add_argument("--out-debug-json")
    scan_market.add_argument("--out-trace-json")
    scan_market.add_argument("--debug", action="store_true", help="Enable step-level trace logging")
    scan_market.add_argument("--limit", type=int, help="Optional limit for quick runs")
    scan_market.add_argument("--inventory-haircut", type=float, default=0.7)
    scan_market.add_argument("--dividend-tax-rate", type=float, default=0.10)
    scan_market.add_argument("--annual-dividend-since-year", type=int, default=2010)
    scan_market.set_defaults(func=cmd_scan_market)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return int(args.func(args))
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
