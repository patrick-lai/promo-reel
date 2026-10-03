"""Style presets (`style.preset` in promo.yaml, `promo new --style <name>`).

A preset is a named bundle of editorial rules so an agent does not have to invent a renderer for a new look:
pacing (what the cut grid is and how long shots/text must hold), a caption/card band, typography, allowed
transitions, and the `promo check` gates that enforce them. Values in the spec win over the preset (deep merge), so
a project only writes what it changes.

    style: {preset: anime-opening}             # + any overrides, e.g. band: {y0: 780}
    timeline: {grid: music/edit-v1.json, beats: 225}   # beat grid from a music JSON (tempo, bars, markers)

Presets:
  hero           calm product hero (the commission-ai-hero look): beat grid, dark pills in the 9:16-safe lower-middle
                 zone held >= 2 s, eased push-ins, cuts only. Same defaults the engine always had.
  anime-opening  kinetic title cards on real footage: cuts snapped to bar lines from a music grid, UI shots hold
                 >= 1 bar, text-free shots >= 1/2 bar, cards held >= 1 bar in ONE fixed lower-third band that never
                 covers app UI text, beat flashes / speed lines only at cuts and never over UI text, <= 3 flashes/s.
                 Shot type `anime` (promo/shots/anime.py) renders it.
  livestream     talk-show / livestream composite: long holds (>= 4 s), lower-left chyron band, cuts and
                 dissolves only (no flashes / speed lines), captions >= 2.5 s.
"""
from __future__ import annotations

import copy
import json
import os

FONT_DIR = "/usr/share/fonts/truetype/sand-box/google"
INTER = f"{FONT_DIR}/Inter/Inter-VariableFont_opsz,wght.ttf"
BARLOW = f"{FONT_DIR}/Barlow Condensed"

PRESETS = {
    "hero": dict(
        description="Calm product hero: eased push-ins on real UI, dark pills in the 9:16-safe lower-middle zone, cuts on beats.",
        pacing=dict(snap="beat", min_caption_hold_s=2.0),
        caption=dict(cx=960, cy=905, size=32, max_w=608, zone=dict(x0=656, x1=1264, y0=860, y1=950)),
        typography=dict(font=INTER, weight="SemiBold"),
        transitions=dict(allowed=["cut"]),
        checks=["caption-hold", "caption-zone", "beat-grid"],
        qa=dict(min_caption_hold=2.0, beat_subdivision=1),
    ),
    "anime-opening": dict(
        description="Anime-opening kinetic cards on real footage, bar-snapped cuts from a music grid, one fixed lower-third band.",
        pacing=dict(
            snap="bar",                 # cuts on bar lines (beats_per_bar from the grid)
            half_bar_cuts="text-free",  # a cut may sit on a half bar only next to a text-free shot
            ui_min_bars=1.0,            # shots showing app UI hold >= 1 bar
            textfree_min_bars=0.5,      # text-free shots (scenery, robots) hold >= 1/2 bar
            card_min_bars=1.0,          # every text card holds >= 1 bar ...
            word_min_s=0.6,             # ... and every word is readable >= 0.6 s
            card_start="bar",           # cards start on a bar line
            fx_max_frames=6,            # flash / speed-line window at a cut (frames at 30 fps)
            max_flashes_per_s=3,        # photosensitivity
        ),
        # ONE fixed band for every card in the whole opening (1920x1080 canvas units). On UI shots the footage is framed
        # ABOVE the band (layout: band) so a card can never sit on app UI text; text-free shots may run full-bleed.
        band=dict(x0=96, x1=1824, y0=800, y1=1040, fill=[14, 12, 34], alpha=235, accent=[255, 64, 129], accent2=[64, 220, 255],
                  rows=dict(title=dict(cy=868, size=104, max_w=1680), sub=dict(cy=952, size=42, max_w=1500),
                            tag=dict(cy=1004, size=28, max_w=600)),
                  # `pillar_fill: brand` on a fit: contain shot: the opening's night-sky brand background (sampled from the
                  # shot-03 night plate) fills the pillarbox, so a narrow crop reads as a deliberate panel
                  brand_bg=dict(top=[10, 8, 44], mid=[16, 24, 80], bottom=[14, 12, 34], stars=70, glow=0.18)),
        typography=dict(title_font=f"{BARLOW}/BarlowCondensed-BlackItalic.ttf", sub_font=f"{BARLOW}/BarlowCondensed-SemiBoldItalic.ttf",
                        tag_font=f"{BARLOW}/BarlowCondensed-BoldItalic.ttf", uppercase_titles=True, stroke=6,
                        slam=dict(dur=0.12, scale=1.22), fade_out=0.08),
        transitions=dict(allowed=["cut", "flash", "speed_lines"], placement="between-shots",
                         flash=dict(frames=3, alpha=0.85), speed_lines=dict(frames=6, alpha=0.7)),
        checks=["grid", "bar-cuts", "shot-hold", "card-hold", "card-band", "card-ui-clear", "fx-between", "flash-rate",
                "claims", "named", "markers", "placeholders"],
        qa=dict(min_caption_hold=2.0, beat_subdivision=2),
    ),
    "livestream": dict(
        description="Talk-show / livestream composite: long holds, lower-left chyron, cuts and dissolves only.",
        pacing=dict(snap="beat", min_shot_s=4.0, min_caption_hold_s=2.5),
        caption=dict(cx=520, cy=960, size=34, max_w=900, zone=dict(x0=64, x1=1000, y0=900, y1=1020)),
        typography=dict(font=INTER, weight="SemiBold"),
        transitions=dict(allowed=["cut"]),          # dissolves: not rendered by the engine yet
        checks=["caption-hold", "caption-zone", "beat-grid", "shot-hold", "no-fx"],
        qa=dict(min_caption_hold=2.5, beat_subdivision=1),
    ),
}


