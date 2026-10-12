"""Designed-hero composition plan: what a thin prompt plus a few stills becomes (docs/thin-prompt-quality.md).

`promo plan` already fills idea, five beats, length, shot list and capture defaults. This module adds the part that makes the
result read as a designed promo instead of a flat stitch of screen recordings, and writes it under `plan.designed`:

    framing   per shot: floating (rounded panel with shadow over a plate, the primary look) | fullscreen (peak action, real
              footage only) | device (landscape bezel or portrait panel, for context) | plate (kinetic type over a plate, no UI)
    kinetic   caption cards: big blocky type, few words, pop / slide / scale, snapped to the beat, VO reads it verbatim
    plates    non-UI background plates to generate (AGENTS.md rule 1 carve-out), one shared look so the grade carries across cuts
    motion    a slow push-in on every panel, a recap montage whose cuts accelerate
    spine     the reference's proportions scaled to the master length, and the length band

What the system invents: plates, type curves, which still floats vs sits in a device, beat sync, the montage burst.
What it never invents: product claims, numbers, URLs, UI. Every word on a card must be a contiguous run of words the person
wrote (the prompt or a co-spec answer); `check_no_invention` refuses the plan otherwise, and `gates` repeats that at `promo check`.
"""
from __future__ import annotations

import math
import os
import re

from . import pacing as P

FRAMINGS = ("floating", "fullscreen", "device", "plate")
ANIMS = ("pop", "slide", "scale")
VIDEO_EXT = (".mp4", ".mov", ".m4v", ".webm", ".mkv")
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp")

REFERENCE = dict(
    duration_s=90,
    median_shot_s=0.73,
    avg_shot_s=2.25,
    cuts_per_s=0.43,
    loudness_lufs=-14.0,
    segments=[
        dict(name="action hook", beat="hook", s=[0, 7]),
        dict(name="title / value", beat="hook", s=[8, 14]),
        dict(name="feature pairs", beat="problem", s=[15, 36]),
        dict(name="social proof", beat="problem", s=[37, 43]),
        dict(name="depth / niche", beat="demo", s=[44, 63]),
        dict(name="recap montage", beat="payoff", s=[64, 79]),
        dict(name="cta", beat="ask", s=[80, 90]),
    ],
    note="Craft only: proportions and rhythm. Nothing of the reference's art style, assets or words is used.",
)

TYPE_STYLE = dict(
    face="bold blocky sans (Barlow Condensed Black when installed; Liberation / DejaVu Bold otherwise)",
    fill=[255, 255, 255],
    outline=[12, 12, 28],
    shadow=True,
    uppercase=True,
    size_pct_height=[8, 15],
    max_words_per_card=4,
    min_hold_s=0.6,
    sync="beat",
    vo_reads_onscreen=True,
    note="Readable with the sound off. VO says the card's words nearly verbatim (no claim on screen the voice does not say).",
)

ANIM_BY_BEAT = {
    "hook": {"anim": "pop", "from": None, "size_pct": 14},
    "problem": {"anim": "slide", "from": "left", "size_pct": 11},
    "demo": {"anim": "slide", "from": "up", "size_pct": 11},
    "payoff": {"anim": "scale", "from": None, "size_pct": 13},
    "ask": {"anim": "pop", "from": None, "size_pct": 12},
}

PLATE_GUARD = "No text, no logos, no screens, no devices, no people, no user interface."
WORLDS = (   # prompt keyword -> (plate A look, plate B look); only used when the person's own words say so
    (("night", "bed", "sleep", "overnight", "dark"), ("a calm deep-blue night sky just before dawn, soft stars, out of focus",
                                                      "first light of dawn, warm amber glow over a soft horizon, out of focus")),
    (("morning", "dawn", "sunrise", "wake"), ("a calm deep-blue sky before sunrise, out of focus",
                                              "first light of dawn, warm amber glow over a soft horizon, out of focus")),
)
DEFAULT_WORLD = ("a soft out-of-focus abstract gradient backdrop, cool blue shading to warm amber, gentle bokeh, subtle film grain",
                 "a soft out-of-focus abstract gradient backdrop, warm amber shading to cool blue, gentle bokeh, subtle film grain")

PANEL = dict(
    floating=dict(w=0.66, cy=0.40, radius=26),
    hero=dict(w=0.78, cy=0.44, radius=26),
    device=dict(w=0.58, cy=0.42, radius=46),
)
BEZEL = dict(alpha=0.95, width=9.0, color=[18, 18, 22])
REUSE_FOCUS = ((0.42, 0.42), (0.58, 0.42), (0.42, 0.58), (0.58, 0.58))   # a still shown again is cropped toward a different area
THIN_MAX_WORDS = 80
MAX_FEATURES = 3
MIN_SHOT_S = 0.75
BEAT_SUB = 2          # cards and cuts snap to half beats

