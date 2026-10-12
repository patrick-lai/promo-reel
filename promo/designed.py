"""Designed-hero composition plan: what a thin prompt plus a few stills becomes (docs/thin-prompt-quality.md).

`promo plan` already fills idea, five beats, length, shot list and capture defaults. This module adds the part that makes the
result read as a designed promo instead of a flat stitch of screen recordings, and writes it under `plan.designed`:

    framing   per shot: floating (rounded panel with shadow over a plate, the primary look) | fullscreen (peak action, real
              footage only) | device (landscape bezel or portrait panel, for context) | plate (kinetic type over a plate, no UI)
    kinetic   caption cards: big blocky type, few words, pop / slide / scale, snapped to the beat, VO reads it verbatim
    plates    non-UI background plates to generate (AGENTS.md rule 1 carve-out), one shared look so the grade carries across cuts
    motion    a slow push-in on every panel, a recap montage whose cuts accelerate
    spine     the reference's proportions scaled to the master length, and the length band

Two craft dialects (`DIALECTS`), picked from a thin prompt by `pick_dialect` (ethereal unless the words say kinetic):

    ethereal  (default)  breathable holds, micro snaps, sparse light type used as UI (brackets, anchors, an inline thumb), small
                         panels of the real stills floating on pastel plates, slow linear camera, music-led, quiet until the end card
    kinetic              Smash&Clash-style: denser cuts, big outlined blocky type locked to the VO, floating panels, an accelerating recap

What the system invents: plates, type curves, which still floats vs sits in a device, beat sync, the montage burst (kinetic).
What it never invents: product claims, numbers, URLs, UI. Every word on a card must be a contiguous run of words the person
wrote (the prompt or a co-spec answer); `check_no_invention` refuses the plan otherwise, and `gates` repeats that at `promo check`.
"""
from __future__ import annotations

import copy
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

DIALECT_NAMES = ("ethereal", "kinetic")
DEFAULT_DIALECT = "ethereal"
_ETHEREAL_WORDS = ("ethereal", "conceptual", "minimalist", "minimal", "calm", "airy", "pastel", "apple", "opus", "serene", "quiet",
                   "dreamy", "gentle", "zen", "breathable", "lo-fi", "lofi", "blueemi", "music-led")
_KINETIC_WORDS = ("kinetic", "smash", "clash", "hype", "hyped", "energetic", "punchy", "fast-paced", "fast cuts", "launch trailer",
                  "loud", "dense", "big type", "bold type", "game trailer")

TYPE_STYLE_ETHEREAL = dict(
    face="light / medium humanist sans in sentence case (the UI font's Light and Medium weights)",
    fill=[34, 38, 56],
    outline=None,
    shadow=False,
    uppercase=False,
    size_pct_height=[4, 9],
    max_words_per_card=8,
    min_hold_s=1.2,
    sync="snap",
    vo_reads_onscreen=False,
    note="Sparse and quiet. Type is treated as UI: brackets, selection anchors, an inline thumb of a real still. No outline, no shadow.",
)

ANIM_BY_BEAT_ETHEREAL = {
    "hook": {"anim": "cascade", "from": None, "size_pct": 7.5, "weight": "Light"},
    "problem": {"anim": "snap", "from": None, "size_pct": 5.5, "weight": "Medium", "anchors": True},
    "demo": {"anim": "snap", "from": None, "size_pct": 5.5, "weight": "Medium", "brackets": True},
    "payoff": {"anim": "snap", "from": None, "size_pct": 7.0, "weight": "Light", "brackets": True},
    "ask": {"anim": "cascade", "from": None, "size_pct": 7.5, "weight": "Light", "brackets": True},
}

WORLDS_ETHEREAL = (
    (("night", "bed", "sleep", "overnight", "dark"), ("a soft pastel pre-dawn sky, powder blue fading to peach, halftone texture, airy and out of focus",
                                                      "pale peach first light over a soft horizon, airy, low contrast, out of focus")),
    (("morning", "dawn", "sunrise", "wake"), ("a soft pastel sky before sunrise, powder blue to peach, halftone texture, airy and out of focus",
                                              "pale peach first light over a soft horizon, airy, low contrast, out of focus")),
)
DEFAULT_WORLD_ETHEREAL = ("a soft pastel halftone sky, powder blue to peach, airy, out of focus",
                          "an empty pastel room with soft window light, minimal, smooth surfaces, a soft computer-rendered look, out of focus")
PLATE_STYLE = dict(
    kinetic="Cinematic, shallow depth of field, soft graded colour, empty centre.",
    ethereal="Soft pastel palette, low contrast, airy, minimal, lots of empty space, gentle grain, empty centre.",
)

