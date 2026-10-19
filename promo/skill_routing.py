"""Route a brief to one primary skill. Catalog is skills/*/skill.yaml; SKILL.md is not read here.
Score = hint hits on prompt tokens; a skill-id token counts 2. Floor 1.5. Ties follow catalog order
(promo-reel, then id). Below the floor: first primary whose formats include format, else promo-reel.
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import yaml

FLOOR = 1.5
STOP = frozenset("a an the and or of for to in on with from by at as is it be this that these those my our your their we you into over about than then so if but not do make using use via per its are was were how what when where who which will just also can".split())
_WORD = re.compile(r"[a-z0-9]+")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def _words(text):
    return _WORD.findall((text or "").lower())

def load_catalog():
    """Skills in catalog order. Does not open skill_md."""
    out, base = [], os.path.join(_ROOT, "skills")
    for name in sorted(os.listdir(base)):
        path = os.path.join(base, name, "skill.yaml")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            doc = yaml.safe_load(f) or {}
        doc.setdefault("id", name)
        doc.setdefault("primary", True)
        out.append(doc)
    out.sort(key=lambda s: (s["id"] != "promo-reel", s["id"]))
    return out

def _fmt(value):
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-") if value else None

def _formats(skill):
    return [f for f in (_fmt(x) for x in skill.get("formats") or []) if f]

def _extras(platform, length):
    extra = ["x"] if str(platform or "").strip().lower() == "x" else []
    m = re.search(r"\d+(?:\.\d+)?", str(length)) if length is not None and str(length).strip() else None
    if m and float(m.group(0)) <= 30:
        extra.append("clip")
    return extra

def _score(skill, prompt, extras):
    bag = _words(prompt) + list(extras)
    text, content = " ".join(bag), [w for w in bag if w not in STOP and (len(w) > 1 or w == "x")]
    seen, total, hits, names = set(), 0.0, [], set(_words(skill.get("id", "")))
    for t in content:
        if t in names and t not in seen:
            seen.add(t)
            total += 2.0
            hits.append(t)
    hints = sorted(skill.get("hints") or [], key=lambda h: (-len(_words(str(h))), str(h)))
    for hint in hints:
        hw = _words(str(hint))
        phrase = " ".join(hw)
        if not hw or any(w in seen for w in hw):
            continue
        if (len(hw) == 1 and hw[0] in content) or (len(hw) > 1 and phrase in text):
            seen.update(hw)
            total += 1.0
            hits.append(phrase)
    return total, hits

def _helpers(skill, prompt):
    pid = skill["id"]
    found = [str(h) for h in (skill.get("companions") or [])]
    if "render" in (skill.get("outputs") or []):
        found.append("previz")
    text = " " + " ".join(_words(prompt)) + " "
    if pid != "cinetic" and any(f" {w} " in text for w in ("sound", "sfx", "audio")):
        found.append("cinetic")
    return sorted({h for h in found if h and h != pid})

def route(prompt, format=None, platform=None, length=None):
    """{primary, helpers, reason}. Primary skills only; a known format narrows the pool."""
    catalog, fmt = load_catalog(), _fmt(format)
    pool = [s for s in catalog if s.get("primary", True)]
    if fmt:
        narrowed = [s for s in pool if fmt in _formats(s)]
        pool = narrowed or pool
    extras = _extras(platform, length)
    ranked = [(*_score(s, prompt or "", extras), i, s) for i, s in enumerate(pool)]
    score, hits, _, skill = max(ranked, key=lambda r: (r[0], -r[2]))
    if score >= FLOOR:
        reason = f"{skill['id']} score {score:g} ({', '.join(hits)}) >= {FLOOR:g}"
    else:
        skill = next((s for s in catalog if s.get("primary", True) and fmt and fmt in _formats(s)), None)
        if skill:
            reason = f"no score >= {FLOOR:g}; first skill with format {fmt}"
        else:
            skill = next(s for s in catalog if s["id"] == "promo-reel")
            reason = f"no score >= {FLOOR:g}; fallback promo-reel"
    return {"primary": skill["id"], "helpers": _helpers(skill, prompt or ""), "reason": reason}

def _show(result):
    helpers = ", ".join(result["helpers"]) if result["helpers"] else "-"
    print(f"primary: {result['primary']}\nhelpers: {helpers}\nreason: {result['reason']}")

def main(argv=None):
    ap = argparse.ArgumentParser(prog="promo skills", description="Skill catalog and routing")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list catalog skills")
    rt = sub.add_parser("route", help="pick a primary skill and helpers for a prompt")
    rt.add_argument("prompt")
    rt.add_argument("--format")
    rt.add_argument("--platform")
    rt.add_argument("--length")
    rt.add_argument("--project", help="project directory or promo.yaml")
    rt.add_argument("--write", action="store_true", help="set skills: {primary, helpers} in DIR/promo.yaml")
    rt.add_argument("--reroute", action="store_true", help="replace skills already written")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for s in load_catalog():
            kind = "primary" if s.get("primary", True) else "helper"
            print(f"{s['id']}\t{kind}\t{','.join(s.get('formats') or []) or '-'}\t{s.get('description', '')}")
        return 0
    result = route(args.prompt, format=args.format, platform=args.platform, length=args.length)
    if not args.write:
        _show(result)
        return 0
    path = args.project
    if path and os.path.isdir(path):
        path = os.path.join(path, "promo.yaml")
    if not path or not os.path.isfile(path):
        print("promo: error: --write needs --project DIR with a promo.yaml", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        print(f"promo: error: {path} is not a mapping", file=sys.stderr)
        return 2
    if data.get("skills") and not args.reroute:
        cur = data["skills"] or {}
        print(f"skills already set in {path} (pass --reroute to replace)")
        _show({"primary": cur.get("primary"), "helpers": list(cur.get("helpers") or []), "reason": "existing"})
        return 0
    data["skills"] = {"primary": result["primary"], "helpers": list(result["helpers"])}
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    _show(result)
    print(f"wrote {path}")
    return 0