_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w-]+\.(?:com|io|ai|dev|app|co|net|org|sh|so|me)\b(?:/\S*)?", re.I)
_META = re.compile(r"\b(?:promo|video|reel|trailer|teaser|spot|commercial|film|ad|clip)\b", re.I)
_DIRECTION = re.compile(r"^(?:make|create|build|produce|write|use|keep|avoid|ignore|please|attach|attached|here|see|include|add)\b", re.I)
_STILLS_TALK = re.compile(r"\b(?:stills?|screenshots?|images?|screens?|footage|photos?)\b", re.I)


# ---------------------------------------------------------------- reading the prompt
def _norm(text):
    return re.sub(r"[^\w']+", " ", str(text).lower()).strip()


def _labelled(prompt, key):
    m = re.search(rf"(?im)^[ \t]*{key}\s*:\s*(.+?)\s*$", prompt)
    return m.group(1).strip() if m else None


def _body(prompt):
    """The prompt without `label: value` lines (those fill named beats and fields, not free phrases)."""
    keep = [ln for ln in prompt.splitlines()
            if not re.match(r"^[ \t]*(?:idea|hook|problem|demo|payoff|cta|ask|call to action|features?|preset|style|format)\s*:", ln, re.I)]
    return "\n".join(keep)


def is_thin(prompt):
    """A thin prompt: a few lines, at most THIN_MAX_WORDS, and fewer than three of the five beats written out."""
    words = len(re.findall(r"\w+", prompt or ""))
    labelled = len(re.findall(r"(?im)^[ \t]*(?:hook|problem|demo|payoff|cta|ask|call to action)\s*:\s*\S", prompt or ""))
    return 0 < words <= THIN_MAX_WORDS and labelled < 3


def phrases(prompt):
    """The prompt's own short phrases, in order, minus the brief about the job ("60s promo for my app") and directions."""
    out = []
    for sent in re.split(r"(?<=[.!?])\s+|\n+", _body(prompt)):
        sent = sent.strip()
        if not sent or _STILLS_TALK.search(sent) and re.search(r"\b(?:attached|here|these|those|with|using|from)\b", sent, re.I):
            continue
        if _META.search(sent) and re.search(r"\b(?:for|about|of)\b", sent, re.I):
            continue
        for clause in re.split(r"\s*[,;:\u2014\u2013]\s*|\s+-\s+|\s+then\s+", sent):
            clause = clause.strip(" .!?\"'")
            if not clause or _DIRECTION.match(clause) or len(re.findall(r"\w+", clause)) < 1:
                continue
            out.append(clause)
    return out


def chunks(text, max_words=None):
    """Split a phrase into the fewest evenly sized runs of at most `max_words` words (contiguous, original wording)."""
    max_words = max_words or TYPE_STYLE["max_words_per_card"]
    words = text.split()
    n = max(1, math.ceil(len(words) / max_words))
    size = math.ceil(len(words) / n)
    return [" ".join(words[i:i + size]) for i in range(0, len(words), size)]


def parse_list(value, sep=r"[;\n]"):
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in re.split(sep, str(value)) if p.strip()]


def parse_claims(value):
    """`text | evidence` lines -> [{text, evidence}] (evidence may be empty: the claim then waits for it)."""
    res = []
    for item in parse_list(value):
        text, _, ev = item.partition("|")
        res.append(dict(text=text.strip(), evidence=ev.strip()))
    return res


# ---------------------------------------------------------------- stills
def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or "still"


def scan_stills(paths):
    """What the person handed over, described without reading its pixels: [{id, path, exists, kind, width, height, orientation}]."""
    res, used = [], set()
    for raw in paths or []:
        path = os.path.abspath(os.path.expanduser(str(raw)))
        base = _slug(os.path.splitext(os.path.basename(path))[0])
        sid, n = base, 2
        while sid in used:
            sid, n = f"{base}-{n}", n + 1
        used.add(sid)
        ext = os.path.splitext(path)[1].lower()
        kind = "video" if ext in VIDEO_EXT else "image" if ext in IMAGE_EXT else "other"
        row = dict(id=sid, path=path, exists=os.path.isfile(path), kind=kind, width=None, height=None, orientation="unknown")
        if row["exists"]:
            try:
                if kind == "image":
                    from PIL import Image
                    with Image.open(path) as im:
                        row["width"], row["height"] = im.size
                elif kind == "video":
                    from . import footage as FT
                    res_s, _fps = FT.probe_media(path)
                    row["width"], row["height"] = (int(v) for v in res_s.split("x"))
            except Exception:  # noqa: BLE001  (an unreadable still is still listed; the plan says it needs a look)
                pass
        if row["width"] and row["height"]:
            r = row["width"] / row["height"]
            row["orientation"] = "portrait" if r < 0.85 else "square" if r < 1.15 else "landscape"
        res.append(row)
    return res


