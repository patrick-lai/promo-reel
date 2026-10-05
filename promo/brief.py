"""The locked brief: what the person ASKED for, in their own words, and the references they gave.

    promo brief init    --project projects/<name> [--intent TEXT | --intent-file F] [--force]
    promo brief show    --project projects/<name> [--json]
    promo brief check   --project projects/<name> [--json]
    promo brief confirm --project projects/<name> --by NAME --hash H     (a HUMAN runs this; see below)
    promo brief conflict add|decide --project ...                        (record team-rule / reference conflicts and their decisions)

`projects/<name>/brief.yaml` is the one place the original request lives, verbatim. Every council round and every
`promo check` reads it again, so the cut is judged against the person's words and their references, never against an
agent's own summary of them (a style preset the agent wrote is NOT the reference).

    intent_verbatim   the user's exact request text, never paraphrased
    references        [{id, url|path, why: <the user's own words about it>, people: true|false (optional)}]
    must_have / must_not / deliverables   lists
    conflicts         [{what, rule, ref (optional reference id), decision: pending|<text>, decided_by}]
    confirmed         {by, at, hash}: hash of intent_verbatim + references + must_have + must_not

`confirm` records that the app owner / requester agreed this brief. It refuses unless the hash they pass equals the
current content hash (copy it from `brief show`, i.e. they looked at exactly this text), the brief has no structural
FAIL, and the name is not an agent's. An agent must NEVER run `confirm` on its own behalf: ask the human.

The gates (`promo check`, via `gates(spec)`): `brief` (FAIL: missing / empty intent / reference without `why` / conflict still
pending or decided by nobody; WARN: unconfirmed or edited since confirmation), `references` (dossiers complete, see
promo/refs.py) and `intent-review` (the newest `rounds/<n>/decision.md` carries an `intent-check:` line, see below).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys

import yaml

AGENT_NAMES = re.compile(r"\b(claude|agent|assistant|ai|bot|codex|gpt|gemini|grok|llm|council|lens)\b", re.I)
INTENT_RE = re.compile(r"^\s*[-*>\s]*intent-check:\s*(.*)$", re.I | re.M)
VERDICTS = ("YES", "PARTIAL", "NO")


class BriefError(Exception):
    pass


def brief_path(project_dir):
    return os.path.join(project_dir, "brief.yaml")


def exists(project_dir):
    return os.path.isfile(brief_path(project_dir))


def load(project_dir):
    p = brief_path(project_dir)
    if not os.path.isfile(p):
        raise BriefError(f"no brief at {p}: run `promo brief init --project {project_dir}`")
    b = yaml.safe_load(open(p)) or {}
    if not isinstance(b, dict):
        raise BriefError(f"{p}: not a mapping")
    return b


def save(project_dir, b):
    os.makedirs(project_dir, exist_ok=True)
    with open(brief_path(project_dir), "w") as f:
        yaml.safe_dump(b, f, sort_keys=False, allow_unicode=True, width=100)


def _ref_core(r):
    return {"id": r.get("id"), "url": r.get("url"), "path": r.get("path"), "why": (r.get("why") or "").strip()}


def content_hash(b):
    """sha256 of intent_verbatim + references + must_have + must_not (what `confirmed.hash` vouches for)."""
    core = {"intent_verbatim": (b.get("intent_verbatim") or "").strip(),
            "references": [_ref_core(r) for r in (b.get("references") or [])],
            "must_have": [str(x).strip() for x in (b.get("must_have") or [])],
            "must_not": [str(x).strip() for x in (b.get("must_not") or [])]}
    return hashlib.sha256(json.dumps(core, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def intent_sha(b):
    """Short hash of the verbatim request alone: what an `intent-check:` line in a round's decision.md must quote."""
    return hashlib.sha256((b.get("intent_verbatim") or "").strip().encode()).hexdigest()[:12]


# ---------------------------------------------------------------- commands
def init(project_dir, intent="", force=False):
    if exists(project_dir) and not force:
        raise BriefError(f"{brief_path(project_dir)} exists (use --force to overwrite; the old text is the user's)")
    b = {"intent_verbatim": (intent or "").strip(),
         "references": [], "must_have": [], "must_not": [], "deliverables": [], "conflicts": [],
         "confirmed": {"by": None, "at": None, "hash": None}}
    save(project_dir, b)
    return b


