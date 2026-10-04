"""Zen's scoring rubric, read from the versioned file `evals/rubric.yaml` (never hardcoded).

    promo rubric <scores.yaml|.json|review.md> [--rubric evals/rubric.yaml] [--json]

`load()` returns the rubric dict; `evaluate(rubric, scores)` computes the verdict: PASS needs truth PASS, no criterion
under `pass.min_score` and an average of the scores >= `pass.min_average`. A scores file is YAML/JSON
    {hook: 4, legibility: 5, story: 4, pacing: 5, calm: 4, style: 4, polish: 4, truth: PASS}
(keys = criterion `key` or `name`, case-insensitive) or a review markdown in Zen's format (a `| Rubric | Score |` table
plus a `**Truth:** PASS` line, e.g. projects/commission-ai-anime/reviews/zen-v9.md).
Rubric path: an explicit argument, else $PROMO_RUBRIC, else <repo>/evals/rubric.yaml.
"""
from __future__ import annotations

import json
import os
import re
import sys

import yaml

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "evals", "rubric.yaml")


class RubricError(Exception):
    pass


def path_of(path=None):
    return path or os.environ.get("PROMO_RUBRIC") or DEFAULT_PATH


def load(path=None):
    p = path_of(path)
    if not os.path.exists(p):
        raise RubricError(f"rubric file not found: {p}")
    r = yaml.safe_load(open(p))
    crit = r.get("criteria") or []
    if not crit or any(not c.get("key") or not c.get("question") for c in crit):
        raise RubricError(f"{p}: every criterion needs key + question")
    ps = r.get("pass") or {}
    for k in ("min_average", "min_score", "truth"):
        if k not in ps:
            raise RubricError(f"{p}: pass.{k} missing")
    r["_path"] = p
    return r


def criteria(r):
    """[(name, question)] in rubric order (the BRIEF.md list)."""
    return [(c.get("name") or c["key"], c["question"]) for c in r["criteria"]]


def pass_text(r):
    ps = r["pass"]
    return ps.get("text") or (f"truth {ps['truth']}, no criterion under {ps['min_score']}, and an average of the "
                              f"{len(r['criteria'])} scores >= {ps['min_average']}.")


def _norm(k):
    return re.sub(r"[^a-z]", "", str(k).lower())


def parse_review_md(text):
    """Scores + truth from a review in Zen's markdown format."""
    out = {}
    for m in re.finditer(r"^\|\s*\**([A-Za-z][A-Za-z ]*?)\**\s*\|\s*\**([0-9.]+)\**\s*\|", text, flags=re.M):
        out[m.group(1).strip()] = float(m.group(2))
    t = re.search(r"\*\*Truth:?\*\*:?\s*\**(PASS|FAIL)", text, flags=re.I)
    if t:
        out["truth"] = t.group(1).upper()
    return out


def read_scores(path):
    txt = open(path).read()
    if path.lower().endswith(".md"):
        return parse_review_md(txt)
    d = json.loads(txt) if path.lower().endswith(".json") else yaml.safe_load(txt)
    return d.get("scores", d) if isinstance(d, dict) else d


def evaluate(r, scores):
    """dict(ok, verdict, average, scores, truth, problems). Missing or out-of-range scores are problems (FAIL)."""
    lo, hi = r.get("scale", {}).get("min", 1), r.get("scale", {}).get("max", 5)
    ps = r["pass"]
    by = {_norm(k): v for k, v in (scores or {}).items()}
    got, problems = {}, []
    for c in r["criteria"]:
        v = by.get(_norm(c["key"]), by.get(_norm(c.get("name", ""))))
        if v is None:
            problems.append(f"missing score: {c['key']}")
            continue
        v = float(v)
        if not lo <= v <= hi:
            problems.append(f"{c['key']} = {v:g} outside {lo}-{hi}")
        got[c["key"]] = v
    tkey = _norm((r.get("truth") or {}).get("key", "truth"))
    truth = str(by.get(tkey, "")).upper() or None
    avg = round(sum(got.values()) / len(got), 2) if got else None
    if truth != str(ps["truth"]).upper():
        problems.append(f"truth {truth or 'missing'} (needs {ps['truth']})")
    low = [k for k, v in got.items() if v < ps["min_score"]]
    if low:
        problems.append(f"under {ps['min_score']}: {', '.join(f'{k} {got[k]:g}' for k in low)}")
    if avg is not None and avg < ps["min_average"] - 1e-9:
        problems.append(f"average {avg:.2f} < {ps['min_average']}")
    ok = not problems
    return dict(ok=ok, verdict="PASS" if ok else "FAIL", average=avg, scores=got, truth=truth, problems=problems,
                rubric=dict(id=r.get("id"), version=r.get("version"), path=r.get("_path")))


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="promo rubric", description="PASS/FAIL of a scores file against evals/rubric.yaml")
    ap.add_argument("scores", help="scores .yaml/.json, or a review .md in Zen's format")
    ap.add_argument("--rubric", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        res = evaluate(load(a.rubric), read_scores(a.scores))
    except (RubricError, OSError, yaml.YAMLError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=1))
    else:
        print(" ".join(f"{k} {v:g}" for k, v in res["scores"].items()) + f" | truth {res['truth']} | average {res['average']}")
        print(f"{res['verdict']}" + (f": {'; '.join(res['problems'])}" if res["problems"] else "")
              + f"  (rubric {res['rubric']['id']} v{res['rubric']['version']})")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
