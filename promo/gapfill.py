"""Fill a thin prompt into a project file (docs/PRODUCT-DEFAULTS.md).

`promo plan <name> --prompt "..."` scaffolds when needed and writes every fill under `plan:` in promo.yaml
so a person can see it and edit it. It does not invent product claims, counts, testimonials, URLs or UI.
Commission-ai spine lines in the defaults doc are examples, not copy this module will insert.
"""
from __future__ import annotations

import os
import re
import shutil

import yaml

from . import pacing as P
from . import reviewgate as RG
from . import styles as STY

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BEGIN = "# promo:plan BEGIN (written by `promo plan`; edit these fills; defaults: docs/PRODUCT-DEFAULTS.md)\n"
END = "# promo:plan END\n"
SHOT_COLUMNS = ("beat", "on_screen", "notice", "caption", "seconds", "app_state")
SCAFFOLD_TITLES = ("My promo", "My promo (anime opening)", "My livestream cut")

_PREFIX = re.compile(
    r"^(?:please\s+)?(?:make|create|build|write|produce)\s+(?:me\s+|us\s+)?"
    r"(?:a\s+|an\s+|the\s+)?(?:short\s+|simple\s+|quick\s+)?"
    r"(?:promo|video|reel|hero|film|ad)?\s*(?:for|about|of)?\s*",
    re.I,
)
_ANIME = ("anime-opening", "anime opening", "kinetic", "anime")
_LIVE = ("livestream", "live-stream", "live stream", "talk show", "talk-show", "talkshow", "chyron")
_VERT = ("vertical-short", "vertical short")
_SCAFFOLD_CAPTION = re.compile(
    r"(?m)^  caption: \{cx: 960, cy: 905, size: 32, max_w: 608, zone: \{x0: 656, x1: 1264, y0: 860, y1: 950\}\}.*\n"
)


def one_idea(prompt):
    """(sentence ≤10 words, source prompt|default, trimmed). The sentence is the prompt's own words, or one generic line."""
    m = re.search(r"(?im)^[ \t]*idea\s*:\s*(.+?)\s*$", prompt)
    text = m.group(1).strip().strip("\"'") if m else None
    source = "prompt"
    if text is None:
        quoted = re.search(r"[\"“]([^\"”]{1,120})[\"”]", prompt)
        if quoted and len(quoted.group(1).split()) <= 10:
            text = quoted.group(1).strip()
        else:
            stripped = _PREFIX.sub("", prompt.strip()).strip(" .")
            text = stripped
            source = "prompt"
    words = (text or "").split()
    if not words:
        return "Show the product doing one job", "default", False
    trimmed = len(words) > 10
    if trimmed:
        source = "prompt"
    return " ".join(words[:10]), source, trimmed


def pick_preset(prompt):
    """(hero|anime-opening|livestream|vertical-short, prompt|default). First explicit keyword wins; otherwise hero."""
    m = re.search(
        r"(?i)\b(?:preset|style|format)\s*:\s*(vertical-short(?:@1)?|hero|anime-opening|livestream)\b",
        prompt,
    )
    if m:
        return m.group(1).lower().split("@", 1)[0], "prompt"
    low = prompt.lower()
    hits = []
    for name, keys in (("vertical-short", _VERT), ("anime-opening", _ANIME), ("livestream", _LIVE)):
        for key in keys:
            i = low.find(key)
            if i >= 0:
                hits.append((i, name))
                break
    if not hits:
        return "hero", "default"
    hits.sort()
    return hits[0][1], "prompt"


def _labelled_beats(prompt):
    keys = {"hook": "hook", "problem": "problem", "demo": "demo", "payoff": "payoff", "cta": "cta", "ask": "cta",
            "call to action": "cta"}
    found = {}
    for m in re.finditer(r"(?im)^[ \t]*(hook|problem|demo|payoff|cta|ask|call to action)\s*:\s*(.*)$", prompt):
        found[keys[m.group(1).lower()]] = m.group(2).strip()
    return found