def structural_problems(b, project_dir=None):
    """[(status, msg)] for the `brief` gate (without the confirmation WARN)."""
    out = []
    if not (b.get("intent_verbatim") or "").strip():
        out.append(("FAIL", "intent_verbatim is empty: paste the user's exact request, unedited"))
    ids = set()
    for i, r in enumerate(b.get("references") or []):
        rid = r.get("id") or f"#{i + 1}"
        if not r.get("id"):
            out.append(("FAIL", f"reference #{i + 1} has no id"))
        elif rid in ids:
            out.append(("FAIL", f"reference id {rid!r} appears twice"))
        ids.add(rid)
        if not (r.get("url") or r.get("path")):
            out.append(("FAIL", f"reference {rid}: needs a url or path"))
        if not (r.get("why") or "").strip():
            out.append(("FAIL", f"reference {rid}: `why` is empty: write what the user said about it, in their words"))
    for i, c in enumerate(b.get("conflicts") or []):
        d = str(c.get("decision") or "pending").strip()
        what = str(c.get("what") or f"#{i + 1}")[:60]
        if d.lower() == "pending":
            out.append(("FAIL", f"conflict {i + 1} ({what}) is still pending: ask the user and record the decision"))
        elif not (c.get("decided_by") or "").strip():
            out.append(("FAIL", f"conflict {i + 1} ({what}) has a decision but no `decided_by`"))
    return out


def check(project_dir):
    """[(gate, status, msg)] for the `brief` gate."""
    try:
        b = load(project_dir)
    except BriefError as e:
        return [("brief", "FAIL", str(e))]
    probs = structural_problems(b, project_dir)
    if probs:
        fails = [m for s, m in probs if s == "FAIL"]
        return [("brief", "FAIL", "; ".join(fails))]
    cf = b.get("confirmed") or {}
    if not cf.get("hash"):
        return [("brief", "WARN", "brief not confirmed by a human yet (`promo brief confirm --by NAME --hash H`)")]
    if cf["hash"] != content_hash(b):
        return [("brief", "WARN", f"brief edited since {cf.get('by')} confirmed it ({cf.get('at')}): re-confirm")]
    return [("brief", "PASS", f"intent {intent_sha(b)}, {len(b.get('references') or [])} reference(s), "
                              f"{len(b.get('conflicts') or [])} conflict(s) decided; confirmed by {cf.get('by')} at {cf.get('at')}")]