# ---------------------------------------------------------------- plan pieces
def length_band(master_s):
    cls = "short" if master_s < 25 else "long" if master_s > 75 else "standard"
    segs = {
        "short": ["action hook", "title / value", "feature pairs", "cta"],
        "standard": ["action hook", "title / value", "feature pairs", "depth / niche", "recap montage", "cta"],
        "long": [s["name"] for s in REFERENCE["segments"]],
    }[cls]
    return dict(master_s=master_s, **{"class": cls}, reference_s=REFERENCE["duration_s"],
                scale=round(master_s / REFERENCE["duration_s"], 3), segments=segs,
                recap_montage=cls != "short",
                note="short: no montage burst, three or four held shots; standard: all five beats; long: adds the social-proof and depth runs.")


def spine(master_s):
    """The reference's seven segments scaled to the master, each tagged with the five-beat name it serves."""
    k = master_s / REFERENCE["duration_s"]
    return [dict(name=s["name"], beat=s["beat"], s=[round(s["s"][0] * k, 1), round(s["s"][1] * k + (k if s["s"][1] < 90 else 0), 1)])
            for s in REFERENCE["segments"]]


def world(prompt, answers):
    """(plate A look, plate B look, source). The person's own words first; keywords from the prompt next; else the neutral default."""
    given = (answers or {}).get("world")
    if given:
        return str(given).strip().rstrip("."), str(given).strip().rstrip("."), "answer"
    low = " ".join(re.findall(r"[a-z]+", (prompt or "").lower()))
    words = set(low.split())
    for keys, (a, b) in WORLDS:
        if words & set(keys):
            return a, b, "prompt"
    return DEFAULT_WORLD[0], DEFAULT_WORLD[1], "default"


def plates_for(prompt, answers, rows):
    """Plates to generate (non-UI, `ui: false`): A under hook + problem, B under demo + payoff, an end plate that reuses B's world."""
    a, b, src = world(prompt, answers)
    uses = {"plate-a": [], "plate-b": [], "plate-end": []}
    for r in rows:
        key = "plate-a" if r["beat"] in ("hook", "problem") else "plate-end" if r["beat"] == "ask" else "plate-b"
        uses[key].append(r["n"])
    spec = [("plate-a", a, "Opening world: hook and problem."), ("plate-b", b, "Proof world: demo and recap. Same look bible as plate-a, one step on in time or light."),
            ("plate-end", b, "End card world: calmer, more empty centre for the wordmark.")]
    res = []
    for pid, look, why in spec:
        if not uses[pid]:
            continue
        res.append(dict(
            id=pid, kind="image", aspect="16:9", seconds=4, ui=False, world_source=src, why=why, shots=uses[pid],
            prompt=f"{look[0].upper() + look[1:]}. Cinematic, shallow depth of field, soft graded colour, empty centre. {PLATE_GUARD}",
            provider=None,
            upgrade="a 4 s video plate (promo gen video / the Studio) once the still is approved",
            register=f"promo gen register <file> --id {pid} --prompt '<raw prompt>' --provider <who made it> --shots "
                     + " ".join(f"{n:02d}" for n in uses[pid]),
        ))
    return res


def montage_durations(total, n_cap=24, d0=2.0, d1=MIN_SHOT_S, grid=0.25):
    """Accelerating shot lengths (geometric from d0 to d1) that fill `total` seconds on a `grid`-second raster."""
    best = None
    for n in range(2, n_cap + 1):
        r = (d1 / d0) ** (1.0 / (n - 1))
        ds = [d0 * r ** i for i in range(n)]
        err = abs(sum(ds) - total)
        if best is None or err < best[0]:
            best = (err, ds)
    ds = best[1]
    k = total / sum(ds)
    q = [max(grid * 3, round(d * k / grid) * grid) for d in ds]
    while sum(q) > total + 1e-6 and len(q) > 1:
        q.pop()
    q[-1] += round(total - sum(q), 6)
    return [round(v, 3) for v in q]


def beat_grid(bpm=120.0):
    return 60.0 / bpm / BEAT_SUB


def snap(t, bpm=120.0):
    g = beat_grid(bpm)
    return round(round(t / g) * g, 3)


