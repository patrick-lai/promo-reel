"""Config-driven claims: card / caption text chosen by what the footage legibly shows.

Team rule: no number on screen that the frame does not show. A claim table picks its line from a *legibility record*
(what the capturing agent wrote in the footage manifest.md for the shot), so the text can never outrun the frame.

    claims:
      legible:                                   # one record per evidence shot; null = not captured / not checked yet
        shot11_legible: {cards: null, logos: null}
      tables:
        merged_count:                            # reusable: the anime peak card and the hero caption both use it
          selector: shot11_legible
          evidence: {manifest: /abs/footage/manifest.md, section: "Shot 11"}
          rows:                                  # first row whose every count matches exactly wins; last row = no numbers
            - {cards: 8, logos: 3, text: "8 TASKS · 3 AGENTS · ALL MERGED"}
            - {logos: 3, text: "3 AGENTS · ALL MERGED"}
            - {cards: 8, text: "8 TASKS · ALL MERGED"}
            - {text: "ALL MERGED."}
        plan_count:
          selector: shot11_legible
          rows:
            - {cards: 8, text: "8 TASKS."}
            - {text: "THE PLAN.", confirm: "Marketing"}   # softened fallback, NOT final copy: flagged until confirmed

A row's `confirm: <who>` marks provisional copy: while that row is selected, the claims gate WARNs that <who> must confirm
the line (and critique packs flag it). Remove `confirm` once the line is signed off.
A card/caption uses `text_from: claims.merged_count` instead of literal text. `promo check` (gate `claims`) fails if a
selected line has a digit that is not one of the legible counts it was selected on, if a table has no number-free
fallback row, or if the manifest section names counts that disagree with the legibility record.
"""
from __future__ import annotations

import os
import re

COUNT_WORDS = {"cards": r"(\d+)\s+(?:task\s+|ticket\s+)?cards?|(\d+)\s+in\s+this\s+run\b",   # board header '8 in this run'
               "logos": r"(\d+)\s+(?:agent\s+)?logos?", "tasks": r"(\d+)\s+tasks?", "agents": r"(\d+)\s+agents?"}


META = ("text", "note", "confirm")       # row keys that are not count conditions


class ClaimError(Exception):
    pass


def select(rows, legible):
    """Pick the first row whose every count key equals the legible value. Rows without count keys always match.
    `legible` values of None (unknown) never match a count, so an uncaptured shot falls through to the number-free row."""
    legible = legible or {}
    for r in rows:
        conds = {k: v for k, v in r.items() if k not in META}
        if all(legible.get(k) is not None and int(legible[k]) == int(v) for k, v in conds.items()):
            return r
    raise ClaimError("no claim row matches and there is no number-free fallback row")


def table(raw, name):
    t = ((raw.get("claims") or {}).get("tables") or {}).get(name)
    if t is None:
        raise ClaimError(f"unknown claim table {name!r}")
    return t


def legible_for(raw, t):
    sel = t.get("selector")
    return ((raw.get("claims") or {}).get("legible") or {}).get(sel) if sel else {}


def resolve(raw, ref):
    """'claims.<table>' -> (text, info dict)."""
    name = ref.split(".", 1)[1] if ref.startswith("claims.") else ref
    t = table(raw, name)
    leg = legible_for(raw, t)
    row = select(t["rows"], leg)
    return row["text"], dict(table=name, selector=t.get("selector"), legible=leg, row=row)


def text_of(raw, cfg):
    """Literal `text`, or the claim line named by `text_from`."""
    if cfg.get("text_from"):
        return resolve(raw, cfg["text_from"])[0]
    return cfg["text"]


def manifest_counts(path, section):
    """Counts written in a footage manifest.md section ('### Shot 11 ...' up to the next '### '): {key: int}. None if absent.
    `section` may name a full heading such as 'Shot 11 (header counts)' to pick one of several takes of a shot."""
    if not path or not os.path.exists(path):
        return None
    txt = open(path).read()
    m = re.search(rf"^###\s+{re.escape(section)}(?!\w).*?$(.*?)(?=^###\s|\Z)", txt, flags=re.M | re.S)
    if not m:
        return None
    body = m.group(1)
    legm = re.search(r"legible[^\n]*", body, flags=re.I)
    scope = legm.group(0) if legm else body
    out = {}
    for k, rx in COUNT_WORDS.items():
        mm = re.search(rx, scope, flags=re.I)
        if mm:
            out[k] = int(next(g for g in mm.groups() if g is not None))
    return out


def audit(raw, resolve_path=lambda p: p):
    """List of (status, msg) for the claims gate."""
    res = []
    cl = raw.get("claims") or {}
    for name, t in (cl.get("tables") or {}).items():
        rows = t.get("rows") or []
        if not rows or any(set(r) - set(META) for r in rows[-1:]) or re.search(r"\d", rows[-1].get("text", "")):
            res.append(("FAIL", f"claim table {name}: last row must be a number-free fallback with no count conditions"))
        for r in rows:
            nums = {int(x) for x in re.findall(r"\d+", r.get("text", ""))}
            conds = {int(v) for k, v in r.items() if k not in META}
            if nums - conds:
                res.append(("FAIL", f"claim table {name}: row {r.get('text')!r} shows {sorted(nums - conds)} without a matching legible-count condition"))
        leg = legible_for(raw, t) or {}
        try:
            row = select(rows, leg)
        except ClaimError as e:
            res.append(("FAIL", f"claim table {name}: {e}"))
            continue
        ev = t.get("evidence") or {}
        mc = manifest_counts(resolve_path(ev["manifest"]), ev.get("section", "")) if ev.get("manifest") else None
        if all(v is None for v in leg.values()) or not leg:
            res.append(("WARN", f"claim table {name}: {t.get('selector')} not filled in (evidence shot not captured or not checked); "
                                f"showing the number-free fallback {row['text']!r}"))
        if mc:
            bad = {k: (leg.get(k), v) for k, v in mc.items() if k in leg and leg.get(k) is not None and int(leg[k]) != v}
            if bad:
                res.append(("FAIL", f"claim table {name}: {t.get('selector')} {leg} disagrees with {ev.get('section')} in {ev['manifest']}: {bad}"))
            missing = {k: v for k, v in mc.items() if k in leg and leg.get(k) is None}
            if missing:
                res.append(("WARN", f"claim table {name}: manifest {ev.get('section')} lists {missing} but {t.get('selector')} is still null"))
        elif ev.get("manifest"):
            res.append(("WARN", f"claim table {name}: no '{ev.get('section')}' legibility entry in {ev['manifest']} yet"))
        if row.get("confirm"):
            res.append(("WARN", f"claim table {name}: {row['text']!r} is provisional copy: {row['confirm']} to confirm"))
        res.append(("INFO", f"claim table {name}: {t.get('selector')}={leg} -> {row['text']!r}"))
    return res
