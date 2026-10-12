"""Style presets (`style.preset` in promo.yaml, `promo new --style <name>`).

A preset is a named bundle of editorial rules so an agent does not have to invent a renderer for a new look:
pacing (what the cut grid is and how long shots/text must hold), a caption/card band, typography, allowed
transitions, and the `promo check` gates that enforce them. Values in the spec win over the preset (deep merge), so
a project only writes what it changes.

    style: {preset: anime-opening}             # + any overrides, e.g. band: {frac: 0.18} (or an absolute y0)
    timeline: {grid: music/edit-v1.json, beats: 225}   # beat grid from a music JSON (tempo, bars, markers)

Presets:
  hero           calm product hero (the hero look): beat grid, dark pills in the 9:16-safe lower-middle
                 zone held >= 2 s, eased push-ins, cuts only. Same defaults the engine always had.
  anime-opening  kinetic title cards on real footage: cuts snapped to bar lines from a music grid, UI shots hold
                 >= 1 bar, text-free shots >= 1/2 bar, cards held >= 1 bar in ONE fixed lower-third band that never
                 covers app UI text, beat flashes / speed lines only at cuts and never over UI text, <= 3 flashes/s.
                 Shot type `anime` (promo/shots/anime.py) renders it.
  livestream     talk-show / livestream composite: long holds (>= 4 s), lower-left chyron band, cuts and
                 dissolves only (no flashes / speed lines), captions >= 2.5 s.
  cinematic-story  short-film look ("dots"): UI as contained depth-of-field panels over a blurred copy of themselves,
                 warm low-key grade / bloom / vignette / grain on the backdrop only (UI pixels are never graded), slow
                 eased camera, shots >= 0.8 s (UI >= 2.5 s), cut rate calm -> busier -> calm, fades from / to black,
                 sparse serif title + lower-third copy, no flashes. Shot type `cinema` (promo/shots/cinema.py), look in
                 promo/grade.py.
  podcast        podcast / VTuber show (promo/podcast.py): Live2D hosts overlaid on the real app with no box by default
                 (boxed / two-shot / speaker cam are layouts), speaker-coloured subtitles (<= 35 chars, >= 2 s), shots
                 >= 3 s, cuts only, lines on a half-beat grid. Shot type `podcast` (promo/shots/podcast.py); `promo podcast`
                 turns a script into VO, timeline and shots.
  horizon        Opus-5.5-style horizon film: rapid cuts (1/2 beat allowed in the burst, shots >= 0.3 s hard / 0.4 s soft)
                 of real surfaces, each framed so one real edge forms a horizon (`anchor`), ONE serif sentence on the
                 horizon whose words change while the picture keeps cutting (show-level `horizon_text`, each word spans
                 >= 2 shots or >= 1.2 s), burst followed by a hold >= 3 s, held `dawn` sunrise end card, cuts only.
                 Shot types `horizon` and `dawn` (promo/shots/horizon.py).
  anime-mv       anime music video (Eve "心海" look, measured): a 2.35:1 picture band on a cream page, ONE small tracked
                 Mincho lyric line under it, flat-cel generated or drawn plates (never product UI), drawings on 2s, cuts on
                 beats from a music grid (half beats in bursts, shots >= 0.25 s, median ~1.5 s), petals / bubbles, whiteouts
                 and ink wipes on big cuts (<= 3 flashes/s). Shot type `mv` (promo/shots/mv.py), lyrics in promo/lyrics.py,
                 plates and the look bible via `promo mv`.

Version 2 (`style.version: 2` or `preset: hero@2`) of hero, anime-opening and livestream adds the reference-study
pacing targets (docs/PRODUCT-DEFAULTS.md): phrase sync by default, cut-rate curves, one planned hold. Version 1 is
what `PRESETS` holds and stays the default when a spec names a preset with no version.
"""
from __future__ import annotations

import copy
import json
import os

FONT_DIR = "/usr/share/fonts/truetype/sand-box/google"
INTER = f"{FONT_DIR}/Inter/Inter-VariableFont_opsz,wght.ttf"
BARLOW = f"{FONT_DIR}/Barlow Condensed"
SERIF_FONTS = ["/System/Library/Fonts/NewYork.ttf", "/System/Library/Fonts/Supplemental/Georgia.ttf",
               "/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf"]