def fill_beats(prompt, idea):
    """Five lines. A labelled empty line stays empty so `--final` can refuse it. Unlabelled lines get a non-claim default."""
    labelled = _labelled_beats(prompt)
    defaults = {
        "hook": idea,
        "problem": "The viewer already feels this",
        "demo": "Show the product doing that job",
        "payoff": idea,
        "cta": "Name the product",
    }
    beats, sources = {}, {}
    for key, default in defaults.items():
        if key in labelled:
            beats[key] = labelled[key]
            sources[key] = "prompt"
        else:
            beats[key] = default
            sources[key] = "default"
    return beats, sources


def master_seconds(prompt):
    m = re.search(r"(?i)\b(\d{1,3})\s*(?:s|sec|secs|second|seconds)\b", prompt)
    if m:
        return int(m.group(1)), "prompt"
    return 60, "default"


def _caption(text, n=35):
    text = " ".join(str(text).split())
    if len(text) <= n:
        return text
    return text[: n - 1].rstrip() + "…"


def _filled_shot_beats(beats):
    """Shot-list beat names whose line is non-empty. `ask` is the cta line."""
    key = {"hook": "hook", "problem": "problem", "demo": "demo", "payoff": "payoff", "ask": "cta"}
    return {beat for beat, src in key.items() if str((beats or {}).get(src) or "").strip()}


def _rows_from_specs(specs, beats, idea):
    """Six-column rows. Specs are (beat, seconds) in order. No invented UI or product claims."""
    copy = {
        "hook": ("The promise, before any logo", idea, "Clean demo. Cursor hidden. No logo yet."),
        "problem": ("The viewer's situation, then the first real UI", "The pain, not a feature list",
                    "Clean demo. Fixed window. No debug chrome."),
        "demo": ("Real footage of the product doing the job", "The one action that proves the idea",
                 "Clean demo. Cursor only if the click is the point. One push-in on the notice."),
        "payoff": ("The result after the job is done", idea, "Clean demo. Cursor hidden."),
        "ask": ("End card. Product name only until a real destination exists.",
                "One verb and one real destination, or the product name", "End card. No invented URL."),
    }
    line = {"hook": beats.get("hook"), "problem": beats.get("problem"), "demo": beats.get("demo"),
            "payoff": beats.get("payoff"), "ask": beats.get("cta")}
    per_beat = {}
    for beat, _seconds in specs:
        per_beat[beat] = per_beat.get(beat, 0) + 1
    seen = {}
    rows = []
    for beat, seconds in specs:
        seen[beat] = seen.get(beat, 0) + 1
        n = per_beat[beat]
        on_screen, notice, app_state = copy[beat]
        if n > 1:
            on_screen = f"{on_screen} (cut {seen[beat]} of {n})"
        rows.append(dict(
            beat=beat,
            on_screen=on_screen,
            notice=notice,
            caption=_caption(line.get(beat) or notice),
            seconds=round(float(seconds), 2),
            app_state=app_state,
        ))
    return rows


def shot_rows(beats, idea, master, preset, pace):
    """(skeleton, expanded). Skeleton is one six-column row per beat. Expanded splits filled beats
    toward the preset @2 cut-rate cap. Empty labelled beats stay a single row."""
    skeleton, expanded = P.plan_shots(preset, master, pace, _filled_shot_beats(beats))
    return _rows_from_specs(skeleton, beats, idea), _rows_from_specs(expanded, beats, idea)


def _shell_id(text):
    key = re.sub(r"[\s/]+", "-", text.strip().lower())
    return {"ui-zoom": "ui-zoom", "craft-loop": "craft-loop", "before-after": "before-after"}.get(key, "ui-zoom")


def _vertical_catalog():
    preset = STY.PRESETS["vertical-short"]
    return {s["id"]: s for s in preset["shells"]}, list(preset["parked"]), preset


