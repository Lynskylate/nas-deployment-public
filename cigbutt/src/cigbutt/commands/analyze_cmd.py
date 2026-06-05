from __future__ import annotations

import argparse

from ..strategy import run_analysis


def cmd_analyze(args: argparse.Namespace) -> int:
    result = run_analysis(
        ticker=args.ticker,
        market=args.market,
        financial_paths=args.financials,
        supplemental_path=args.supplemental,
        out_csv=args.out_csv,
        out_debug_json=args.out_debug_json,
        out_trace_json=args.out_trace_json,
        inventory_haircut=args.inventory_haircut,
        dividend_tax_rate=args.dividend_tax_rate,
        debug=args.debug,
    )
    print(f"[OK] CSV written: {result['csv_path']}")
    if args.out_debug_json:
        print(f"[OK] Debug JSON: {result['debug_json_path']}")
    if args.out_trace_json:
        print(f"[OK] Trace JSON: {result['trace_json_path']}")
    return 0