from . import grade as _grade  # noqa: E402  (look defaults for cinematic-story; numpy + PIL only)

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
        # The band is a preset parameter: `frac` = band height as a fraction of the frame (bottom-anchored; y0 = H*(1-frac)),
        # rows are placed relative to it (rel_cy / rel_cx within the band, rel_size = font px / band height), so one
        # number re-flows the whole layout. Explicit y0 / y1 / row cy / size (project overrides) still win.
        # v6: 15% (162 px at 1080p) instead of the 26% (280 px) the v1-v5 band took.
        band=dict(frac=0.15, pad=4, x0=96, x1=1824, min_cap_px=18,
                  fill=[14, 12, 34], alpha=235, accent=[255, 64, 129], accent2=[64, 220, 255],
                  rows=dict(title=dict(rel_cy=0.33, rel_size=0.44, max_w=1680),
                            sub=dict(rel_cy=0.74, rel_size=0.21, max_w=1100),
                            tag=dict(rel_cy=0.74, rel_cx=0.93, rel_size=0.175, max_w=300)),
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
    "cinematic-story": dict(
        description="Cinematic short film on real screen recordings: contained depth-of-field panels, warm low-key grade on the backdrop only, slow camera, fades, sparse serif copy.",
        pacing=dict(
            snap="beat",
            min_shot_s=0.8,             # nothing cuts faster than 0.8 s
            ui_min_hold_s=2.5,          # shots that show app UI hold >= 2.5 s (FAIL; a spec may lower it, e.g. 1.5)
            ui_short_hold_s=2.0,        # a UI shot under this with a camera move over max_camera_rate WARNs (ui-hold-short)
            min_caption_hold_s=2.0,     # title / lower-third copy visible >= 2 s
            cut_rate=dict(thirds=[0.3, 0.6, 0.3], tol=0.2),   # cuts/s in each third of the runtime (WARN): calm, build, calm
            max_camera_rate=dict(zoom=0.25, pan=0.10),       # slow eased camera only (WARN): |d ln w| / s and |d centre| / s
        ),
        # `look:` is the preset default of promo/grade.py (DEFAULT_LOOK); the spec's style.look and each shot's look: merge over it.
        # protect_ui: grade / bloom / grain / vignette only on the backdrop (and on ui: false footage), never on UI pixels.
        look=_grade.DEFAULT_LOOK,
        caption=dict(cx=960, cy=905, size=32, max_w=608, zone=dict(x0=656, x1=1264, y0=860, y1=950)),   # unused (no pills); engine contract
        typography=dict(serif_fonts=SERIF_FONTS, color=[244, 236, 224]),
        transitions=dict(allowed=["cut", "fade"]),        # fade_in / fade_out from / to black; no flashes, no speed lines
        checks=["shot-hold", "ui-hold", "ui-hold-short", "no-fx", "cinema-keys", "ui-protect", "copy-hold", "copy-clear", "copy-size", "claims",
                "cut-curve", "slow-camera", "fades", "serif-font", "screen-quad", "screen-ui"],
        qa=dict(min_caption_hold=2.0, beat_subdivision=1),
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
    "podcast": dict(
        description="Podcast / VTuber show: Live2D hosts overlaid on the real app (no box by default), speaker-coloured subtitles, long holds, cuts only.",
        pacing=dict(snap="beat", min_shot_s=3.0, min_caption_hold_s=2.0),
        # the generic caption pills (overlays) keep the hero's 9:16-safe zone; subtitles have their own two-row zone (promo/podcast.py SUB_ZONE)
        caption=dict(cx=960, cy=905, size=32, max_w=608, zone=dict(x0=656, x1=1264, y0=860, y1=950)),
        typography=dict(font=INTER, weight="SemiBold"),
        transitions=dict(allowed=["cut"]),
        checks=["caption-hold", "caption-zone", "shot-hold", "no-fx"],
        qa=dict(min_caption_hold=2.0, beat_subdivision=2),         # lines start on the half-beat grid
    ),
    "horizon": dict(
        description="Horizon film (Opus 5.5 look): rapid cuts of real surfaces each framed on a real edge, ONE serif line on the horizon whose words change across cuts, a held dawn end card.",
        pacing=dict(
            snap="beat",                # cuts on whole beats ...
            burst_snap=0.5,             # ... or half beats inside the burst window
            min_shot_s=0.3,             # hard FAIL under this
            soft_min_shot_s=0.4,        # WARN under this
            burst_below_s=1.0,          # auto burst window = consecutive shots shorter than this (style.burst: [beat0, beat1] overrides)
            burst_min_shots=3,
            hold_after_burst_s=3.0,     # the burst must be followed by a single shot held at least this long
            text_min_shots=2,           # a horizon word spans >= 2 shots ...
            text_min_s=1.2,             # ... or >= this many seconds
            word_min_s=0.5,             # and is never shorter than this
            max_dips_per_s=3,           # flash_dip photosensitivity (only when allowed below)
            wordless_open_frac=0.40,    # no horizon word starts before this fraction of the burst (the reference keeps ~45 % wordless)
        ),
        caption=dict(cx=960, cy=905, size=32, max_w=608, zone=dict(x0=656, x1=1264, y0=860, y1=950)),    # unused (no per-shot captions); the generic caption gates need it
        # the persistent serif line (global, composited over every horizon shot): ~10 % of the frame height (the reference
        # film's words), baseline kissing the horizon, no pill / box. Override with style.horizon_text_style: {size_frac,
        # gap_frac, shadow: {blur, alpha, dy}} (all fractions of the frame height; shadow: false = off).
        horizon_text=dict(size_frac=0.10, gap_frac=0.004, fallback_y=0.58, top_margin_frac=0.05, x=0.5, fade_frames=3,
                          color_light=[255, 255, 255], color_dark=[17, 19, 24], lum_threshold=0.6,
                          shadow=dict(blur=0.012, alpha=0.55, dy=0.002), max_w_frac=0.8, max_words=12),
        typography=dict(serif=SERIF_FONTS, sans=[INTER, "/System/Library/Fonts/Helvetica.ttc"]),
        # flat gradient above a footage edge that sits low in the frame (never fake UI): top colour -> `bottom` (auto = the footage's top row)
        sky=dict(top=[10, 14, 30], bottom="auto", max_frac=0.6, warn_frac=0.08),   # FAIL above max_frac, WARN (horizon-sky) above warn_frac of the frame height
        # dawn: a thin navy -> teal rim (reach) that turns amber only in the last 0.6 s (amber_at seconds; default = shot dur - 0.6);
        # name only by default (wordmark / tagline have no default text). Old tall amber card: reach [0.12, 0.80], amber_at 0,
        # name_frac 0.11, name_y 0.40.
        dawn=dict(rise_s=3.0, reach=[0.05, 0.22], name_at=0.3, tagline_at=1.0, fade_s=0.7, name_frac=0.065, wordmark_frac=0.024,
                  tagline_frac=0.034, name_y=0.47, wordmark_y=0.545, tagline_y=0.60, min_hold_s=3.0, amber_s=0.45,
                  stops=[[0.0, [255, 186, 100]], [0.2, [226, 130, 86]], [0.45, [28, 92, 110]], [0.7, [14, 52, 78]], [1.0, [7, 10, 30]]]),
        transitions=dict(allowed=["cut"], flash_dip=dict(frames=3, alpha=0.7, color=[255, 244, 224])),   # flash_dip: opt in via allowed: [cut, flash_dip]
        checks=["horizon-shot-hold", "horizon-cuts", "horizon-burst-hold", "horizon-text", "horizon-text-fit", "horizon-edge",
                "horizon-transitions", "horizon-dawn", "horizon-text-ui", "horizon-wordless-open", "horizon-sky", "caption-hold", "beat-grid"],
        qa=dict(min_caption_hold=2.0, beat_subdivision=2),
    ),
    "anime-mv": dict(
        description="Anime music video: a letterboxed 2.35:1 picture band on a cream page, one small lyric line under it, flat-cel generated plates, drawings on 2s, cuts on the beat.",
        pacing=dict(
            snap="beat",                # cuts on beats from the music grid ...
            burst_snap=0.5,             # ... or half beats inside a burst (consecutive shots < burst_below_s)
            burst_below_s=1.0,
            min_shot_s=0.25,            # FAIL under this (the reference's shortest cut is 0.27 s)
            median_shot_s=[0.9, 3.0],   # WARN outside this range (reference: median 1.47 s, mean 2.19 s)
            frame_step=2,               # drawings held 2 frames unless a shot says otherwise
            max_flashes_per_s=3,        # flash / whiteout photosensitivity
        ),
        # the reference page: cream #FFFDF9, picture y 131-949 of 1080 (2.35:1); `mode: full` = full bleed
        frame=dict(mode="band", color=[255, 253, 249], top=131, bottom=949),
        # lyric line in the cream under the picture (promo/lyrics.py DEFAULT_STYLE): Mincho ~34 px, tracked 0.32 em, slate
        lyrics=dict(layout="band", size=34, color=[44, 58, 74], tracking=0.32, y=1012, anim="fade", fade_s=0.12),
        # picture-only look: clean and clear like the reference's flat cel (generated plates already carry haze, so no shadow lift),
        # a breath of bloom on the highlights and fine paper grain; no vignette
        look=dict(grade=dict(on=True, lift=[0.0, 0.0, 0.0], gamma=[1.04, 1.03, 1.02], gain=[1.0, 1.0, 1.0], shadows=[0.0, 0.0, 0.006],
                             highlights=[0.008, 0.004, 0.0], split=1.0, saturation=1.04),
                  bloom=dict(on=True, threshold=0.80, radius=0.012, strength=0.18, tint=[1.0, 0.98, 0.95]),
                  vignette=False, grain=dict(on=True, amount=0.012, size=1.0, seed=11)),
        # the look bible every plate prompt starts with (`promo mv plan`); a project writes its own under `look_bible:`
        guard="illustrated",
        caption=dict(cx=960, cy=1012, size=34, max_w=1600, zone=dict(x0=96, x1=1824, y0=960, y1=1060)),   # engine contract; lyrics have their own gates
        typography=dict(font="/System/Library/Fonts/ヒラギノ明朝 ProN.ttc"),
        transitions=dict(allowed=["cut", "whiteout", "flash", "ink", "iris", "smear", "rgb"]),
        checks=["mv-shots", "mv-cuts", "mv-hold", "mv-median", "mv-flashes", "mv-plates", "look-bible", "lyrics", "test-audio"],
        qa=dict(min_caption_hold=0.8, beat_subdivision=2),
    ),
}


# Version 2 overlays. Merged on top of the locked v1 preset; they do not change PRESETS itself.
# Targets: docs/PRODUCT-DEFAULTS.md (reference study). checks_add is appended, not a style key.
PRESETS_V2 = {
    "hero": dict(
        pacing=dict(
            snap="phrase",
            sync="phrase",
            strict_beat=False,
            cut_rate=dict(overall=[0.35, 0.45], montage=[0.6, 0.8], montage_window=[0.70, 0.87]),
            promise_by_s=0.5,
            logo_after_s=8.0,
            hero_word_frac=[0.08, 0.15],
            card_hold_s=[2.0, 3.0],
            max_captions=5,
            end_card_min_s=6.0,
            planned_hold=dict(min_s=7.0, max_s=12.0, max_count=1),
        ),
        checks_add=["cut-rate", "planned-hold", "phrase-sync", "hero-open"],
    ),
    "anime-opening": dict(
        pacing=dict(
            sync="phrase",          # bar snap (v1) stays the mechanical grid; phrase sync is the extra WARN
            cut_rate=dict(early=0.3, peak=1.0, peak_window=[0.45, 0.67], tol=0.35),
            median_shot_s=[1.2, 1.5],
            loudness_lufs=-14.0,
            planned_hold=dict(min_s=7.0, max_s=12.0, max_count=1),
        ),
        checks_add=["cut-rate", "planned-hold", "phrase-sync"],
    ),
    "livestream": dict(
        pacing=dict(
            snap="phrase",
            sync="phrase",
            strict_beat=False,
            layout_every_s=[5.0, 7.0],
            speaker_turn_max_s=12.0,
            wpm=[165, 180],
            jokes_per_100s=[4, 5],
            bit_by_s=15.0,
            caption_height_frac=[0.03, 0.04],
            caption_hold_s=[2.0, 4.5],
            demo_cue_s=1.0,
            planned_hold=dict(min_s=7.0, max_s=12.0, max_count=1),
        ),
        checks_add=["talk-pace", "planned-hold", "phrase-sync"],
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


def split_preset(name):
    """('hero', None) or ('hero', 2) from `hero` / `hero@2`. The version in the name is optional."""
    if not name or "@" not in str(name):
        return name, None
    base, ver = str(name).rsplit("@", 1)
    if not ver.isdigit() or int(ver) < 1:
        raise StyleError(f"bad preset version in {name!r}; use {base}@1 or {base}@2")
    return base, int(ver)


def _versioned(base, ver):
    """Locked v1 dict, or v1 deep-merged with the @2 overlay. `checks_add` is appended to v1 checks."""
    if ver == 1:
        out = copy.deepcopy(PRESETS[base])
        out["version"] = 1
        return out
    if ver != 2 or base not in PRESETS_V2:
        have = "1 and 2" if base in PRESETS_V2 else "1"
        raise StyleError(f"unknown preset version {ver} for {base}; have {have}")
    extra = PRESETS_V2[base]
    out = deep_merge(PRESETS[base], {k: v for k, v in extra.items() if k != "checks_add"})
    checks = list(PRESETS[base]["checks"])
    for c in extra.get("checks_add") or []:
        if c not in checks:
            checks.append(c)
    out["checks"] = checks
    out["version"] = 2
    return out


def resolve(raw):
    """Resolved style dict for a raw spec: preset defaults deep-merged with the spec's `style:` block.
    No `style.preset` = legacy behaviour (hero defaults, nothing injected).
    `preset: hero` is version 1 (locked). `preset: hero@2` or `version: 2` opts into the reference-study pacing."""
    st = (raw or {}).get("style") or {}
    name = st.get("preset")
    if not name:
        return dict(st, preset=None)
    base, tagged = split_preset(name)
    if base not in PRESETS:
        raise StyleError(f"unknown style preset {base!r}; have {names()}")
    ver = st.get("version", tagged)
    if ver is None:
        ver = 1
    try:
        ver = int(ver)
    except (TypeError, ValueError):
        raise StyleError(f"style.version must be 1 or 2, not {ver!r}")
    preset = _versioned(base, ver)
    over = {k: v for k, v in st.items() if k not in ("preset", "version")}
    res = deep_merge(preset, over)
    res["preset"] = base
    res["version"] = ver
    if isinstance(res.get("band"), dict):
        res["band"] = layout_band(res["band"])
    return res


def layout_band(band, H=1080):
    """Absolute band geometry (y0, y1, rows' cx / cy / size in 1920x1080 canvas units) from the relative band parameters.
    y0 = H * (1 - frac) unless given; y1 = H - pad unless given; a row's rel_cy / rel_cx / rel_size place it inside the
    band (explicit cy / cx / size win). Idempotent."""
    b = copy.deepcopy(band)
    if b.get("y0") is None:
        b["y0"] = int(round(H * (1.0 - float(b.get("frac", 0.15)))))
    if b.get("y1") is None:
        b["y1"] = H - int(b.get("pad", 4))
    bh = H - b["y0"]
    for r in (b.get("rows") or {}).values():
        if r.get("cy") is None and r.get("rel_cy") is not None:
            r["cy"] = round(b["y0"] + float(r["rel_cy"]) * bh, 1)
        if r.get("size") is None and r.get("rel_size") is not None:
            r["size"] = int(round(float(r["rel_size"]) * bh))
        if r.get("cx") is None and r.get("rel_cx") is not None:
            r["cx"] = round(b["x0"] + float(r["rel_cx"]) * (b["x1"] - b["x0"]), 1)
    return b


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