ETHEREAL_PANEL = dict(
    floating=dict(w=0.52, cy=0.42, radius=22),
    hero=dict(w=0.58, cy=0.43, radius=22),
    device=dict(w=0.46, cy=0.42, radius=40),
)
ETHEREAL_BEZEL = dict(alpha=0.95, width=8.0, color=[236, 236, 242])
ETHEREAL_LOOK = dict(
    grade=dict(on=True, lift=[0.040, 0.040, 0.050], gamma=[1.08, 1.06, 1.04], gain=[1.0, 0.99, 1.0],
               shadows=[0.030, 0.020, 0.040], highlights=[0.0, 0.0, 0.0], split=1.0, saturation=0.82),
    vignette=False,
    bloom=dict(on=True, threshold=0.7, radius=0.020, strength=0.22),
    grain=dict(on=True, amount=0.015, size=1.0, seed=7),
)
ETHEREAL_PANEL_FX = dict(
    shadow=dict(on=True, layers=[dict(alpha=0.14, blur=0.006, dy=0.003, spread=0.0), dict(alpha=0.16, blur=0.034, dy=0.022, spread=0.0)]),
    rim=dict(on=True, alpha=0.55, width=1.0, color=[255, 255, 255]),
    glow=False,
)
ETHEREAL_FILL = dict(top=[205, 218, 240], bottom=[246, 226, 216])    # pastel placeholder world until a plate is registered
ETHEREAL_RESOLVE = dict(kind="mosaic", dur=0.9, steps=6, from_blocks=8)
ETHEREAL_PUSH = 0.04
ETHEREAL_MAX_DRIFT = dict(pan_per_s=0.02, zoom_per_s=0.012)    # a floaty dolly, not a move
KINETIC_MAX_DRIFT = dict(pan_per_s=0.35, zoom_per_s=0.25)

DIALECTS = {
    "ethereal": dict(
        name="ethereal", aka="conceptual-minimalist",
        summary="breathable holds, micro snaps, sparse type as UI, small real panels floating on pastel plates, music-led",
        pacing=dict(target_shot_s=5.0, end_card_min_s=6.0, cuts_per_s=[0.1, 0.25], median_shot_min_s=3.0, accelerating_recap=False,
                    snaps="type and selection boxes appear in one frame, no blur"),
        type=TYPE_STYLE_ETHEREAL,
        camera=dict(allowed="locked, or a slow linear push-in / floaty dolly", forbidden=["whip pan", "shake", "heavy motion blur"],
                    max_drift=ETHEREAL_MAX_DRIFT, ease="linear"),
        ui=dict(fullscreen=False, primary="small floating panels of the supplied stills, lots of air",
                abstraction="typography as UI (brackets, selection anchors, an inline thumb of a real still); never drawn or generated app UI",
                clutter="no fullscreen app chrome"),
        plates=dict(family="surreal pastel: halftone sky, empty pastel room, smooth gradient field", seconds=6),
        grade="soft pastels, airy gradients, low contrast (no vignette, light grain, no glow spill)",
        audio=dict(music_led=True, vo=False, bed="ambient / lo-fi bed (a licensed asset in assets.yaml; test_only for an internal test)",
                   clicks="soft ASMR UI clicks on the snaps (sfx library: click or tick)", whoosh="a soft whoosh only on a mosaic resolve",
                   quiet_until_cta=True, loudness_lufs=-14.0),
        transitions=[dict(kind="mosaic-resolve", on="the backdrop of the first shot of each beat: coarse blocks resolve to sharp in hard steps"),
                     dict(kind="cascade", on="the words of the hook and end card snap on one by one"),
                     dict(kind="hard-cut", on="everything else; no whip, flash, shake or blur")],
    ),
    "kinetic": dict(
        name="kinetic", aka="launch trailer",
        summary="denser cuts, big outlined blocky type locked to the VO, floating UI panels, an accelerating recap",
        pacing=dict(target_shot_s=REFERENCE["avg_shot_s"], end_card_min_s=3.0, cuts_per_s=[0.3, 0.6], median_shot_min_s=0.0,
                    accelerating_recap=True, snaps="words pop, slide and scale in on the beat"),
        type=TYPE_STYLE,
        camera=dict(allowed="slow push-ins on panels with continuous micro-animation", forbidden=[],
                    max_drift=KINETIC_MAX_DRIFT, ease="ease"),
        ui=dict(fullscreen=True, primary="floating rounded panels with a drop shadow over plates; fullscreen only for peak action",
                abstraction="none: the real stills, bezel only for context", clutter="fullscreen only with real footage, at most a quarter of the UI shots"),
        plates=dict(family="graded cinematic backdrops", seconds=4),
        grade="warm low-key graded backdrops (the preset look)",
        audio=dict(music_led=False, vo=True, bed="music on the beat grid", clicks="the preset's tick on each pop", whoosh=None,
                   quiet_until_cta=False, loudness_lufs=-14.0),
        transitions=[dict(kind="hard-cut", on="every cut, snapped to the half-beat grid"),
                     dict(kind="accelerating-montage", on="the payoff: shot lengths shrink from 2.0 s to 0.75 s")],
    ),
}


def _hits(words, text):
    low = " " + _norm(str(text or "").replace("-", " ")) + " "
    return sorted({w for w in words if f" {_norm(w.replace('-', ' '))} " in low})


