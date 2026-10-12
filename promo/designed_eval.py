"""Eval of the thin-prompt -> designed-plan path (evals/thin-prompt-designed.yaml, evals/thin-prompt-designed.md).

    promo designed eval [--case evals/thin-prompt-designed.yaml] [--stills a.png b.png ...] [--json]

Runs each case through `promo plan` in a scratch project and asserts, with no model in the loop, that the plan:
  * has the designed composition fields (framing per shot, kinetic cards, plates, length band, spine, type style, montage, needs),
  * makes floating panels the primary framing and keeps fullscreen to real footage and a small share,
  * picks the craft dialect the case expects (ethereal unless the words or the flag say kinetic) and follows its rules (ethereal: no
    fullscreen, long holds, no accelerating recap, no VO; kinetic: fast recap, VO reads the cards),
  * asks at most three co-spec questions,
  * puts only the person's own words on cards and invents no claim, number, URL, feature or reference asset.
A model judge (Sonnet) then scores what no assertion can: evals/thin-prompt-designed.md. Cases without real stills get small
synthetic placeholders (a plan never reads the pixels), so this runs on any box; pass `--stills` to use the real ones.
"""
from __future__ import annotations

import json
import os
import re
import tempfile

import yaml

from . import cospec as CS
from . import designed as D
from . import gapfill

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CASE = os.path.join(ROOT, "evals", "thin-prompt-designed.yaml")
SIZES = {"landscape": (960, 540), "portrait": (300, 650), "square": (600, 600)}


def _placeholders(dest, specs):
    from PIL import Image
    paths = []
    for name, kind in specs:
        p = os.path.join(dest, f"{name}.png")
        Image.new("RGB", SIZES.get(kind, SIZES["landscape"]), (30, 34, 48)).save(p)
        paths.append(p)
    return paths


def _walk_text(node, out):
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("prompt", "reference", "cospec"):      # the person's own words, the reference's numbers and the questions are not output text
                continue
            _walk_text(v, out)
    elif isinstance(node, (list, tuple)):
        for v in node:
            _walk_text(v, out)
    elif isinstance(node, str):
        out.append(node)


