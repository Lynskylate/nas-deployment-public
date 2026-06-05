from __future__ import annotations

import argparse
import json

from ..providers import ProviderRouter
from ..strategy import REQUIRED_FIELDS
from ..utils import dataclass_to_dict


def cmd_probe_providers(args: argparse.Namespace) -> int:
    router = ProviderRouter()
    print(json.dumps(router.probe(), ensure_ascii=False, indent=2))
    if args.ticker:
        outcome = router.fetch_fields(args.ticker, args.market, REQUIRED_FIELDS)
        print(json.dumps(dataclass_to_dict(outcome), ensure_ascii=False, indent=2))
    return 0