def assign_rows(plan_rows, stills, master_s, bpm=120.0):
    """One composition row per planned shot: framing, which still, plate, motion. Montage rows are re-cut to accelerate."""
    cls = length_band(master_s)
    uis = [s for s in stills if s["kind"] in ("image", "video")]
    videos = [s for s in uis if s["kind"] == "video" and s["orientation"] != "portrait"]
    context = [s for s in uis if s["orientation"] == "portrait" or s.get("role") in ("phone", "terminal", "context", "other")]
    wide = [s for s in uis if s not in context] or uis
    by_beat = {}
    for r in plan_rows:
        by_beat.setdefault(r["beat"], []).append(r)
    expanded = []
    for beat in P.SHOT_BEATS:
        group = by_beat.get(beat, [])
        secs = [float(r["seconds"]) for r in group]
        if beat == "payoff" and cls["recap_montage"] and group and sum(secs) >= 4.0:
            secs = montage_durations(sum(secs))
        for s in secs:
            expanded.append((beat, s))
    count = {b: sum(1 for x, _ in expanded if x == b) for b in P.SHOT_BEATS}
    slots = {("problem", 1), ("demo", max(1, count["demo"] * 3 // 4)), ("payoff", 3 if count["payoff"] >= 3 else 1)}   # a context device now and then
    rows, t, rw, rc, n_beat, uses = [], 0.0, 0, 0, {}, {}
    for n, (beat, secs) in enumerate(expanded, 1):
        i = n_beat[beat] = n_beat.get(beat, 0) + 1
        src, framing, why = None, "floating", ""
        if beat == "ask":
            framing, why = "plate", "end card: verb + place on a plate, no UI"
        elif not uis:
            framing, why = "plate", "no still or footage supplied for this shot yet: type over a plate until a real UI source exists"
        elif beat == "hook" and i == 1:
            if videos:
                framing, src, why = "fullscreen", videos[0], "action hook: real footage, peak action"
            else:
                framing, why = "plate", "hook: the promise in big type by 0.5 s; a still is not action"
        elif beat == "demo" and videos and i == (count["demo"] + 1) // 2:
            framing, src, why = "fullscreen", videos[0], "demo peak: real footage fullscreen, the one fullscreen moment of the middle"
        elif context and (beat, i) in slots:
            src, rc = context[rc % len(context)], rc + 1
            framing, why = "device", f"context ({src.get('role') or src['orientation']}): a device-shaped panel, bezel only, nothing drawn on the UI"
        else:
            src, rw = wide[rw % len(wide)], rw + 1
            why = "floating panel over the plate (primary framing)"
            if src["orientation"] == "portrait":
                framing, why = "device", "portrait source: a device-shaped panel (a 16:9 crop would cut it)"
        plate = None
        if framing in ("floating", "device", "plate"):
            plate = "plate-a" if beat in ("hook", "problem") else "plate-end" if beat == "ask" else "plate-b"
        k = 0
        if src is not None:
            k = uses[src["id"]] = uses.get(src["id"], -1) + 1
        motion = dict(push_in=0.0 if framing == "plate" else (0.06 if beat != "payoff" else 0.03), drift=framing == "plate")
        if src is not None and k > 0 and framing != "fullscreen":
            fx, fy = REUSE_FOCUS[(k - 1) % len(REUSE_FOCUS)]
            motion.update(focus=[fx, fy], zoom_w=0.8, crop="placeholder: a reused still is cropped toward a corner; aim it with `promo peek`")
        row = dict(n=n, id=f"{n:02d}", beat=beat, seconds=round(secs, 3), t0=round(t, 3), framing=framing,
                   ui_source=src["id"] if src else None, plate=plate, motion=motion,
                   text_ok=framing in ("floating", "plate") or (framing == "device" and not (src and src["orientation"] == "portrait")),
                   why=why, cards=[])
        t += secs
        rows.append(row)
    return rows


def _sources(prompt, answers):
    srcs = [str(prompt or "")]
    for v in (answers or {}).values():
        if isinstance(v, (list, tuple)):
            srcs.extend(str(x) for x in v)
        elif v:
            srcs.append(str(v))
    return srcs


def grounded(text, sources):
    """Is `text` a contiguous run of whole words in one of the person's own texts?"""
    t = " " + _norm(text) + " "
    return bool(_norm(text)) and any(t in " " + _norm(s) + " " for s in sources)


def make_cards(prompt, beats, beat_sources, answers, idea=None):
    """Kinetic caption cards from the person's own words, one idea per beat. A beat with no words of theirs gets a placeholder
    card (`status: needs-copy`) naming the co-spec question that fills it; the card never carries invented text."""
    answers = answers or {}
    ph = phrases(prompt) or ([idea] if idea else [])
    feats = parse_list(answers.get("features")) or parse_list(_labelled(prompt, "features?"))
    feats = feats[:MAX_FEATURES]
    claims = [c for c in parse_claims(answers.get("must_keep")) if c["text"]]
    by_beat = {b: [] for b in P.SHOT_BEATS}

    def labelled(beat_key):
        return beats.get(beat_key) if beat_sources.get(beat_key) == "prompt" and beats.get(beat_key) else None

    hook = labelled("hook") or (ph[0] if ph else None)
    payoff = labelled("payoff") or (ph[-1] if len(ph) > 1 else None) or hook
    problem = labelled("problem") or (ph[1] if len(ph) > 2 else None)
    cta = answers.get("cta") or labelled("cta")
    for beat, texts, src in (("hook", [hook], "prompt"), ("problem", [problem], "prompt"),
                             ("demo", feats or [None], "answer" if answers.get("features") else "prompt"),
                             ("payoff", [payoff], "prompt"), ("ask", [cta], "answer" if answers.get("cta") else "prompt")):
        for text in texts:
            if not text:
                by_beat[beat].append(dict(beat=beat, text=None, status="needs-copy", source=None,
                                          needs={"hook": "idea", "problem": "idea", "demo": "features", "payoff": "idea",
                                                 "ask": "cta"}[beat]))
                continue
            for k, piece in enumerate(chunks(str(text))):
                by_beat[beat].append(dict(beat=beat, text=piece, status="ready", source=src, chain=k))
    for c in claims:
        if c["evidence"]:
            by_beat["demo"].append(dict(beat="demo", text=c["text"], status="ready", source="answer", chain=0, evidence=c["evidence"]))
    cards = []
    for beat in P.SHOT_BEATS:
        for c in by_beat[beat]:
            cards.append(c)
    for i, c in enumerate(cards, 1):
        c["id"] = f"k{i:02d}"
        spec = ANIM_BY_BEAT[c["beat"]]
        c.update(anim=spec["anim"], size_pct=spec["size_pct"], sync="beat" if c["text"] else None)
        if spec["from"]:
            c["from"] = spec["from"]
        c["vo"] = c["text"]
    return cards


def place_cards(rows, cards, bpm=120.0):
    """Put each card on a shot of its beat that can carry type (never over a UI panel), spread evenly, snapped to the beat grid.
    Fullscreen rows carry none. More cards than shots: the surplus stays unplaced and is listed (one idea per beat)."""
    unplaced = []
    for beat in P.SHOT_BEATS:
        cs = [c for c in cards if c["beat"] == beat]
        rs = [r for r in rows if r["beat"] == beat and r["text_ok"]]
        if not cs:
            continue
        if not rs:
            unplaced += [c["id"] for c in cs]
            continue
        if len(cs) > len(rs):
            for c in cs[len(rs):]:
                unplaced.append(c["id"])
            cs = cs[:len(rs)]
        for i, c in enumerate(cs):
            r = rs[i] if (beat == "payoff" or len(cs) >= len(rs)) else rs[min(len(rs) - 1, int(i * len(rs) / len(cs)))]
            need = max(TYPE_STYLE["min_hold_s"], 0.3 * len(str(c["text"]).split()))
            at = 0.0 if (beat == "hook" and r["n"] == rows[0]["n"]) else snap(min(0.25, max(r["seconds"] - need, 0.0)), bpm)
            c.update(shot=r["id"], at=at, dur=round(max(r["seconds"] - at, TYPE_STYLE["min_hold_s"]), 3))
            r["cards"].append(c["id"])
    return unplaced


def build(prompt, plan, stills=None, answers=None, bpm=120.0, trigger="thin+stills"):
    """The `plan.designed` block for a plan built by `gapfill.build_plan`."""
    from . import cospec as CS
    answers = dict(answers or {})
    scanned = CS.apply_roles(scan_stills(stills or []), answers)
    master = plan["length"]["master_s"]
    rows = assign_rows(plan["shot_list"], scanned, master, bpm)
    cards = make_cards(prompt, plan["beats"], plan["beat_sources"], answers,
                       idea=plan["idea"] if plan.get("idea_source") == "prompt" else None)
    unplaced = place_cards(rows, cards, bpm)
    plates = plates_for(prompt, answers, rows)
    ui_rows = [r for r in rows if r["framing"] != "plate"]
    n_full = sum(1 for r in ui_rows if r["framing"] == "fullscreen")
    needs = []
    if not any(s["exists"] for s in scanned):
        needs.append(dict(kind="ui", why="no real still or footage supplied (or the file is missing): shots show type over a plate until a real UI source exists",
                          then="promo plan <name> --prompt ... --stills <png|mp4> ..."))
    for s in scanned:
        if not s["exists"]:
            needs.append(dict(kind="ui", id=s["id"], why=f"file not found: {s['path']}", then="fix the path and re-run `promo plan --stills`"))
    for c in cards:
        if c["status"] == "needs-copy":
            needs.append(dict(kind="copy", id=c["id"], beat=c["beat"], why=f"no words of yours for the {c['beat']} beat; nothing is invented",
                              then=f"promo cospec --answer {c['needs']}=..."))
    for cl in [c for c in parse_claims(answers.get("must_keep")) if c["text"] and not c["evidence"]]:
        needs.append(dict(kind="evidence", text=cl["text"], why="a must-keep claim needs what on screen proves it before it becomes a card",
                          then="promo cospec --answer 'must_keep=<claim> | <evidence>'"))
    if any(p["id"] for p in plates):
        needs.append(dict(kind="plates", ids=[p["id"] for p in plates], why="non-UI backdrop plates to generate (rule 1 carve-out)",
                          then="promo gen plan; make each; promo gen register ..."))
    return dict(
        enabled=True,
        trigger=trigger,
        note=("Craft plan, not copy. Framing, type curves, plates and montage are the system's choices (edit them); every word on a card is "
              "yours (prompt or co-spec answer). Anything marked needs-* is waiting on you; nothing is invented to fill it."),
        stills=scanned,
        length_band=length_band(master),
        spine=spine(master),
        reference=dict(**{k: v for k, v in REFERENCE.items() if k != "segments"}),
        type_style=TYPE_STYLE,
        framing_hierarchy=dict(
            primary="floating", fullscreen="peak action only, real footage only (a still is never fullscreen)",
            device="context; bezel only, nothing drawn on the UI", plate="type over a generated plate, no UI",
            counts={f: sum(1 for r in rows if r["framing"] == f) for f in FRAMINGS},
            fullscreen_share=round(n_full / len(ui_rows), 3) if ui_rows else 0.0,
        ),
        plates=plates,
        kinetic_cards=cards,
        unplaced_cards=unplaced,
        shots=rows,
        montage=dict(beat="payoff", enabled=length_band(master)["recap_montage"],
                     shots=[r["id"] for r in rows if r["beat"] == "payoff"],
                     durations=[r["seconds"] for r in rows if r["beat"] == "payoff"], accelerates=True,
                     min_shot_s=MIN_SHOT_S, reference_median_s=REFERENCE["median_shot_s"]),
        loudness_lufs=-14.0,
        bpm=bpm,
        needs=needs,
        never=["invented claims, numbers or URLs", "invented or generated app UI", "text, logos, screens or people on a plate",
               "type over app UI pixels"],
    )


def broll_entries(designed):
    """`broll:` entries (promo gen plan format) for the plates."""
    return [dict(id=p["id"], kind=p["kind"], prompt=p["prompt"], seconds=p["seconds"], aspect=p["aspect"]) for p in designed.get("plates") or []]


# ---------------------------------------------------------------- the refusal: no invented words, numbers or URLs
def check_no_invention(designed, prompt, answers=None):
    """Problems (empty = fine). Card text and the claims must come from the person; plate prompts must carry the guard and no
    product words, numbers or URLs."""
    srcs = _sources(prompt, answers)
    bad = []
    for c in designed.get("kinetic_cards") or []:
        t = c.get("text")
        if t is None:
            if c.get("status") != "needs-copy":
                bad.append(f"card {c.get('id')}: empty text but status {c.get('status')!r}")
            continue
        if not grounded(t, srcs):
            bad.append(f"card {c.get('id')} {t!r} is not words the prompt or a co-spec answer wrote")
        if _URL.search(t) and not any(_URL.search(s) and _norm(_URL.search(t).group(0)) in _norm(s) for s in srcs):
            bad.append(f"card {c.get('id')} {t!r} carries a URL nobody gave")
    for p in designed.get("plates") or []:
        pr = p.get("prompt", "")
        if PLATE_GUARD not in pr:
            bad.append(f"plate {p.get('id')}: prompt lacks the no-text / no-UI guard")
        if p.get("ui") is not False:
            bad.append(f"plate {p.get('id')}: a plate must be ui: false")
        if p.get("world_source") != "answer" and (re.search(r"\d", pr) or _URL.search(pr)):
            bad.append(f"plate {p.get('id')}: prompt carries a number or URL")
    ans = answers or {}
    for banned in parse_list(ans.get("must_not")):
        for c in designed.get("kinetic_cards") or []:
            if c.get("text") and _norm(banned) and _norm(banned) in _norm(c["text"]):
                bad.append(f"card {c.get('id')} {c['text']!r} says what you said never to say ({banned!r})")
    for r in designed.get("shots") or []:
        if r["framing"] not in FRAMINGS:
            bad.append(f"shot {r['id']}: framing {r['framing']!r}")
        if r["framing"] == "fullscreen" and r.get("ui_source") is None:
            bad.append(f"shot {r['id']}: fullscreen without a real source")
    return bad


# ---------------------------------------------------------------- compile to cinema shots (the build wiring)
def compile_shots(designed, bpm=None, ready=()):
    """`shots:` for promo.yaml: `cinema` shots (floating panel over a plate, kinetic type, slow push-in), from a designed plan.
    UI shots point at the supplied stills by clip id (register them with `promo footage add`). A plate is used only once it is in
    `ready` (registered in the footage manifest); until then the shot falls back to a dark plate / the blurred copy, so a preview builds."""
    ready = set(ready)
    bpm = float(bpm or designed.get("bpm") or 120.0)
    bsec = 60.0 / bpm
    cards = {c["id"]: c for c in designed.get("kinetic_cards") or []}
    stills = {s["id"]: s for s in designed.get("stills") or []}
    out, cur = [], 0.0
    for r in designed["shots"]:
        b0 = round(cur / bsec * 2) / 2.0
        cur += float(r["seconds"])
        b1 = round(cur / bsec * 2) / 2.0
        fr = r["framing"]
        shot = dict(id=r["id"], beats=[b0, b1], type="cinema")
        look = {}
        push = float(r["motion"].get("push_in") or 0.0)
        if fr == "plate":
            shot["ui"] = False
            if r.get("plate") in ready:
                shot["source"] = r["plate"]
                shot["t_in"] = 0.0
            look["backdrop"] = "none"
            if r["motion"].get("drift"):
                shot["cam"] = [[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.94]]
        else:
            shot["source"] = r["ui_source"]
            shot["t_in"] = 0.0
            if r["motion"].get("focus"):
                fx, fy = r["motion"]["focus"]
                w0 = float(r["motion"].get("zoom_w", 0.8))
                shot["cam"] = [[0, fx, fy, w0], ["end", fx, fy, round(w0 - push, 3)]]
            else:
                shot["cam"] = [[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, round(1.0 - push, 3)]]
            if fr == "fullscreen":
                look["backdrop"] = "none"
            else:
                bd = {"plate": r["plate"], "blur": 0.03, "dim": 0.8, "warm": 0.12} if r.get("plate") in ready else {}
                if bd:
                    look["backdrop"] = bd
                base = PANEL["device"] if fr == "device" else (PANEL["hero"] if r["beat"] == "demo" else PANEL["floating"])
                panel = dict(base, **{"in": dict(dur=0.3, from_scale=0.94, fade=True)})
                if fr == "device":
                    panel["rim"] = dict(BEZEL)
                    st = stills.get(r["ui_source"]) or {}
                    if st.get("orientation") == "portrait" and st.get("width") and st.get("height"):
                        panel.update(aspect=round(st["width"] / st["height"], 3), w=0.22, cy=0.5)
                look["panel"] = panel
        if look:
            shot["look"] = look
        kin = []
        for cid in r["cards"]:
            c = cards[cid]
            if not c.get("text"):
                continue
            item = dict(text=c["text"], at=c["at"], dur=c["dur"], size_pct=c["size_pct"], anim=c["anim"])
            if c.get("from"):
                item["from"] = c["from"]
            if fr == "plate":
                item["cy"] = 0.5
            kin.append(item)
        if kin:
            shot["kinetic_copy"] = kin
        shot["notes"] = f"designed: {fr}; {r['why']}" + (f"; source {r['ui_source']}" if r.get("ui_source") else "")
        out.append(shot)
    return out


# ---------------------------------------------------------------- promo check
def gates(spec):
    """(gate, status, msg) for a project whose plan carries `designed:`. Empty when it does not."""
    plan = (getattr(spec, "raw", None) or {}).get("plan") or {}
    des = plan.get("designed")
    if not des:
        return []
    from .shots import cinema as CN
    answers = (plan.get("cospec") or {}).get("answers") or {}
    srcs = _sources(plan.get("prompt", ""), answers)
    items = [(s, c) for s in spec.shots if s.type == "cinema" for c in CN.kinetic_items(s)]
    out = []
    bad = []
    for s, c in items:
        t = CN.kinetic_text(c)
        if not grounded(t, srcs):
            bad.append(f"shot {s.id} kinetic {t!r} is not words the prompt or a co-spec answer wrote")
        if _URL.search(t):
            bad.append(f"shot {s.id} kinetic {t!r} carries a URL (only one the person wrote may appear: put it in a co-spec answer)")
    out.append(("designed-grounded", "FAIL" if bad else "PASS", "; ".join(bad) or f"{len(items)} kinetic cards are all the person's own words"))
    warn, clear = [], []
    lo, hi = TYPE_STYLE["size_pct_height"]
    for s, c in items:
        pct = CN.kinetic_pct(c)
        if not (lo - 1e-9 <= pct <= hi + 1e-9):
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r} size_pct {pct:g} outside {lo}-{hi}")
        words = len(CN.kinetic_text(c).split())
        hold = min(float(c.get("dur", 2.0)), s.dur - float(c.get("at", 0.0)))
        need = max(TYPE_STYLE["min_hold_s"], 0.3 * words)
        if hold < need - 1e-6:
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r} visible {hold:.2f}s < {need:.2f}s (0.3 s per word, min {TYPE_STYLE['min_hold_s']}s)")
        if len(CN.kinetic_text(c).split()) > TYPE_STYLE["max_words_per_card"]:
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r} has more than {TYPE_STYLE['max_words_per_card']} words")
        if CN.is_ui(s):
            pb = CN.panel_box_of(spec, s)
            box = CN.kinetic_box(spec, s, c, (1920, 1080))
            if pb is None:
                clear.append(f"shot {s.id} {CN.kinetic_text(c)!r} is on a full-bleed UI shot (type belongs on a plate or in the panel margin)")
            elif box[0] < pb[2] and pb[0] < box[2] and box[1] < pb[3] and pb[1] < box[3]:
                clear.append(f"shot {s.id} {CN.kinetic_text(c)!r} box {[round(v) for v in box]} overlaps the UI panel {list(pb)}")
    out.append(("designed-kinetic", "WARN" if warn else "PASS", "; ".join(warn) or f"{len(items)} kinetic cards: size, hold and word count within the type style"))
    out.append(("designed-clear", "FAIL" if clear else "PASS", "; ".join(clear) or "no kinetic type over app UI"))
    cs = [s for s in spec.shots if s.type == "cinema"]
    ui = [s for s in cs if CN.is_ui(s)]
    full = [s for s in ui if CN.panel_box_of(spec, s) is None]
    if ui:
        share = len(full) / len(ui)
        msg = f"{len(ui) - len(full)} panel shots, {len(full)} fullscreen ({share:.0%})"
        out.append(("designed-framing", "WARN" if share > 0.25 or len(full) > len(ui) - len(full) else "PASS",
                    msg + ("; floating panels over plates are the primary framing (fullscreen only for peak action)" if share > 0.25 else "")))
    return out


