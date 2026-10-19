#!/usr/bin/env python3
"""Print brief|picked|expected|PASS/FAIL for evals/skill-routing.yaml. Exit 1 if any fail."""
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from promo.skill_routing import route  # noqa: E402


def main():
    path = os.path.join(ROOT, "evals", "skill-routing.yaml")
    with open(path, encoding="utf-8") as f:
        cases = (yaml.safe_load(f) or {}).get("cases") or []
    failed = 0
    for case in cases:
        got = route(case.get("prompt") or "", format=case.get("format"),
                    platform=case.get("platform"), length=case.get("length"))
        picked, expected = got["primary"], case.get("expected")
        ok = picked == expected
        failed += not ok
        print(f"{case.get('id') or case.get('prompt')}|{picked}|{expected}|{'PASS' if ok else 'FAIL'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
