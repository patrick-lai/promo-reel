"""A reviewer from a second model family: the judge checks of a draft are put to the grok CLI (headless) with the draft's scene stills,
and its answers are recorded as marks of family `grok` beside the council's. A judge check passes only when no family that looked says it
fails, so a blind spot the council's own family shares does not slip through. The control check goes to it too.

    promo flow second-opinion [--draft N] [--provider grok] [--dry-run]
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import flow as F
from . import flowcheck as FC
from . import genvideo as GV

TIMEOUT_S = 900


def stills(pd, st, n):
    """One still per scene at its middle, from the draft itself: {scene id: path}."""
    from . import watch as W
    d = os.path.join(F.fdir(pd), "second", f"d{n}")
    os.makedirs(d, exist_ok=True)
    out = {}
    for _, b, _ in F.boards(pd, st):
        for s in b.get("scenes") or []:
            p = os.path.join(d, f"scene-{s['id']}.jpg")
            if os.path.isfile(p) or W.grab(Path(st["drafts"][n - 1]["file"]), (float(s["t"][0]) + float(s["t"][1])) / 2, Path(p), 960):
                out[str(s["id"])] = p
    return out


def prompt(st, checks, shots):
    L = ["You review one cut of a product promo. Look at the image files listed (read each file), then judge each statement below as true or",
         "false for what the stills show. Do not guess from the wording: if the stills do not show it, answer \"unsure\".", "",
         "The request the video answers: " + " ".join(st["intent"].split()), "", "Stills (one per scene, from the middle of the scene):"]
    L += [f"- scene {k}: {v}" for k, v in shots.items()]
    L += ["", "Statements:"]
    L += [f"- {c['id']}: " + (f"(scene {c['scene']}) " if c.get("scene") else "(whole video) ") + c["what"] for c in checks]
    L += ["", "Answer with one JSON object per line and nothing else:",
          '{"id": "<statement id>", "status": "pass" | "fail" | "unsure", "evidence": "<what in which still shows it>"}']
    return "\n".join(L)


def _ask(provider, text):
    r = subprocess.run(GV.argv_for(provider, text), capture_output=True, text=True, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise F.FlowError(f"{provider['id']} did not answer (exit {r.returncode}): {(r.stderr or r.stdout).strip()[-300:]}")
    return r.stdout


def run(pd, n=None, provider="grok", dry_run=False, ask=None):
    st = F.load(pd)
    n, _ = FC.draft_of(st, n)
    checks = FC.judge_checks(st)
    if not checks:
        raise F.FlowError("no judge checks to put to a second reviewer yet")
    text = prompt(st, checks, stills(pd, st, n))
    if dry_run:
        return text, 0
    p = next((x for x in GV.detect() if x["id"] == provider), None)
    if not p or not p["available"]:
        raise F.FlowError(f"{provider} is not available on this machine (`promo gen detect`)")
    said = (ask or _ask)(p, text)
    known = {c["id"] for c in checks}
    lines = []
    for line in said.splitlines():
        line = line.strip().strip(",")
        if not line.startswith("{"):
            continue
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        if m.get("id") in known and m.get("status") in ("pass", "fail") and (m.get("evidence") or "").strip():
            lines.append(json.dumps(dict(id=m["id"], status=m["status"], evidence=m["evidence"])))
    if not lines:
        raise F.FlowError(f"{provider} answered, but with no usable line (one JSON object per statement)")
    tmp = os.path.join(F.fdir(pd), "second", f"d{n}", f"{provider}-marks.jsonl")
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    return text, FC.marks(pd, tmp, n, provider, by=f"{provider} second opinion")