# ---------------------------------------------------------------- `promo designed apply`: write the compiled shots into promo.yaml
SHOTS_BEGIN = "# promo:designed-shots BEGIN (written by `promo designed apply` from plan.designed; re-run it after `promo plan` / `promo cospec`)\n"
SHOTS_END = "# promo:designed-shots END\n"


def _top_span(lines, key):
    start = next((i for i, ln in enumerate(lines) if re.match(rf"^{key}:", ln)), None)
    if start is None:
        return None
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and not ln.startswith((" ", "\t", "- ")):
            break
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    return start, end


def sync_timeline(text, master_s, total_beats):
    """Make output.duration, timeline.beats and the music edit follow the designed shots (only the scaffold's own one-line forms)."""
    text = re.sub(r"(?m)^(output:.*?duration:\s*)[\d.]+", lambda m: f"{m.group(1)}{float(master_s):.1f}", text, count=1)
    text = re.sub(r"(?m)^(timeline:.*?beats:\s*)[\d.]+", lambda m: f"{m.group(1)}{total_beats:g}", text, count=1)
    text = re.sub(r"(segments:\s*\[\[0,\s*0,\s*)[\d.]+(\]\])", lambda m: f"{m.group(1)}{total_beats:g}{m.group(2)}", text, count=1)
    text = re.sub(r"(?m)^(\s*silence_from_beat:\s*)[\d.]+", lambda m: f"{m.group(1)}{total_beats:g}", text, count=1)
    return text