def pick_dialect(prompt, flag=None, answers=None):
    """Which craft dialect a prompt wants: {name, source, matched, ambiguous}.

    An explicit flag or a `dialect:` answer / line wins. Otherwise the prompt's own words: kinetic words only -> kinetic, ethereal words
    only -> ethereal, both -> ambiguous (ethereal, plus one co-spec question), neither -> ethereal (the default for a thin prompt)."""
    answers = answers or {}
    for src, val in (("flag", flag), ("answer", answers.get("dialect")), ("prompt", _labelled(prompt or "", "dialect"))):
        v = str(val or "").strip().lower()
        if v in DIALECT_NAMES:
            return dict(name=v, source=src, matched=[], ambiguous=False)
        if v and src != "prompt":
            raise ValueError(f"dialect {val!r}: use one of {', '.join(DIALECT_NAMES)}")
    k, e = _hits(_KINETIC_WORDS, prompt), _hits(_ETHEREAL_WORDS, prompt)
    if k and e:
        return dict(name=DEFAULT_DIALECT, source="default", matched=sorted(set(k + e)), ambiguous=True)
    if k:
        return dict(name="kinetic", source="prompt", matched=k, ambiguous=False)
    if e:
        return dict(name="ethereal", source="prompt", matched=e, ambiguous=False)
    return dict(name=DEFAULT_DIALECT, source="default", matched=[], ambiguous=False)


def profile(dialect):
    return DIALECTS[dialect or DEFAULT_DIALECT]


def type_style(dialect):
    return profile(dialect)["type"]


def anim_by_beat(dialect):
    return ANIM_BY_BEAT_ETHEREAL if dialect == "ethereal" else ANIM_BY_BEAT

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
            if not re.match(r"^[ \t]*(?:idea|hook|problem|demo|payoff|cta|ask|call to action|features?|preset|style|format|dialect|audience|promise)\s*:", ln, re.I)]
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


def world(prompt, answers, dialect=None):
    """(plate A look, plate B look, source). The person's own words first; keywords from the prompt next; else the dialect's default."""
    given = (answers or {}).get("world")
    if given:
        return str(given).strip().rstrip("."), str(given).strip().rstrip("."), "answer"
    low = " ".join(re.findall(r"[a-z]+", (prompt or "").lower()))
    words = set(low.split())
    eth = dialect == "ethereal"
    for keys, (a, b) in (WORLDS_ETHEREAL if eth else WORLDS):
        if words & set(keys):
            return a, b, "prompt"
    dflt = DEFAULT_WORLD_ETHEREAL if eth else DEFAULT_WORLD
    return dflt[0], dflt[1], "default"


def plates_for(prompt, answers, rows, dialect=None):
    """Plates to generate (non-UI, `ui: false`): A under hook + problem, B under demo + payoff, an end plate that reuses B's world."""
    a, b, src = world(prompt, answers, dialect)
    prof = profile(dialect)
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
            id=pid, kind="image", aspect="16:9", seconds=prof["plates"]["seconds"], ui=False, world_source=src, why=why, shots=uses[pid],
            prompt=f"{look[0].upper() + look[1:]}. {PLATE_STYLE[prof['name']]} {PLATE_GUARD}",
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


def retime(plan_rows, dialect, bpm=120.0):
    """Ethereal holds: the plan's per-beat budgets (the spine's proportions) re-split into fewer, longer shots (about 5 s, the end
    card one shot). Kinetic keeps the plan's own cut rate."""
    if dialect != "ethereal":
        return plan_rows
    tgt = DIALECTS["ethereal"]["pacing"]["target_shot_s"]
    g = beat_grid(bpm)
    out = []
    for beat in P.SHOT_BEATS:
        group = [r for r in plan_rows if r["beat"] == beat]
        if not group:
            continue
        total = sum(float(r["seconds"]) for r in group)
        n = 1 if beat == "ask" else max(1, round(total / tgt))
        each = max(g, round(total / n / g) * g)
        secs = [each] * (n - 1)
        secs.append(round(total - sum(secs), 6))
        out += [dict(group[0], seconds=round(v, 3)) for v in secs]
    need = end_card_need(sum(float(r["seconds"]) for r in out))
    while out and out[-1]["beat"] == "ask" and out[-1]["seconds"] < need - 1e-6:
        donor = max(out[:-1], key=lambda r: r["seconds"], default=None)
        if donor is None or donor["seconds"] - g < 3.0:
            break
        donor["seconds"] = round(donor["seconds"] - g, 3)
        out[-1]["seconds"] = round(out[-1]["seconds"] + g, 3)
    return out


def end_card_need(master_s):
    """The end card's held minimum in the ethereal dialect: 6 s, or a quarter of a short master."""
    return round(min(DIALECTS["ethereal"]["pacing"]["end_card_min_s"], 0.25 * float(master_s)), 3)