def pick_shell(prompt):
    """(shell id, prompt|default, parked labels mentioned). Quote card and talking head stay parked."""
    low = prompt.lower()
    _shells, parked_names, _preset = _vertical_catalog()
    parked = [name for name in parked_names if name in low or name.replace(" ", "-") in low]
    m = re.search(
        r"(?i)\b(?:shell|template)\s*:\s*(ui-zoom|ui zoom|craft-loop|craft loop|before-after|before/after|before after)\b",
        prompt,
    )
    if m:
        return _shell_id(m.group(1)), "prompt", parked
    hits = []
    for sid, keys in (
        ("before-after", ("before/after", "before-after", "before after")),
        ("craft-loop", ("craft loop", "craft-loop")),
        ("ui-zoom", ("ui zoom", "ui-zoom")),
    ):
        for key in keys:
            i = low.find(key)
            if i >= 0:
                hits.append((i, sid))
                break
    if not hits:
        return "ui-zoom", "default", parked
    hits.sort()
    return hits[0][1], "prompt", parked


def _vertical_seconds(prompt, shell):
    """(seconds, source, clamped_from or None) inside that shell's band."""
    lo, hi = (int(x) for x in shell["length_s"])
    default = int(shell["default_s"])
    m = re.search(r"(?i)\b(\d{1,3})\s*(?:s|sec|secs|second|seconds)\b", prompt)
    if not m:
        return default, "default", None
    n = int(m.group(1))
    if lo <= n <= hi:
        return n, "prompt", None
    return (hi if n > hi else lo), "preset", n


def _shell_rows(shell_id, idea, master):
    """Format-shell rows only. One caption (the idea). No logo shot. No product claims."""
    line = _caption(idea)
    if shell_id == "before-after":
        a, b = P._round_parts([float(master) / 2.0, float(master) / 2.0], master)
        return [
            dict(beat="hook", on_screen="The same UI, before the one craft change.", notice="The control as it is",
                 caption=line, seconds=a,
                 app_state="Real UI, or a diagram of that same UI. No logo. Never paint out UI."),
            dict(beat="payoff", on_screen="The same UI, after one craft change.", notice="The one change",
                 caption=line, seconds=b,
                 app_state="Same UI, one change. A diagram is allowed. No logo. Never paint out UI."),
        ]
    if shell_id == "craft-loop":
        return [dict(
            beat="demo",
            on_screen="One interaction, looped. UI detail, or licensed generative motion.",
            notice="The one interaction. Not a product tour.",
            caption=line, seconds=round(float(master), 2),
            app_state="Captions only. Generative motion only when licensed and on-brief. Never paint out real UI. No logo.",
        )]
    return [dict(
        beat="demo",
        on_screen="Real screen capture. One deliberate zoom on one control.",
        notice="That one control",
        caption=line, seconds=round(float(master), 2),
        app_state="Clean demo. One zoom. Cursor only if the click is the point. Captions only. No logo. Never paint out UI.",
    )]


