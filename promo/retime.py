"""`promo move-cut <beat> <new_beat>`: move ONE cut on the beat grid, i.e. end the shot that ends at <beat> and start the
next shot at <new_beat> instead. Everything else stays put. Edits promo.yaml in place, keeping comments (only the two
`beats: [a, b]` lines change). Made for slot swaps such as the 03 composer: `promo move-cut 20 12` lands 03 at 4.07 s.

Refuses when a shot's timing would silently break: explicit `segs` durations (they must add up to the shot) or a card
that would run past the shortened shot; re-time those by hand, then run `promo check` (bar cuts, holds, markers)."""
from __future__ import annotations

import re


class RetimeError(Exception):
    pass


def _fmt(v):
    return str(int(v)) if float(v).is_integer() else repr(float(v))


def _block(lines, sid):
    """(start, end) line indexes of the YAML block of shot `sid` under `shots:`."""
    pat = re.compile(r'^\s*-\s+id:\s*["\']?' + re.escape(str(sid)) + r'["\']?\s*(#.*)?$')
    start = next((i for i, ln in enumerate(lines) if pat.match(ln)), None)
    if start is None:
        raise RetimeError(f"shot {sid}: block not found in promo.yaml")
    ind = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        s = ln.lstrip()
        if s and not s.startswith("#") and (len(ln) - len(s)) <= ind:
            break
        end += 1
    return start, end


def move_cut(path, raw, beat, new, bar_s=None, beats_per_bar=4):
    shots = raw.get("shots") or []
    a = next((s for s in shots if float(s["beats"][1]) == float(beat)), None)
    b = next((s for s in shots if float(s["beats"][0]) == float(beat)), None)
    if a is None or b is None:
        raise RetimeError(f"no cut at beat {beat} (need one shot ending and one starting there)")
    if not (float(a["beats"][0]) < float(new) < float(b["beats"][1])):
        raise RetimeError(f"beat {new} must lie inside shots {a['id']}..{b['id']} ({a['beats'][0]}..{b['beats'][1]})")
    for s, na, nb in ((a, a["beats"][0], new), (b, new, b["beats"][1])):
        if s.get("segs") and any("dur" in g for g in s["segs"]):
            raise RetimeError(f"shot {s['id']} has explicit segs durations: re-time it by hand")
        n_bars = (float(nb) - float(na)) / beats_per_bar
        for c in s.get("cards") or []:
            bars = c.get("bars")
            if bars and bars[1] != "end" and float(bars[1]) > n_bars + 1e-9:
                raise RetimeError(f"shot {s['id']} card {c.get('text') or c.get('text_from')!r} bars {bars} would outrun the "
                                  f"{n_bars:g}-bar shot: use bars [.., end] or re-time it")
    lines = open(path).read().split("\n")
    for s, na, nb in ((a, a["beats"][0], new), (b, new, b["beats"][1])):
        i0, i1 = _block(lines, s["id"])
        for i in range(i0, i1):
            m = re.match(r"^(\s*beats:\s*)\[[^\]]*\](.*)$", lines[i])
            if m:                                   # flow style: beats: [a, b]
                lines[i] = f"{m.group(1)}[{_fmt(na)}, {_fmt(nb)}]{m.group(2)}"
                break
            if re.match(r"^\s*beats:\s*(#.*)?$", lines[i]):   # block style: beats:\n  - a\n  - b
                items = [j for j in range(i + 1, min(i + 3, i1)) if re.match(r"^\s*-\s*[-\d.]+\s*(#.*)?$", lines[j])]
                if len(items) == 2:
                    for j, v in zip(items, (na, nb)):
                        lines[j] = re.sub(r"^(\s*-\s*)[-\d.]+", lambda mm: mm.group(1) + _fmt(v), lines[j])
                    break
        else:
            raise RetimeError(f"shot {s['id']}: no 'beats: [a, b]' line")
    open(path, "w").write("\n".join(lines))
    out = dict(ok=True, moved=[beat, new], shots={a["id"]: [a["beats"][0], new], b["id"]: [new, b["beats"][1]]})
    if bar_s:
        out["starts_s"] = {b["id"]: round(float(new) * bar_s / beats_per_bar, 3)}
    return out