def check_case(plan, case):
    """[(check, ok, msg)] for one plan against one case."""
    res = []

    def ok(name, cond, msg):
        res.append((name, bool(cond), msg))
    des = plan.get("designed") or {}
    ok("designed-present", des.get("enabled") is True, "plan.designed is on for a thin prompt with stills")
    for key in ("shots", "kinetic_cards", "plates", "length_band", "spine", "type_style", "framing_hierarchy", "montage", "needs", "stills"):
        ok(f"field-{key}", des.get(key) not in (None, ""), f"designed.{key} is filled")
    shots = des.get("shots") or []
    ok("framing-values", all(r.get("framing") in D.FRAMINGS for r in shots), f"every shot has a framing in {D.FRAMINGS}")
    counts = (des.get("framing_hierarchy") or {}).get("counts") or {}
    ui = sum(v for k, v in counts.items() if k != "plate")
    ok("floating-primary", ui and counts.get("floating", 0) > ui / 2, f"floating {counts.get('floating', 0)} of {ui} UI shots")
    dn = (des.get("dialect") or {}).get("name")
    if case.get("expect_dialect"):
        ok("dialect-expected", dn == case["expect_dialect"], f"dialect {dn!r} ({(des.get('dialect') or {}).get('source')}), expected {case['expect_dialect']!r}")
    ok("dialect-known", dn in D.DIALECT_NAMES, f"dialect is one of {D.DIALECT_NAMES}")
    has_video = any(s.get("kind") == "video" for s in des.get("stills") or [])
    ok("fullscreen-earned", counts.get("fullscreen", 0) == 0 or (has_video and counts["fullscreen"] <= max(2, ui // 4)),
       f"fullscreen {counts.get('fullscreen', 0)} (only real footage, at most a quarter)")
    ok("every-beat", {r["beat"] for r in shots} >= set(D.P.SHOT_BEATS), "all five beats have a shot")
    ok("seconds-add-up", abs(sum(r["seconds"] for r in shots) - plan["length"]["master_s"]) < 0.05,
       f"shots sum to {sum(r['seconds'] for r in shots):.2f}s of {plan['length']['master_s']}s")
    pay = [r["seconds"] for r in shots if r["beat"] == "payoff"]
    if dn == "kinetic" and (des.get("length_band") or {}).get("recap_montage") and len(pay) > 2:
        ok("montage-accelerates", all(a >= b - 1e-6 for a, b in zip(pay, pay[1:])) and pay[0] > pay[-1],
           "recap shots get shorter " + " ".join(f"{x:g}" for x in pay))
    if dn == "ethereal":
        secs = sorted(r["seconds"] for r in shots)
        med = secs[len(secs) // 2]
        ok("ethereal-fullscreen-none", counts.get("fullscreen", 0) == 0, "no fullscreen app chrome")
        ok("ethereal-holds", med >= D.DIALECTS["ethereal"]["pacing"]["median_shot_min_s"], f"median shot {med:g}s")
        ok("ethereal-no-recap-burst", not (des.get("montage") or {}).get("accelerates"), "the payoff holds, no accelerating montage")
        ok("ethereal-music-led", (des.get("audio") or {}).get("vo") is False and (des.get("audio") or {}).get("music_led") is True, "music-led, no VO")
        cards = des.get("kinetic_cards") or []
        ok("ethereal-type", all(not c.get("vo") and c.get("anim") in ("snap", "cascade") for c in cards), "cards snap or cascade; no VO line")
        ok("ethereal-conflict-noted", any(c.get("id") == "abstracted-ui-vs-rule-1" for c in des.get("conflicts") or []),
           "the abstracted-UI vs rule 1 question is recorded for the person")
    for key, want in (case.get("defaults") or {}).items():
        ok(f"default-{key}", any(c.get("text") and D._norm(want).startswith(D._norm(c["text"])) and c.get("source") == "team-default"
                                 for c in des.get("kinetic_cards") or []) and any(n["kind"] == "confirm" for n in des.get("needs") or []),
           f"team default {key} reaches the end card and is flagged for the product owner to confirm")
    cos = plan.get("cospec") or {}
    ok("cospec-max-3", len(cos.get("open") or []) <= CS.MAX_QUESTIONS == 3, f"{len(cos.get('open') or [])} open questions (max {CS.MAX_QUESTIONS})")
    if case.get("expect_questions") is not None:
        got = [q["key"] for q in cos.get("open") or []]
        ok("cospec-keys", got == case["expect_questions"], f"asks {got}, expected {case['expect_questions']}")
    answers = cos.get("answers") or {}
    defaults = cos.get("defaults") or {}
    bad = D.check_no_invention(des, plan.get("prompt", ""), answers, defaults)
    ok("no-invented-words", not bad, "; ".join(bad) or "every card is the person's own words; plates are guarded")
    ok("plates-ui-free", all(p.get("ui") is False and D.PLATE_GUARD in p.get("prompt", "") for p in des.get("plates") or []),
       "every plate is ui: false with the no-text / no-UI guard")
    out = []
    _walk_text({k: v for k, v in plan.items() if k != "prompt"}, out)
    blob = " ".join(out).lower()
    prompt_low = plan.get("prompt", "").lower() + " " + " ".join(str(v) for v in list(answers.values()) + list(defaults.values())).lower()
    leaked = [w for w in case.get("never_in_plan", []) if w.lower() in blob and w.lower() not in prompt_low]
    ok("no-invented-claims", not leaked, f"none of {case.get('never_in_plan', [])} appear" if not leaked else f"found {leaked}")
    ok("no-urls", not D._URL.search(" ".join(c.get("text") or "" for c in des.get("kinetic_cards") or [])), "no URL on any card")
    for want in case.get("cards_include", []):
        ok(f"card-{want}", any(D._norm(want) in D._norm(c.get("text") or "") for c in des.get("kinetic_cards") or []),
           f"a card carries {want!r}")
    ok("needs-listed", any(n["kind"] == "copy" for n in des.get("needs") or []) or all(c["status"] == "ready" for c in des["kinetic_cards"]),
       "a beat with no words of the person's is listed as needs-copy, not filled")
    return res


def run_case(case, stills=None):
    with tempfile.TemporaryDirectory() as d:
        paths = stills or _placeholders(d, [(s["name"], s.get("shape", "landscape")) for s in case["stills"]])
        info = gapfill.apply(os.path.join(d, "proj"), case["prompt"], name="eval", stills=paths, dialect=case.get("dialect"),
                             defaults=case.get("defaults"), answers=case.get("answers"))
        results = check_case(info["plan"], case)
        # the compiled shots must also load as a real spec
        try:
            applied = D.apply_shots(info["path"])
            from .spec import load_spec
            spec = load_spec(info["path"], plugins=False)
            results.append(("compiles", len(spec.shots) == len(applied["shots"]), f"{len(spec.shots)} cinema shots load as a spec"))
            gates = {g: (s, m) for g, s, m in D.gates(spec)}
            results.append(("gates", all(s != "FAIL" for s, _ in gates.values()), "; ".join(f"{g} {s}" for g, (s, _m) in gates.items())))
        except SystemExit as e:
            results.append(("compiles", False, str(e)))
    return results


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="promo designed eval")
    ap.add_argument("--case", default=DEFAULT_CASE)
    ap.add_argument("--stills", nargs="+", help="real stills to use instead of synthetic placeholders (first case only)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cases = yaml.safe_load(open(a.case))["cases"]
    allres, failed = {}, 0
    for i, case in enumerate(cases):
        res = run_case(case, a.stills if i == 0 else None)
        allres[case["id"]] = [dict(check=n, ok=o, msg=m) for n, o, m in res]
        failed += sum(1 for _n, o, _m in res if not o)
    if a.json:
        print(json.dumps(dict(ok=failed == 0, failed=failed, cases=allres), indent=1))
    else:
        for cid, rows in allres.items():
            print(f"== {cid}")
            for r in rows:
                print(f"  {'PASS' if r['ok'] else 'FAIL'}  {r['check']:<22} {r['msg']}")
        print("OK" if not failed else f"{failed} check(s) failed")
    return 1 if failed else 0


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