def _vertical_plan(prompt, preset, preset_source):
    """Format shell for vertical-short@1. Not the 60 s hero expansion, and not a content batch."""
    idea, idea_source, trimmed = one_idea(prompt)
    beats, beat_sources = fill_beats(prompt, idea)
    shells, parked_names, src = _vertical_catalog()
    shell_id, shell_source, parked_hit = pick_shell(prompt)
    shell = shells[shell_id]
    master, master_source, clamped_from = _vertical_seconds(prompt, shell)
    lo, hi = (int(x) for x in shell["length_s"])
    outer = src["pacing"]["length_s"]
    rows = _shell_rows(shell_id, idea, master)
    taste = dict(src["taste"])
    length = dict(
        master_s=master,
        master_source=master_source,
        min_s=int(outer[0]),
        max_s=int(outer[1]),
        shell_min_s=lo,
        shell_max_s=hi,
        aspect="9:16",
        frame=[1080, 1920],
        feed_s=master,
        feature_s=master,
        cuts=[],
        note=("Format shell only. The outer loop is %g–%gs; this %s shell is %d–%ds. "
              "Not a 60s hero, and not a 20s feed cut." % (float(outer[0]), float(outer[1]), shell["label"], lo, hi)),
    )
    if clamped_from is not None:
        length["clamped_from_s"] = clamped_from
        length["note"] += " The prompt asked for %ds; this shell allows %d–%ds, so the plan uses %ds." % (
            clamped_from, lo, hi, master)
    return dict(
        prompt=prompt.strip(),
        idea=idea,
        idea_source=idea_source,
        idea_trimmed=bool(trimmed),
        preset=preset,
        preset_version=1,
        preset_source=preset_source,
        beats=beats,
        beat_sources=beat_sources,
        shell=dict(id=shell_id, rank=shell["rank"], label=shell["label"], source=shell_source),
        shells=dict(
            primary="ui-zoom",
            selected=shell_id,
            options=list(src["shells"]),
            parked=parked_names,
            parked_request=parked_hit,
            note="Format shells only. No content batch. Quote card and talking head are parked.",
        ),
        taste=taste,
        length=length,
        hook=dict(
            promise_by_s=0.5,
            logo_after_s=round(max(0.0, float(master) - 1.0), 2),
            logo_last_s=1,
            logo="omit",
            sound_off=True,
            captions_only=True,
            open_on="One caption carries the idea with the sound off. No logo, or a wordmark in the last second at most.",
        ),
        capture=dict(
            dpr=2,
            deliverable=1080,
            aspect="9:16",
            frame=[1080, 1920],
            capture_resolution="2160x3840",
            demo_state="?demo=promo",
            demo_note="Example clean state. Confirm the product's real demo mode before capture.",
            cursor="only when the click is the point; pause before the click; no circling",
            zoom="one deliberate zoom on one control",
            never_paint_ui=True,
            paint_note="Never paint out UI. Reshoot from a clean moment.",
            sound="captions-only",
        ),
        shot_list_skeleton=rows,
        shot_list=rows,
        shot_list_cap=len(rows),
        shot_list_note=(
            "Format shell for %s (%s): %d row(s), %gs, one caption, no logo shot. "
            "The five beat lines stay in beats. This is not the 60s hero expansion. "
            "Content templates are not filled in."
            % (shell["label"], shell_id, len(rows), master)
        ),
        review=dict(required=True, max_rounds=RG.MAX_ROUNDS, roles=list(RG.ROLES)),
        filled=["idea", "preset", "beats", "length", "shot_list", "capture", "hook", "shell", "taste"],
        defaults="docs/PRODUCT-DEFAULTS.md",
    )


def pace_of(preset):
    try:
        return STY.resolve({"style": {"preset": preset, "version": 2}}).get("pacing") or {}
    except STY.StyleError:
        return STY.PRESETS.get(preset, STY.PRESETS["hero"]).get("pacing") or {}


def build_plan(prompt, preset, preset_source):
    if preset == "vertical-short":
        return _vertical_plan(prompt, preset, preset_source)
    idea, idea_source, trimmed = one_idea(prompt)
    beats, beat_sources = fill_beats(prompt, idea)
    master, master_source = master_seconds(prompt)
    pace = pace_of(preset)
    cap = P.max_shots(preset, master, pace)
    skeleton, rows = shot_rows(beats, idea, master, preset, pace)
    rows = P.cap_rows(rows, cap)
    return dict(
        prompt=prompt.strip(),
        idea=idea,
        idea_source=idea_source,
        idea_trimmed=bool(trimmed),
        preset=preset,
        preset_version=2,
        preset_source=preset_source,
        beats=beats,
        beat_sources=beat_sources,
        length=dict(
            master_s=master,
            master_source=master_source,
            feed_s=20,
            feature_s=30,
            cuts=[
                dict(id="feed", seconds=20, beats=["hook", "demo", "payoff", "ask"], note="X / Shorts / feed"),
                dict(id="feature", seconds=30, beats=["hook", "problem", "demo", "payoff", "ask"], note="single-feature clip"),
            ],
        ),
        hook=dict(
            promise_by_s=0.5,
            logo_after_s=8,
            open_on="Open on the payoff evidence, not a brand label. Match the title and the thumbnail.",
        ),
        capture=dict(
            dpr=2,
            deliverable=1080,
            capture_resolution="3840x2160",
            demo_state="?demo=promo",
            demo_note="Example clean state. Confirm the product's real demo mode before capture.",
            cursor="only when the click is the point; pause before the click; no circling",
            zoom="one push-in per shot, landed on the notice target",
            never_paint_ui=True,
            paint_note="Never paint out UI. Reshoot from a clean moment.",
        ),
        shot_list_skeleton=skeleton,
        shot_list=rows,
        shot_list_cap=cap,
        shot_list_note=(f"shot_list_skeleton is the five beat rows. shot_list expands that skeleton to {len(rows)} shots "
                        f"toward the {preset} @2 cut-rate cap of {cap} before capture (master {master}s), "
                        "stopping at the preset's shot-length band. Empty labelled beats stay one row. "
                        "Also plan the ~20s feed (hook, demo, payoff, ask) and the ~30s feature before capture."),
        review=dict(required=True, max_rounds=RG.MAX_ROUNDS, roles=list(RG.ROLES)),
        filled=["idea", "preset", "beats", "length", "shot_list", "capture", "hook"],
        defaults="docs/PRODUCT-DEFAULTS.md",
    )