def assign_rows(plan_rows, stills, master_s, bpm=120.0, dialect=None):
    """One composition row per planned shot: framing, which still, plate, motion. Kinetic re-cuts the montage to accelerate;
    ethereal never goes fullscreen, never opens on a UI shot and holds the payoff."""
    eth = dialect == "ethereal"
    plan_rows = retime(plan_rows, dialect, bpm)
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
        if beat == "payoff" and cls["recap_montage"] and not eth and group and sum(secs) >= 4.0:
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
            if videos and not eth:
                framing, src, why = "fullscreen", videos[0], "action hook: real footage, peak action"
            else:
                framing, why = "plate", ("hook: a quiet plate and the first words, the stills come after" if eth
                                         else "hook: the promise in big type by 0.5 s; a still is not action")
        elif beat == "demo" and videos and not eth and i == (count["demo"] + 1) // 2:
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
        push = ETHEREAL_PUSH if eth else (0.06 if beat != "payoff" else 0.03)
        motion = dict(push_in=0.0 if framing == "plate" else push, drift=framing == "plate")
        if eth:
            motion["ease"] = "linear"
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


def _sources(prompt, answers, defaults=None):
    srcs = [str(prompt or "")]
    for v in list((answers or {}).values()) + list((defaults or {}).values()):
        if isinstance(v, (list, tuple)):
            srcs.extend(str(x) for x in v)
        elif v:
            srcs.append(str(v))
    return srcs


def grounded(text, sources):
    """Is `text` a contiguous run of whole words in one of the person's own texts?"""
    t = " " + _norm(text) + " "
    return bool(_norm(text)) and any(t in " " + _norm(s) + " " for s in sources)


def make_cards(prompt, beats, beat_sources, answers, idea=None, dialect=None, defaults=None):
    """Kinetic caption cards from the person's own words, one idea per beat. A beat with no words of theirs gets a placeholder
    card (`status: needs-copy`) naming the co-spec question that fills it; the card never carries invented text."""
    answers = answers or {}
    defaults = defaults or {}
    ts = type_style(dialect)
    ph = phrases(prompt) or ([idea] if idea else [])
    feats = parse_list(answers.get("features")) or parse_list(_labelled(prompt, "features?"))
    feats = feats[:MAX_FEATURES]
    claims = [c for c in parse_claims(answers.get("must_keep")) if c["text"]]
    by_beat = {b: [] for b in P.SHOT_BEATS}

    def labelled(beat_key):
        return beats.get(beat_key) if beat_sources.get(beat_key) == "prompt" and beats.get(beat_key) else None

    promise = (answers.get("promise") or "").strip() or None
    hook = labelled("hook") or (ph[0] if ph else None)
    payoff = labelled("payoff") or promise or (ph[-1] if len(ph) > 1 else None) or hook
    if promise and not labelled("hook") and _norm(hook or "") == _norm(promise):
        hook = next((p for p in ph if _norm(p) != _norm(promise)), promise)
    problem = labelled("problem") or (ph[1] if len(ph) > 2 else None)
    cta = answers.get("cta") or labelled("cta")
    cta_src = "answer" if answers.get("cta") else "prompt"
    if not cta and defaults.get("cta"):
        cta, cta_src = defaults["cta"], "team-default"
    for beat, texts, src in (("hook", [hook], "prompt"), ("problem", [problem], "prompt"),
                             ("demo", feats or [None], "answer" if answers.get("features") else "prompt"),
                             ("payoff", [payoff], "answer" if promise and payoff == promise else "prompt"), ("ask", [cta], cta_src)):
        for text in texts:
            if not text:
                if dialect == "ethereal" and beat in ("problem", "demo"):
                    continue            # a quiet beat: the panels carry it, nothing waits on words
                by_beat[beat].append(dict(beat=beat, text=None, status="needs-copy", source=None,
                                          needs={"hook": "idea", "problem": "idea", "demo": "features", "payoff": "idea",
                                                 "ask": "cta"}[beat]))
                continue
            for k, piece in enumerate(chunks(str(text), ts["max_words_per_card"])):
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
        spec = anim_by_beat(dialect)[c["beat"]]
        c.update(anim=spec["anim"], size_pct=spec["size_pct"], sync=ts["sync"] if c["text"] else None)
        for k in ("from", "weight", "brackets", "anchors"):
            if spec.get(k):
                c[k] = spec[k]
        c["vo"] = c["text"] if ts["vo_reads_onscreen"] else None
    return cards


def place_cards(rows, cards, bpm=120.0, dialect=None):
    """Put each card on a shot of its beat that can carry type (never over a UI panel), spread evenly, snapped to the beat grid.
    Fullscreen rows carry none. More cards than shots: the surplus stays unplaced and is listed (one idea per beat)."""
    unplaced = []
    ts = type_style(dialect)
    eth = dialect == "ethereal"
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
            words = len(str(c["text"]).split())
            if eth:
                need = max(ts["min_hold_s"], 0.4 * words)
                at = snap(min(0.75, max(r["seconds"] - need, 0.0)), bpm)
                dur = round(max(min(r["seconds"] - at - 0.5, r["seconds"] - at), ts["min_hold_s"]), 3)
            else:
                need = max(ts["min_hold_s"], 0.3 * words)
                at = 0.0 if (beat == "hook" and r["n"] == rows[0]["n"]) else snap(min(0.25, max(r["seconds"] - need, 0.0)), bpm)
                dur = round(max(r["seconds"] - at, ts["min_hold_s"]), 3)
            c.update(shot=r["id"], at=at, dur=dur)
            r["cards"].append(c["id"])
    return unplaced