class StyleError(Exception):
    pass


def names():
    return sorted(PRESETS)


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def resolve(raw):
    """Resolved style dict for a raw spec: preset defaults deep-merged with the spec's `style:` block.
    No `style.preset` = legacy behaviour (hero defaults, nothing injected)."""
    st = (raw or {}).get("style") or {}
    name = st.get("preset")
    if not name:
        return dict(st, preset=None)
    if name not in PRESETS:
        raise StyleError(f"unknown style preset {name!r}; have {names()}")
    over = {k: v for k, v in st.items() if k != "preset"}
    res = deep_merge(PRESETS[name], over)
    res["preset"] = name
    return res


def qa(raw):
    """Effective qa thresholds: preset qa defaults overlaid with the spec's own `qa:`."""
    st = resolve(raw)
    return deep_merge(st.get("qa") or {}, (raw or {}).get("qa") or {})


# ---------------------------------------------------------------- beat grid from a music JSON
class BeatGrid:
    """Beat/bar grid loaded from a music analysis JSON (e.g. anime/music/edit-v1.json).

    Accepted keys: tempo_bpm (or bpm), beat_s (optional), beats [{i, t, downbeat}], bars [{bar, t, phrase_start}],
    markers {name: seconds}, time_signature "4/4", duration_s. Edit beat k sits at k * 60 / bpm; bar lines are the
    downbeats (first downbeat = beat offset)."""

    def __init__(self, data, path=None):
        self.path = path
        self.data = data
        self.bpm = float(data.get("tempo_bpm") or data.get("bpm"))
        self.B = 60.0 / self.bpm
        ts = str(data.get("time_signature", "4/4"))
        self.beats_per_bar = int(ts.split("/")[0])
        self.beats = data.get("beats") or []
        self.bars = data.get("bars") or []
        self.markers = dict(data.get("markers") or {})
        self.duration = data.get("duration_s")
        downs = [b["i"] for b in self.beats if b.get("downbeat")]
        self.offset = (downs[0] % self.beats_per_bar) if downs else 0

    @classmethod
    def load(cls, path):
        if not os.path.exists(path):
            raise StyleError(f"beat grid not found: {path}")
        with open(path) as f:
            return cls(json.load(f), path)

    def t(self, beat):
        return beat * self.B

    def beat_of(self, t):
        return t / self.B

    def is_bar(self, beat, frac=1.0, tol=1e-6):
        """beat on a bar line (frac=1) or a fraction of a bar (frac=0.5 = half-bar line)."""
        step = self.beats_per_bar * frac
        x = (beat - self.offset) / step
        return abs(x - round(x)) < tol

    def bar_beats(self, n_bars):
        return n_bars * self.beats_per_bar

    def phrase_starts(self):
        return [b["t"] for b in self.bars if b.get("phrase_start")]

    def max_drift(self):
        """Largest |JSON beat time - uniform grid time| in seconds (should be ~0 for an edit made on the grid)."""
        return max((abs(b["t"] - b["i"] * self.B) for b in self.beats), default=0.0)

    def snap(self, t, frac=1.0):
        """Nearest bar (or bar fraction) line to time t, as a beat number."""
        step = self.beats_per_bar * frac
        return round((self.beat_of(t) - self.offset) / step) * step + self.offset

    def table(self):
        rows = []
        n = len(self.bars) or 0
        for b in self.bars:
            beat = round(b["t"] / self.B)
            names_ = [k for k, v in self.markers.items() if abs(v - b["t"]) < 0.02]
            rows.append(dict(bar=b.get("bar"), beat=beat, t=round(b["t"], 4), phrase=bool(b.get("phrase_start")), markers=names_))
        return rows if n else []