def _style_span(lines):
    start = next(i for i, ln in enumerate(lines) if re.match(r"^style:\s*", ln))
    end = start + 1
    while end < len(lines):
        ln = lines[end]
        if ln.strip() and not ln.startswith((" ", "\t", "#")):
            break
        end += 1
    return start, end


def existing_preset(text):
    m = re.search(r"(?m)^\s*preset:\s*([A-Za-z0-9@-]+)", text)
    if not m:
        return None
    base, _ver = STY.split_preset(m.group(1))
    return base


def _style_has_version(block):
    return re.search(r"(?m)^\s*version:\s*\d+", block) is not None


def ensure_style(text, preset, version=2):
    """Set style.preset when missing, and style.version when the block has no version yet. A written version: 1 stays."""
    if not re.search(r"(?m)^style:\s*", text):
        return f"style:\n  preset: {preset}\n  version: {version}\n\n{text}"
    lines = text.splitlines(keepends=True)
    start, end = _style_span(lines)
    block = "".join(lines[start:end])
    if _style_has_version(block):
        return text
    if re.match(r"^style:\s*\{", lines[start]):
        line = lines[start]
        if "preset" not in line:
            line = line.replace("{", "{preset: %s, version: %d, " % (preset, version), 1)
        else:
            line = line.replace("{", "{version: %d, " % version, 1)
        lines[start] = line
        return "".join(lines)
    if re.search(r"(?m)^\s*preset:", block):
        for i in range(start, end):
            if re.match(r"\s*preset:", lines[i]):
                lines.insert(i + 1, f"  version: {version}\n")
                break
    else:
        lines.insert(start + 1, f"  preset: {preset}\n  version: {version}\n")
    return "".join(lines)


def write_plan_block(text, plan):
    body = yaml.safe_dump({"plan": plan}, sort_keys=False, allow_unicode=True, width=100)
    block = BEGIN + body + END
    if "# promo:plan BEGIN" in text:
        return re.sub(r"# promo:plan BEGIN.*?# promo:plan END\n?", block, text, count=1, flags=re.S)
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n" + block


def _maybe_title(text, idea):
    def repl(m):
        if m.group(3) not in SCAFFOLD_TITLES:
            return m.group(0)
        return m.group(1) + m.group(2) + idea.replace('"', "'") + m.group(2)
    return re.sub(r'(title:\s*)(["\'])(.*?)\2', repl, text, count=1)


def scaffold(dest, name, preset):
    src = os.path.join(ROOT, "templates", "new-project")
    if not os.path.isdir(src):
        raise SystemExit(f"template not found: {src}")
    os.makedirs(dest, exist_ok=True)
    shutil.copytree(src, dest, dirs_exist_ok=True)
    sdir = os.path.join(ROOT, "templates", "styles", preset)
    if os.path.isdir(sdir):
        shutil.copytree(sdir, dest, dirs_exist_ok=True)
    for rel in ("promo.yaml", "assets.yaml", "footage/manifest.yaml", "footage/manifest.md"):
        p = os.path.join(dest, rel)
        if os.path.isfile(p):
            t = open(p).read().replace("my-promo", name)
            open(p, "w").write(t)
    for d in ("media/music", "media/models"):
        os.makedirs(os.path.join(dest, d), exist_ok=True)