def build(prompt, plan, stills=None, answers=None, bpm=120.0, trigger="thin+stills", dialect=None, defaults=None):
    """The `plan.designed` block for a plan built by `gapfill.build_plan`. `dialect` = an explicit choice (flag) or None (read the prompt)."""
    from . import cospec as CS
    answers = dict(answers or {})
    defaults = dict(defaults or {})
    dsel = pick_dialect(prompt, dialect, answers)
    dn = dsel["name"]
    prof = profile(dn)
    eth = dn == "ethereal"
    scanned = CS.apply_roles(scan_stills(stills or []), answers)
    master = plan["length"]["master_s"]
    rows = assign_rows(plan["shot_list"], scanned, master, bpm, dn)
    cards = make_cards(prompt, plan["beats"], plan["beat_sources"], answers,
                       idea=plan["idea"] if plan.get("idea_source") == "prompt" else None, dialect=dn, defaults=defaults)
    unplaced = place_cards(rows, cards, bpm, dn)
    plates = plates_for(prompt, answers, rows, dn)
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
        if c.get("source") == "team-default" and not any(n["kind"] == "confirm" for n in needs):
            needs.append(dict(kind="confirm", id=c["id"], text=c["text"],
                              why="the end card uses the team default CTA you passed with --default; the product owner confirms it is right for this product",
                              then="promo cospec --answer cta='<exact words>' to replace it"))
    for cl in [c for c in parse_claims(answers.get("must_keep")) if c["text"] and not c["evidence"]]:
        needs.append(dict(kind="evidence", text=cl["text"], why="a must-keep claim needs what on screen proves it before it becomes a card",
                          then="promo cospec --answer 'must_keep=<claim> | <evidence>'"))
    if any(p["id"] for p in plates):
        needs.append(dict(kind="plates", ids=[p["id"] for p in plates], why="non-UI backdrop plates to generate (rule 1 carve-out)",
                          then="promo gen plan; make each; promo gen register ..."))
    if eth:
        needs.append(dict(kind="audio", why="ethereal is music-led: a licensed ambient / lo-fi bed plus click and whoosh sfx in assets.yaml "
                                            "(test_only for an internal test); nothing is bundled and nothing is invented",
                          then="promo fetch / promo assets"))
    conflicts = []
    if eth:
        conflicts.append(dict(
            id="abstracted-ui-vs-rule-1", rules=["AGENTS.md 0.1 real footage only", "AGENTS.md 0.2 never edit the app's UI"],
            ask="The ethereal reference shows abstracted UI (a lone search bar, stylized loading nodes). Generating or drawing product UI breaks "
                "rule 1, so this plan does not.",
            plan="Abstraction is done in type (brackets, selection anchors, an inline thumb of a real still), by small panels of the real stills "
                 "floating in air, and by tight crops of them. Nothing is drawn on or generated for the UI.",
            decision="pending: Patrick (record with `promo brief conflict` before a final)"))
    ts = prof["type"]
    return dict(
        enabled=True,
        trigger=trigger,
        dialect=dict(dsel, aka=prof["aka"], summary=prof["summary"], pacing=prof["pacing"], camera=prof["camera"], ui=prof["ui"], plates=prof["plates"],
                     grade=prof["grade"], transitions=prof["transitions"],
                     note="ethereal is the default for a thin prompt; kinetic when the words say so (`--dialect`, a `dialect:` line or a co-spec answer)."),
        audio=dict(prof["audio"]),
        note=("Craft plan, not copy. Framing, type curves, plates and montage are the system's choices (edit them); every word on a card is "
              "yours (prompt, co-spec answer or a team default you passed). Anything marked needs-* is waiting on you; nothing is invented to fill it."),
        stills=scanned,
        length_band=length_band(master),
        spine=spine(master),
        reference=dict(**{k: v for k, v in REFERENCE.items() if k != "segments"}),
        type_style=ts,
        framing_hierarchy=dict(
            primary="floating", fullscreen=("never in ethereal (no fullscreen app chrome)" if eth
                                            else "peak action only, real footage only (a still is never fullscreen)"),
            device="context; bezel only, nothing drawn on the UI", plate="type over a generated plate, no UI",
            counts={f: sum(1 for r in rows if r["framing"] == f) for f in FRAMINGS},
            fullscreen_share=round(n_full / len(ui_rows), 3) if ui_rows else 0.0,
        ),
        plates=plates,
        kinetic_cards=cards,
        unplaced_cards=unplaced,
        shots=rows,
        montage=dict(beat="payoff", enabled=length_band(master)["recap_montage"] and not eth,
                     shots=[r["id"] for r in rows if r["beat"] == "payoff"],
                     durations=[r["seconds"] for r in rows if r["beat"] == "payoff"], accelerates=not eth,
                     min_shot_s=MIN_SHOT_S, reference_median_s=REFERENCE["median_shot_s"]),
        loudness_lufs=-14.0,
        bpm=bpm,
        needs=needs,
        conflicts=conflicts,
        never=["invented claims, numbers or URLs", "invented or generated app UI", "text, logos, screens or people on a plate",
               "type over app UI pixels"] + (["whip pans, shake, heavy motion blur", "fullscreen app chrome"] if eth else []),
    )


