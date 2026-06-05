from __future__ import annotations

import argparse
from pathlib import Path

from ..strategy import run_e2e


def cmd_e2e_test(args: argparse.Namespace) -> int:
    package_file = Path(__file__).resolve()
    project_root = package_file.parents[3]
    result = run_e2e(project_root, args.out_csv, args.out_debug_json, args.out_trace_json, args.debug)
    print(f"[OK] E2E passed. CSV: {result['csv_path']}")
    if args.out_debug_json:
        print(f"[OK] E2E debug JSON: {result['debug_json_path']}")
    if args.out_trace_json:
        print(f"[OK] E2E trace JSON: {result['trace_json_path']}")
    return 0