def apply_shots(path, register=True, force=False):
    """Compile `plan.designed` to `cinema` shots and put them in promo.yaml between markers (the scaffold's example shots are
    replaced; shots you wrote yourself are refused unless force). Supplied stills are registered in the footage manifest as
    what they are (not recorded by promo), so the shots can name them. Returns {shots, registered, ready_plates, path}."""
    import yaml

    from . import footage as FT
    from . import gapfill as GF
    from .spec import load_spec
    path = os.path.abspath(path)
    text = open(path).read()
    plan = GF.existing_plan(text)
    des = plan.get("designed")
    if not des:
        raise SystemExit("no plan.designed in this file: run `promo plan <name> --prompt ... --stills ...` (or --designed) first")
    problems = check_no_invention(des, plan.get("prompt", ""), (plan.get("cospec") or {}).get("answers"))
    if problems:
        raise SystemExit("designed plan refused (nothing invented is allowed):\n  " + "\n  ".join(problems))
    spec = load_spec(path, plugins=False)
    registered = []
    if register:
        for st in des.get("stills") or []:
            if not st.get("exists") or not os.path.isfile(st["path"]):
                continue
            uses = [r["id"] for r in des["shots"] if r.get("ui_source") == st["id"]]
            FT.add(spec, st["path"], st["id"], shots=uses, commit="unknown", capture="supplied by the person (not recorded by promo)",
                   framing="as supplied", dpr=None, notes="supplied still / clip; confirm it is the real product UI")
            registered.append(st["id"])
        spec._footage = None
    try:
        man = FT.load(spec)
    except Exception:  # noqa: BLE001
        man = {}
    ready = {p["id"] for p in des.get("plates") or [] if p["id"] in man}
    shots = compile_shots(des, ready=ready)
    body = yaml.safe_dump({"shots": shots}, sort_keys=False, allow_unicode=True, width=120, default_flow_style=None)
    block = SHOTS_BEGIN + body + SHOTS_END
    if "# promo:designed-shots BEGIN" in text:
        text = re.sub(r"# promo:designed-shots BEGIN.*?# promo:designed-shots END\n?", lambda m: block, text, count=1, flags=re.S)
    else:
        lines = text.splitlines(keepends=True)
        span = _top_span(lines, "shots")
        if span is None:
            raise SystemExit("promo.yaml has no top-level `shots:` to replace")
        old = "".join(lines[span[0]:span[1]])
        if "my-clip" not in old and not force:
            raise SystemExit("the file's shots: were written by hand; --force replaces them with the designed shots")
        text = "".join(lines[:span[0]]) + block + "".join(lines[span[1]:])
    total = shots[-1]["beats"][1] if shots else 0
    text = sync_timeline(text, plan.get("length", {}).get("master_s", 60), total)
    with open(path, "w") as f:
        f.write(text)
    return dict(path=path, shots=shots, registered=registered, ready_plates=sorted(ready))