def drop_scaffold_caption(text):
    """Drop the 16:9 scaffold caption so a vertical-short preset's 9:16 zone is the one that applies."""
    return _SCAFFOLD_CAPTION.sub("", text, count=1)


def summary(plan, path):
    beats = " | ".join(f"{k}: {plan['beats'][k]}" for k in ("hook", "problem", "demo", "payoff", "cta"))
    if plan.get("preset") == "vertical-short":
        length = plan["length"]
        length_line = (
            f"  length: {length['master_s']}s {plan['shell']['label']} "
            f"(shell {length['shell_min_s']:g}–{length['shell_max_s']:g}s, "
            f"loop {length['min_s']:g}–{length['max_s']:g}s), "
            f"{length['aspect']} {length['frame'][0]}x{length['frame'][1]}\n"
        )
        hook_line = (
            f"  hook: captions only, promise by {plan['hook']['promise_by_s']}s, "
            f"logo {plan['hook']['logo']} (last {plan['hook']['logo_last_s']:g}s max)\n"
        )
    else:
        length_line = (
            f"  length: {plan['length']['master_s']}s master, feed {plan['length']['feed_s']}s, "
            f"feature {plan['length']['feature_s']}s\n"
        )
        hook_line = f"  hook: promise by {plan['hook']['promise_by_s']}s, logo after {plan['hook']['logo_after_s']}s\n"
    return (
        f"filled {path}\n"
        f"  idea ({len(plan['idea'].split())} words, {plan['idea_source']}): {plan['idea']}\n"
        f"  preset: {plan['preset']} @{plan['preset_version']} ({plan['preset_source']})\n"
        f"  beats: {beats}\n"
        f"{length_line}"
        f"  shot list: {len(plan['shot_list'])} rows from a {len(plan['shot_list_skeleton'])}-row skeleton "
        f"(cap {plan['shot_list_cap']}), six columns\n"
        f"  capture: {plan['capture']['capture_resolution']} (dpr {plan['capture']['dpr']}), never_paint_ui {plan['capture']['never_paint_ui']}\n"
        f"{hook_line}"
        f"  next: edit plan: in that file. `promo preview` is 540p + stills. "
        f"`promo build --final` needs every beat and reviews/round-N.md signed by Marketing, Zen and Director.\n"
        f"  defaults: docs/PRODUCT-DEFAULTS.md"
    )


def apply(dest, prompt, name=None):
    """Scaffold `dest` if it has no promo.yaml, then write the fills. Returns {path, plan, summary}."""
    dest = os.path.abspath(dest)
    path = os.path.join(dest, "promo.yaml")
    picked, preset_source = pick_preset(prompt)
    if not os.path.isfile(path):
        scaffold(dest, name or os.path.basename(dest.rstrip(os.sep)) or "promo", picked)
    text = open(path).read()
    have = existing_preset(text)
    preset = have or picked
    if have and have != picked:
        preset_source = "file"
    elif have:
        preset_source = preset_source if preset_source == "prompt" else "file"
    text = ensure_style(text, preset, 1 if preset == "vertical-short" else 2)
    if preset == "vertical-short":
        text = drop_scaffold_caption(text)
    plan = build_plan(prompt, preset, preset_source)
    # a locked `version: 1` on a preset that has @2 was left in place; say so on the plan the human edits.
    # vertical-short@1 is the only version, so that note does not apply.
    if preset != "vertical-short" and re.search(r"(?m)^\s*version:\s*1\s*(?:#.*)?$", text):
        plan["preset_version"] = 1
        plan["preset_note"] = "style.version: 1 is locked in this file. Delete that line and re-run promo plan to opt into @2 pacing."
    text = _maybe_title(text, plan["idea"])
    text = write_plan_block(text, plan)
    with open(path, "w") as f:
        f.write(text)
    RG.ensure_round(dest, 1)
    return dict(path=path, plan=plan, summary=summary(plan, path))
