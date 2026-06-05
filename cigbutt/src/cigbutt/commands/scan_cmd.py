from __future__ import annotations

import argparse

from ..strategy import run_hk_scan, run_market_scan


def cmd_scan_hk(args: argparse.Namespace) -> int:
    result = run_hk_scan(
        out_csv=args.out_csv,
        out_all_csv=args.out_all_csv,
        out_debug_json=args.out_debug_json,
        out_trace_json=args.out_trace_json,
        debug=args.debug,
        limit=args.limit,
        inventory_haircut=args.inventory_haircut,
        dividend_tax_rate=args.dividend_tax_rate,
        annual_dividend_since_year=args.annual_dividend_since_year,
    )
    summary = result["summary"]
    print(f"[OK] HK scan done. Candidates: {summary['candidate_count']} / Processed: {summary['processed_count']}")
    print(f"[OK] Candidate CSV: {result['csv_path']}")
    if result.get("all_csv_path"):
        print(f"[OK] Full universe CSV: {result['all_csv_path']}")
    if args.out_debug_json:
        print(f"[OK] Debug JSON: {result['debug_json_path']}")
    if args.out_trace_json:
        print(f"[OK] Trace JSON: {result['trace_json_path']}")
    return 0


def cmd_scan_market(args: argparse.Namespace) -> int:
    result = run_market_scan(
        market=args.market,
        out_csv=args.out_csv,
        out_all_csv=args.out_all_csv,
        out_debug_json=args.out_debug_json,
        out_trace_json=args.out_trace_json,
        debug=args.debug,
        limit=args.limit,
        inventory_haircut=args.inventory_haircut,
        dividend_tax_rate=args.dividend_tax_rate,
        annual_dividend_since_year=args.annual_dividend_since_year,
    )
    summary = result["summary"]
    print(
        f"[OK] {summary['market']} scan done. "
        f"Candidates: {summary['candidate_count']} / Processed: {summary['processed_count']}"
    )
    print(f"[OK] Candidate CSV: {result['csv_path']}")
    if result.get("all_csv_path"):
        print(f"[OK] Full universe CSV: {result['all_csv_path']}")
    if args.out_debug_json:
        print(f"[OK] Debug JSON: {result['debug_json_path']}")
    if args.out_trace_json:
        print(f"[OK] Trace JSON: {result['trace_json_path']}")
    return 0
