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


_BRIEF_SENTENCE = re.compile(r"^(?:\d{1,3}\s*(?:s|sec|secs|seconds?)\s+)?(?:promo|video|reel|trailer|film|ad)\b.*\b(?:for|about|of)\b", re.I)


def _skip_brief(prompt):
    """Drop a leading sentence that only briefs the job ("60s promo for my app.") when the prompt goes on to say something."""
    parts = re.split(r"(?<=[.!?])\s+", prompt.strip(), maxsplit=1)
    if len(parts) == 2 and parts[1].strip() and _BRIEF_SENTENCE.match(parts[0].strip()):
        return parts[1].strip()
    return prompt


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
            stripped = _PREFIX.sub("", _skip_brief(prompt.strip())).strip(" .")
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
    """(hero|anime-opening|livestream, prompt|default). First explicit keyword wins; otherwise hero."""
    m = re.search(r"(?i)\b(?:preset|style|format)\s*:\s*(hero|anime-opening|livestream)\b", prompt)
    if m:
        return m.group(1), "prompt"
    low = prompt.lower()
    hits = []
    for name, keys in (("anime-opening", _ANIME), ("livestream", _LIVE)):
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


def pace_of(preset):
    try:
        return STY.resolve({"style": {"preset": preset, "version": 2}}).get("pacing") or {}
    except STY.StyleError:
        return STY.PRESETS.get(preset, STY.PRESETS["hero"]).get("pacing") or {}


def build_plan(prompt, preset, preset_source):
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


def designed_summary(plan):
    d = plan.get("designed")
    if not d:
        return ""
    fr = d["framing_hierarchy"]["counts"]
    ready = sum(1 for c in d["kinetic_cards"] if c["status"] == "ready")
    lines = [f"\n  designed ({d['trigger']}): {len(d['shots'])} shots, framing "
             + ", ".join(f"{k} {v}" for k, v in fr.items() if v)
             + f"; {ready}/{len(d['kinetic_cards'])} kinetic cards have your words; {len(d['plates'])} plates to generate; "
             f"{len(d['stills'])} stills; band {d['length_band']['class']}"]
    for n in d["needs"]:
        lines.append(f"    needs {n['kind']}: {n['why']}")
    q = plan.get("cospec", {}).get("open") or []
    if q:
        lines.append(f"  co-spec ({len(q)} of max {plan['cospec']['max_questions']}, optional): " + " | ".join(x["key"] for x in q)
                     + "  -> promo cospec")
    lines.append("  next: promo designed apply -p promo.yaml writes the cinema shots; then promo preview")
    return "\n".join(lines)


def summary(plan, path):
    beats = " | ".join(f"{k}: {plan['beats'][k]}" for k in ("hook", "problem", "demo", "payoff", "cta"))
    return (
        f"filled {path}\n"
        f"  idea ({len(plan['idea'].split())} words, {plan['idea_source']}): {plan['idea']}\n"
        f"  preset: {plan['preset']} @{plan['preset_version']} ({plan['preset_source']})\n"
        f"  beats: {beats}\n"
        f"  length: {plan['length']['master_s']}s master, feed {plan['length']['feed_s']}s, feature {plan['length']['feature_s']}s\n"
        f"  shot list: {len(plan['shot_list'])} rows from a {len(plan['shot_list_skeleton'])}-row skeleton "
        f"(cap {plan['shot_list_cap']}), six columns\n"
        f"  capture: {plan['capture']['capture_resolution']} (dpr {plan['capture']['dpr']}), never_paint_ui {plan['capture']['never_paint_ui']}\n"
        f"  hook: promise by {plan['hook']['promise_by_s']}s, logo after {plan['hook']['logo_after_s']}s\n"
        f"  next: edit plan: in that file. `promo preview` is 540p + stills. "
        f"`promo build --final` needs every beat and reviews/round-N.md signed by Marketing, Zen and Director.\n"
        f"  defaults: docs/PRODUCT-DEFAULTS.md"
        + designed_summary(plan)
    )


def existing_plan(text):
    m = re.search(r"# promo:plan BEGIN[^\n]*\n(.*?)# promo:plan END", text, re.S)
    if not m:
        return {}
    try:
        return (yaml.safe_load(m.group(1)) or {}).get("plan") or {}
    except yaml.YAMLError:
        return {}


DESIGNED_BEGIN = "# promo:designed BEGIN (broll plates written by `promo plan`; generate with `promo gen plan`)\n"
DESIGNED_END = "# promo:designed END\n"


def write_designed_block(text, broll):
    """The plates as a top-level `broll:` between markers. A `broll:` the person wrote themselves is left alone."""
    body = yaml.safe_dump({"broll": broll}, sort_keys=False, allow_unicode=True, width=100) if broll else ""
    block = DESIGNED_BEGIN + body + DESIGNED_END if broll else ""
    if "# promo:designed BEGIN" in text:
        return re.sub(r"# promo:designed BEGIN.*?# promo:designed END\n?", block, text, count=1, flags=re.S)
    if not broll:
        return text
    if re.search(r"(?m)^broll:", text):
        return text
    if not text.endswith("\n"):
        text += "\n"
    return text + "\n" + block


def apply(dest, prompt, name=None, stills=None, designed=None, answers=None):
    """Scaffold `dest` if it has no promo.yaml, then write the fills. Returns {path, plan, summary}.

    designed: None = on when the prompt is thin AND stills are supplied (or the file already has a designed plan); True = always;
    False = never. stills / answers carry over from the file's earlier plan when not given again."""
    from . import cospec as CS
    from . import designed as D
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
    text = ensure_style(text, preset, 2)
    plan = build_plan(prompt, preset, preset_source)
    # a locked `version: 1` was left in place; say so on the plan the human edits
    if re.search(r"(?m)^\s*version:\s*1\s*(?:#.*)?$", text):
        plan["preset_version"] = 1
        plan["preset_note"] = "style.version: 1 is locked in this file. Delete that line and re-run promo plan to opt into @2 pacing."
    prev = existing_plan(text)
    prev_des = prev.get("designed") or {}
    if stills is None:
        stills = [x["path"] for x in prev_des.get("stills") or []]
    merged = dict((prev.get("cospec") or {}).get("answers") or {})
    merged.update({k: v for k, v in (answers or {}).items() if v not in (None, "")})
    on = designed if designed is not None else bool(prev_des.get("enabled")) or (D.is_thin(prompt) and bool(stills))
    if on:
        trigger = "flag" if designed else ("kept" if prev_des.get("enabled") and designed is None else "thin+stills")
        des = D.build(prompt, plan, stills, merged, trigger=trigger)
        problems = D.check_no_invention(des, prompt, merged)
        if problems:
            raise SystemExit("designed plan refused (nothing invented is allowed):\n  " + "\n  ".join(problems))
        plan["designed"] = des
        plan["filled"] = plan["filled"] + ["designed"]
    plan["cospec"] = CS.block(prompt, D.scan_stills(stills) if on else [], merged)
    text = _maybe_title(text, plan["idea"])
    text = write_plan_block(text, plan)
    text = write_designed_block(text, D.broll_entries(plan["designed"]) if on else [])
    with open(path, "w") as f:
        f.write(text)
    RG.ensure_round(dest, 1)
    return dict(path=path, plan=plan, summary=summary(plan, path))