def confirm(project_dir, by, hash_):
    b = load(project_dir)
    if not (by or "").strip() or AGENT_NAMES.search(by):
        raise BriefError(f"--by {by!r}: a human's name is required; an agent must never confirm the brief on its own")
    fails = [m for s, m in structural_problems(b, project_dir) if s == "FAIL"]
    if fails:
        raise BriefError("not confirmable yet: " + "; ".join(fails))
    cur = content_hash(b)
    if not hash_ or hash_ != cur:
        raise BriefError(f"hash mismatch: the brief you were shown is not this one (current {cur}); run `promo brief show` and pass its hash")
    b["confirmed"] = {"by": by.strip(), "at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "hash": cur}
    save(project_dir, b)
    return b["confirmed"]


def add_conflict(project_dir, what, rule, ref=None):
    b = load(project_dir)
    b.setdefault("conflicts", []).append({"what": what, "rule": rule, **({"ref": ref} if ref else {}),
                                          "decision": "pending", "decided_by": None})
    save(project_dir, b)
    return len(b["conflicts"])


def decide_conflict(project_dir, n, decision, by):
    b = load(project_dir)
    cs = b.get("conflicts") or []
    if not 1 <= n <= len(cs):
        raise BriefError(f"no conflict {n} (have {len(cs)})")
    if not (by or "").strip() or AGENT_NAMES.search(by):
        raise BriefError("--by must be the human who decided; an agent records only what the user told it, under the user's name")
    cs[n - 1]["decision"] = decision
    cs[n - 1]["decided_by"] = by.strip()
    save(project_dir, b)
    return cs[n - 1]


def show_text(project_dir):
    b = load(project_dir)
    L = ["INTENT (verbatim; re-read it before judging anything):", "", *("  " + ln for ln in (b.get("intent_verbatim") or "").splitlines()), ""]
    for r in b.get("references") or []:
        L.append(f"REFERENCE {r.get('id')}: {r.get('url') or r.get('path')}\n  why: {r.get('why')}")
    for k in ("must_have", "must_not", "deliverables"):
        if b.get(k):
            L += ["", k.upper() + ":"] + [f"  - {x}" for x in b[k]]
    if b.get("conflicts"):
        L += ["", "CONFLICTS:"]
        for i, c in enumerate(b["conflicts"], 1):
            L.append(f"  {i}. {c.get('what')}  [rule: {c.get('rule')}]  -> {c.get('decision')} ({c.get('decided_by') or '-'})")
    cf = b.get("confirmed") or {}
    L += ["", f"content hash (pass to `confirm --hash`): {content_hash(b)}",
          f"confirmed: {cf.get('by') or 'NO'} {cf.get('at') or ''}",
          "", "decision.md line for the intent lens (fill the verdict and scores; quote the sha as is):",
          f"  intent-check: intent_sha={intent_sha(b)} verdict=<YES|PARTIAL|NO> intent=<1-5> reference=<1-5> lens=intent-reference"]
    return "\n".join(L)


# ---------------------------------------------------------------- intent-review gate (rounds/<n>/decision.md)
def rounds(project_dir):
    d = os.path.join(project_dir, "rounds")
    if not os.path.isdir(d):
        return []
    nums = sorted((int(x) for x in os.listdir(d) if x.isdigit() and os.path.isdir(os.path.join(d, x))))
    return [(n, os.path.join(d, str(n))) for n in nums]


def parse_intent_check(text):
    """dict(sha, verdict, scores{}) of the LAST `intent-check:` line in a decision.md, or None."""
    ms = INTENT_RE.findall(text or "")
    if not ms:
        return None
    line = ms[-1]
    sha = re.search(r"intent_sha\s*[=:]\s*([0-9a-f]{8,64})", line, re.I)
    ver = re.search(r"verdict\s*[=:]\s*(YES|PARTIAL|NO)\b", line, re.I)
    sc = {k.lower(): float(v) for k, v in re.findall(r"\b(intent|reference)\s*[=:]\s*([0-9](?:\.[0-9]+)?)", line, re.I)}
    return dict(sha=sha.group(1).lower() if sha else None, verdict=ver.group(1).upper() if ver else None, scores=sc, line=line.strip())


def intent_review(project_dir, b=None):
    """[(gate, status, msg)]: the newest round's decision.md must hold a valid `intent-check:` line."""
    try:
        b = b or load(project_dir)
    except BriefError as e:
        return [("intent-review", "FAIL", str(e))]
    rs = rounds(project_dir)
    if not rs:
        return [("intent-review", "WARN", "no rounds/<n>/decision.md yet: every review round must end with an `intent-check:` line "
                                          "from the Intent & Reference lens (evals/council.md)")]
    n, d = rs[-1]
    p = os.path.join(d, "decision.md")
    if not os.path.isfile(p):
        return [("intent-review", "FAIL", f"rounds/{n}/decision.md is missing")]
    ic = parse_intent_check(open(p).read())
    want = intent_sha(b)
    if ic is None:
        return [("intent-review", "FAIL", f"rounds/{n}/decision.md has no `intent-check:` line (intent_sha={want}, verdict from the "
                                          f"Intent & Reference lens): the round was not judged against the user's words")]
    if not ic["sha"] or not (want.startswith(ic["sha"]) or ic["sha"].startswith(want)):
        return [("intent-review", "FAIL", f"rounds/{n}: intent-check quotes intent_sha={ic['sha']}, the brief's is {want}: the lens read a different text")]
    if ic["verdict"] is None:
        return [("intent-review", "FAIL", f"rounds/{n}: intent-check has no `verdict=YES|PARTIAL|NO`")]
    hard = {}
    try:
        from . import rubric as RB
        hard = RB.load().get("pass", {}).get("hard_min") or {}
    except Exception:  # noqa: BLE001
        pass
    low = [f"{k} {ic['scores'][k]:g} < {v}" for k, v in hard.items() if k in ic["scores"] and ic["scores"][k] < v]
    if ic["verdict"] == "NO" or low:
        return [("intent-review", "FAIL", f"rounds/{n}: the person would NOT say yes ({ic['verdict']}" + (f"; {'; '.join(low)}" if low else "") + ")")]
    if ic["verdict"] == "PARTIAL":
        return [("intent-review", "WARN", f"rounds/{n}: intent lens verdict PARTIAL: not shippable until YES")]
    return [("intent-review", "PASS", f"rounds/{n}: intent lens verdict YES (intent_sha {want})")]


def gates(spec):
    """Project-level gates for `promo check`: [(gate, status, msg)]. A project without brief.yaml WARNs, or FAILs with
    `style.require_brief: true`."""
    d = spec.root
    if not exists(d):
        st = "FAIL" if (spec.style or {}).get("require_brief") else "WARN"
        return [("brief", st, f"no brief.yaml in {d}: `promo brief init --project {d}` with the user's exact words, then `promo refs add` "
                              f"each reference" + (" (style.require_brief is set)" if st == "FAIL" else ""))]
    from . import refs
    b = load(d)
    return check(d) + refs.check(d, b) + intent_review(d, b)


# ---------------------------------------------------------------- CLI
def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="promo brief", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, h):
        p = sub.add_parser(name, help=h)
        p.add_argument("--project", required=True, help="project dir, e.g. projects/<name>")
        return p
    i = add("init", "create brief.yaml with the user's exact words")
    i.add_argument("--intent", default="", help="the user's request, verbatim")
    i.add_argument("--intent-file", help="file holding the request verbatim")
    i.add_argument("--force", action="store_true")
    for nm, h in (("show", "print the brief (re-read before every round)"), ("check", "brief gates: FAIL/WARN list")):
        p = add(nm, h)
        p.add_argument("--json", action="store_true")
    c = add("confirm", "HUMAN ONLY: record that the requester confirmed this exact brief")
    c.add_argument("--by", required=True)
    c.add_argument("--hash", help="content hash printed by `brief show`")
    cf = sub.add_parser("conflict", help="record / decide a conflict (team rule vs reference vs request)")
    cs = cf.add_subparsers(dest="ccmd", required=True)
    ca = cs.add_parser("add")
    ca.add_argument("--project", required=True)
    ca.add_argument("--what", required=True)
    ca.add_argument("--rule", required=True, help="the team rule / constraint it collides with, e.g. 'AGENTS.md 0.1 real footage only'")
    ca.add_argument("--ref", help="reference id it came from")
    cd = cs.add_parser("decide")
    cd.add_argument("--project", required=True)
    cd.add_argument("n", type=int)
    cd.add_argument("--decision", required=True, help="what the user decided, in their words")
    cd.add_argument("--by", required=True, help="the human who decided")
    a = ap.parse_args(argv)
    pd = a.project
    try:
        if a.cmd == "init":
            intent = open(a.intent_file).read() if a.intent_file else a.intent
            init(pd, intent, a.force)
            print(f"wrote {brief_path(pd)}" + ("" if intent.strip() else " (intent_verbatim is EMPTY: paste the user's exact words)"))
        elif a.cmd == "show":
            if a.json:
                b = load(pd)
                print(json.dumps(dict(brief=b, content_hash=content_hash(b), intent_sha=intent_sha(b)), indent=1, ensure_ascii=False))
            else:
                print(show_text(pd))
        elif a.cmd == "check":
            from . import refs
            rows = check(pd)
            if exists(pd):
                b_ = load(pd)
                rows += refs.check(pd, b_) + intent_review(pd, b_)
            if a.json:
                print(json.dumps(dict(ok=not any(s == "FAIL" for _, s, _ in rows), results=[dict(gate=g, status=s, msg=m) for g, s, m in rows]), indent=1))
            else:
                for g, s, m in rows:
                    print(f"{s:<4}  {g:<14} {m}")
            return 1 if any(s == "FAIL" for _, s, _ in rows) else 0
        elif a.cmd == "confirm":
            cf_ = confirm(pd, a.by, a.hash)
            print(f"confirmed by {cf_['by']} at {cf_['at']} (hash {cf_['hash'][:12]})")
        elif a.cmd == "conflict":
            if a.ccmd == "add":
                print(f"conflict {add_conflict(pd, a.what, a.rule, a.ref)} recorded as pending: ASK THE USER, then `conflict decide`")
            else:
                c_ = decide_conflict(pd, a.n, a.decision, a.by)
                print(f"conflict {a.n}: {c_['decision']} ({c_['decided_by']})")
    except BriefError as e:
        print(f"promo brief: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