def broll_entries(designed):
    """`broll:` entries (promo gen plan format) for the plates."""
    return [dict(id=p["id"], kind=p["kind"], prompt=p["prompt"], seconds=p["seconds"], aspect=p["aspect"]) for p in designed.get("plates") or []]


# ---------------------------------------------------------------- the refusal: no invented words, numbers or URLs
def check_no_invention(designed, prompt, answers=None, defaults=None):
    """Problems (empty = fine). Card text and the claims must come from the person; plate prompts must carry the guard and no
    product words, numbers or URLs."""
    srcs = _sources(prompt, answers, defaults)
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
        if r["framing"] == "fullscreen" and (designed.get("dialect") or {}).get("name") == "ethereal":
            bad.append(f"shot {r['id']}: fullscreen app chrome is not allowed in the ethereal dialect")
    return bad


# ---------------------------------------------------------------- compile to cinema shots (the build wiring)
def compile_shots(designed, bpm=None, ready=(), sfx=()):
    """`shots:` for promo.yaml: `cinema` shots (floating panel over a plate, kinetic type, slow push-in), from a designed plan.
    UI shots point at the supplied stills by clip id (register them with `promo footage add`). A plate is used only once it is in
    `ready` (registered in the footage manifest); until then the shot falls back to a dark plate / the blurred copy, so a preview builds.
    `sfx` = names in the project's sfx library: ethereal puts a soft click on each snap and a whoosh on each resolve only if they exist."""
    ready, sfx = set(ready), set(sfx)
    bpm = float(bpm or designed.get("bpm") or 120.0)
    bsec = 60.0 / bpm
    eth = (designed.get("dialect") or {}).get("name") == "ethereal"
    panels = ETHEREAL_PANEL if eth else PANEL
    cards = {c["id"]: c for c in designed.get("kinetic_cards") or []}
    stills = {s["id"]: s for s in designed.get("stills") or []}
    thumb_id = next((s["id"] for s in designed.get("stills") or [] if s.get("exists") and s["orientation"] != "portrait"), None)
    click = "click" if "click" in sfx else "tick" if "tick" in sfx else None
    out, cur, seen = [], 0.0, set()
    for r in designed["shots"]:
        b0 = round(cur / bsec * 2) / 2.0
        cur += float(r["seconds"])
        b1 = round(cur / bsec * 2) / 2.0
        fr = r["framing"]
        shot = dict(id=r["id"], beats=[b0, b1], type="cinema")
        look = copy.deepcopy(ETHEREAL_LOOK) if eth else {}
        push = float(r["motion"].get("push_in") or 0.0)
        drift_end = 0.97 if eth else 0.94
        if eth:        # a floaty dolly stays under the dialect's zoom rate however short the shot
            cap = round(ETHEREAL_MAX_DRIFT["zoom_per_s"] * 0.8 * float(r["seconds"]), 3)
            push, drift_end = min(push, cap), max(0.97, round(1.0 - cap, 3))
        ease = ["linear"] if eth else []
        if fr == "plate":
            shot["ui"] = False
            if r.get("plate") in ready:
                shot["source"] = r["plate"]
                shot["t_in"] = 0.0
            look["backdrop"] = "none"
            if eth and r.get("plate") not in ready:
                look["plate_fill"] = dict(ETHEREAL_FILL)
            if r["motion"].get("drift"):
                shot["cam"] = [[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, drift_end, *ease]]
        else:
            shot["source"] = r["ui_source"]
            shot["t_in"] = 0.0
            if r["motion"].get("focus"):
                fx, fy = r["motion"]["focus"]
                w0 = float(r["motion"].get("zoom_w", 0.8))
                shot["cam"] = [[0, fx, fy, w0], ["end", fx, fy, round(w0 - push, 3), *ease]]
            else:
                shot["cam"] = [[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, round(1.0 - push, 3), *ease]]
            if fr == "fullscreen":
                look["backdrop"] = "none"
            else:
                bd = ({"plate": r["plate"], "blur": 0.03, "dim": 1.0 if eth else 0.8, "warm": 0.0 if eth else 0.12}
                      if r.get("plate") in ready else {})
                if bd:
                    look["backdrop"] = bd
                elif eth:
                    look["backdrop"] = dict(fill=dict(ETHEREAL_FILL), warm=0.0)
                base = panels["device"] if fr == "device" else (panels["hero"] if r["beat"] == "demo" else panels["floating"])
                panel = dict(base, **{"in": dict(dur=0.3, from_scale=0.94, fade=True)})
                if eth:
                    panel.update(copy.deepcopy(ETHEREAL_PANEL_FX))
                if fr == "device":
                    panel["rim"] = dict(ETHEREAL_BEZEL if eth else BEZEL)
                    st = stills.get(r["ui_source"]) or {}
                    if st.get("orientation") == "portrait" and st.get("width") and st.get("height"):
                        panel.update(aspect=round(st["width"] / st["height"], 3), w=0.2 if eth else 0.22, cy=0.5)
                look["panel"] = panel
        if look:
            shot["look"] = look
        if eth and r["beat"] not in seen and fr != "fullscreen":
            shot["resolve"] = dict(ETHEREAL_RESOLVE)
            if "whoosh" in sfx:
                shot.setdefault("sfx", []).append(dict(sfx="whoosh", at=0.0, db=-18))
        seen.add(r["beat"])
        kin = []
        for cid in r["cards"]:
            c = cards[cid]
            if not c.get("text"):
                continue
            item = dict(text=c["text"], at=c["at"], dur=c["dur"], size_pct=c["size_pct"], anim=c["anim"])
            if c.get("from"):
                item["from"] = c["from"]
            if eth:
                item.update(uppercase=False, outline=False, shadow=False, color=list(TYPE_STYLE_ETHEREAL["fill"]), weight=c.get("weight", "Light"))
                for k in ("brackets", "anchors"):
                    if c.get(k):
                        item[k] = True
                if c["beat"] == "ask" and thumb_id:
                    item["thumb"] = thumb_id
                if click:
                    shot.setdefault("sfx", []).append(dict(sfx=click, at=c["at"], db=-14))
            if fr == "plate":
                item["cy"] = 0.5
            kin.append(item)
        if kin:
            shot["kinetic_copy"] = kin
        shot["notes"] = f"designed ({'ethereal' if eth else 'kinetic'}): {fr}; {r['why']}" + (f"; source {r['ui_source']}" if r.get("ui_source") else "")
        out.append(shot)
    return out


