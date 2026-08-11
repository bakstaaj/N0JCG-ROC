#!/usr/bin/env python3
"""Exercise the allowlisted Gateway trial service controller."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from n0jcg_roc.operator_controls import set_trial_services_enabled


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", choices=("start", "stop"))
    parser.add_argument(
        "--socket",
        type=Path,
        default=Path("/run/n0jcg-operator-helper/control.sock"),
    )
    args = parser.parse_args()
    result = set_trial_services_enabled(args.state == "start", args.socket)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