# ---------------------------------------------------------------- promo check
def camera_moves(spec_shot):
    """(pan_per_s, zoom_per_s) of the fastest segment of a shot's camera keys (0, 0 for a locked camera)."""
    from .spec import resolve_cam_keys
    keys = resolve_cam_keys(spec_shot.get("cam") or [], float(spec_shot.dur))
    pan = zoom = 0.0
    for k0, k1 in zip(keys, keys[1:]):
        dt = max(float(k1[0]) - float(k0[0]), 1e-6)
        pan = max(pan, math.hypot(float(k1[1]) - float(k0[1]), float(k1[2]) - float(k0[2])) / dt)
        zoom = max(zoom, abs(float(k1[3]) - float(k0[3])) / dt)
    return round(pan, 4), round(zoom, 4)


def gates(spec):
    """(gate, status, msg) for a project whose plan carries `designed:`. Empty when it does not."""
    plan = (getattr(spec, "raw", None) or {}).get("plan") or {}
    des = plan.get("designed")
    if not des:
        return []
    from .shots import cinema as CN
    dn = (des.get("dialect") or {}).get("name") or "kinetic"
    eth = dn == "ethereal"
    ts, prof = type_style(dn), profile(dn)
    answers = (plan.get("cospec") or {}).get("answers") or {}
    defaults = (plan.get("cospec") or {}).get("defaults") or {}
    srcs = _sources(plan.get("prompt", ""), answers, defaults)
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
    lo, hi = ts["size_pct_height"]
    for s, c in items:
        pct = CN.kinetic_pct(c)
        if not (lo - 1e-9 <= pct <= hi + 1e-9):
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r} size_pct {pct:g} outside {lo}-{hi}")
        words = len(CN.kinetic_text(c).split())
        hold = min(float(c.get("dur", 2.0)), s.dur - float(c.get("at", 0.0)))
        need = max(ts["min_hold_s"], (0.4 if eth else 0.3) * words)
        if hold < need - 1e-6:
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r} visible {hold:.2f}s < {need:.2f}s ({0.4 if eth else 0.3:g} s per word, min {ts['min_hold_s']}s)")
        if words > ts["max_words_per_card"]:
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r} has more than {ts['max_words_per_card']} words")
        if eth and (c.get("outline") is not False or c.get("shadow") is not False or c.get("uppercase") is not False):
            warn.append(f"shot {s.id} {CN.kinetic_text(c)!r}: ethereal type is sentence case with no outline and no shadow")
        if CN.is_ui(s):
            pb = CN.panel_box_of(spec, s)
            box = CN.kinetic_box(spec, s, c, (1920, 1080))
            if pb is None:
                clear.append(f"shot {s.id} {CN.kinetic_text(c)!r} is on a full-bleed UI shot (type belongs on a plate or in the panel margin)")
            elif box[0] < pb[2] and pb[0] < box[2] and box[1] < pb[3] and pb[1] < box[3]:
                clear.append(f"shot {s.id} {CN.kinetic_text(c)!r} box {[round(v) for v in box]} overlaps the UI panel {list(pb)}")
    out.append(("designed-kinetic", "WARN" if warn else "PASS", "; ".join(warn) or f"{len(items)} kinetic cards: size, hold and word count within the {dn} type style"))
    out.append(("designed-clear", "FAIL" if clear else "PASS", "; ".join(clear) or "no kinetic type over app UI"))
    cs = [s for s in spec.shots if s.type == "cinema"]
    ui = [s for s in cs if CN.is_ui(s)]
    full = [s for s in ui if CN.panel_box_of(spec, s) is None]
    if ui:
        share = len(full) / len(ui)
        msg = f"{len(ui) - len(full)} panel shots, {len(full)} fullscreen ({share:.0%})"
        if eth:
            out.append(("designed-framing", "FAIL" if full else "PASS",
                        msg + ("; ethereal never goes fullscreen (no app chrome edge to edge): use a floating panel" if full else "")))
        else:
            out.append(("designed-framing", "WARN" if share > 0.25 or len(full) > len(ui) - len(full) else "PASS",
                        msg + ("; floating panels over plates are the primary framing (fullscreen only for peak action)" if share > 0.25 else "")))
    lim = prof["camera"]["max_drift"]
    cam_bad, fast = [], []
    for s in cs:
        pan, zoom = camera_moves(s)
        if pan > lim["pan_per_s"] + 1e-9 or zoom > lim["zoom_per_s"] + 1e-9:
            fast.append(f"shot {s.id} moves {pan:g} pan/s, {zoom:g} zoom/s (limit {lim['pan_per_s']:g} / {lim['zoom_per_s']:g})")
        if eth:
            for key in ("shake", "whip", "whip_pan", "flash", "speed_lines"):
                if s.get(key):
                    cam_bad.append(f"shot {s.id} has {key}")
            if float(s.get("blur") or 0) > 1:
                cam_bad.append(f"shot {s.id} has shutter blur {s.get('blur')} (ethereal: zero blur)")
    msgs = cam_bad + fast
    out.append(("designed-camera", ("FAIL" if eth else "WARN") if msgs else "PASS",
                "; ".join(msgs) or f"{len(cs)} shots: camera within the {dn} limits ({prof['camera']['allowed']})"))
    durs = sorted(float(s.dur) for s in cs)
    if durs:
        med = durs[len(durs) // 2] if len(durs) % 2 else (durs[len(durs) // 2 - 1] + durs[len(durs) // 2]) / 2
        rate = len(durs) / max(sum(durs), 1e-6)
        lo_r, hi_r = prof["pacing"]["cuts_per_s"]
        bad_pace = []
        if med < prof["pacing"]["median_shot_min_s"] - 1e-9:
            bad_pace.append(f"median shot {med:.2f}s < {prof['pacing']['median_shot_min_s']:g}s")
        if rate > hi_r + 1e-9:
            bad_pace.append(f"{rate:.2f} cuts/s > {hi_r:g}")
        if eth and cs and cs[-1].dur < end_card_need(sum(durs)) - 1e-6:
            bad_pace.append(f"end card {cs[-1].dur:.1f}s < {end_card_need(sum(durs)):g}s")
        out.append(("designed-pace", "WARN" if bad_pace else "PASS",
                    "; ".join(bad_pace) or f"median shot {med:.2f}s, {rate:.2f} cuts/s ({dn}: {lo_r:g}-{hi_r:g})"))
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


ETHEREAL_PACING = "  pacing: {promise_by_s: 1.0, cut_rate: {overall: [0.05, 0.3], montage: [0.0, 0.35]}}   # ethereal: breathable holds (written by `promo designed apply`; delete to use the preset's)\n"


def ethereal_pacing(text):
    """Put a calmer `style.pacing` under the project's style block so the preset's cut-rate and promise gates do not WARN on long
    holds. Left alone when the style block already has a `pacing:` key."""
    from . import gapfill as GF
    lines = text.splitlines(keepends=True)
    try:
        start, end = GF._style_span(lines)
    except StopIteration:
        return text
    if re.search(r"(?m)^\s*pacing:", "".join(lines[start:end])):
        return text
    if re.match(r"^style:\s*\{", lines[start]):
        return text
    lines.insert(start + 1, ETHEREAL_PACING)
    return "".join(lines)


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
    problems = check_no_invention(des, plan.get("prompt", ""), (plan.get("cospec") or {}).get("answers"), (plan.get("cospec") or {}).get("defaults"))
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
    lib = ((getattr(spec, "raw", None) or {}).get("sfx") or {}).get("library") or {}
    shots = compile_shots(des, ready=ready, sfx=set(lib))
    from . import previz as PZ
    previz_notes = PZ.merge_cinema(shots, os.path.dirname(path))         # shots the agent directed in previz carry their camera / panel nudges
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
    if (des.get("dialect") or {}).get("name") == "ethereal":
        text = ethereal_pacing(text)
    else:
        text = re.sub(r"(?m)^  pacing:.*# ethereal: breathable holds.*\n", "", text)
    text = sync_timeline(text, plan.get("length", {}).get("master_s", 60), total)
    with open(path, "w") as f:
        f.write(text)
    return dict(path=path, shots=shots, registered=registered, ready_plates=sorted(ready), previz_notes=previz_notes)
