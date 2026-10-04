#!/usr/bin/env python3
"""Generate promo.yaml for the Direction 3 talk show from plan.yaml + the VO's lines.json (exact line durations).

    python projects/commission-ai-talkshow/make_spec.py            # -> projects/commission-ai-talkshow/promo.yaml
    python projects/commission-ai-talkshow/make_spec.py --check    # exit 1 if promo.yaml is stale (VO re-rendered / plan edited)

Timeline: 30 fps, `timeline: {bpm: 1800}` so one timeline beat = one frame and every cut is frame-exact.
Lines inside a beat are 0.20 s apart; each beat's screen cuts
`cut_lead` before its first line, and holds `hold` s after its last line. Beat 7's MAO line is trimmed
automatically if the measured shot-12 text is under `min_px` (see auto_take). Every VO line is sha256-pinned: if the VO director re-renders a line, the
`files` VO engine refuses to build until this script is re-run.
"""
import hashlib
import json
import os
import re
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)
FOOTAGE = "${HERO_FOOTAGE_MANIFEST:-/workspace/promo-reel/projects/commission-ai-hero/footage/manifest.yaml}"


def expand(s):
    return re.sub(r"\$\{(\w+):-([^}]*)\}", lambda m: os.environ.get(m.group(1), m.group(2)), s)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def clip_path(cid):
    """Footage path for a manifest clip id (None if the id is not registered or the file is absent)."""
    mp = expand(FOOTAGE)
    if not os.path.exists(mp):
        return None
    raw = yaml.safe_load(open(mp)) or []
    for c in (raw.get("clips", []) if isinstance(raw, dict) else raw):
        if c.get("id") == cid:
            p = c.get("path")
            if p and not os.path.isabs(p):
                p = os.path.join(os.path.dirname(mp), p)
            return p if p and os.path.exists(p) else None
    return None


def manifest_entry(cid):
    mp = expand(FOOTAGE)
    if not os.path.exists(mp):
        return {}
    raw = yaml.safe_load(open(mp)) or []
    return next((c for c in (raw.get("clips", []) if isinstance(raw, dict) else raw) if c.get("id") == cid), {})


def manifest_md_tod(cid):
    """`time of day: <value>` written for clip `cid` in the footage manifest.md (next to manifest.yaml): on the clip's
    table row or in the paragraph under a heading naming it. Value forms as in tod_change. None if not recorded."""
    mp = os.path.join(os.path.dirname(expand(FOOTAGE)), "manifest.md")
    if not os.path.exists(mp):
        return None
    pat = re.compile(r"time[ _-]of[ _-]day\s*[:=]\s*`?([^|;`\n]+)", re.I)
    cur = None
    for ln in open(mp, encoding="utf-8"):
        if ln.startswith("#"):
            cur = cid if re.search(rf"(?<![\w-]){re.escape(cid)}(?![\w-])", ln) else None
        row = ln.startswith("|") and re.search(rf"^\|\s*{re.escape(cid)}\s*\|", ln)
        if row or cur == cid:
            m = pat.search(ln)
            if m:
                return m.group(1).strip()
    return None


DISSOLVE = 0.4


def tod_change(clip, prof):
    """Time-of-day change inside a take -> (at_src, from, to, origin) or None. Source of truth: the clip's footage
    manifest (`time_of_day` in manifest.yaml, else `time of day: ...` in manifest.md, where Commission-ai records it
    with the take): a plain value
    ("dusk") = constant, no dissolve; "dusk -> day @ 5.50" or {from, to, at} = a change at that clip time. No field ->
    the plan profile's `time_of_day` (same forms) for the current take."""
    v, origin = manifest_entry(clip).get("time_of_day"), "manifest"
    if v is None:
        v, origin = manifest_md_tod(clip), "manifest.md"
    if v is None:
        v, origin = prof.get("time_of_day"), "plan profile"
    if v is None:
        return None
    if isinstance(v, dict):
        return (float(v["at"]), v.get("from"), v.get("to"), origin) if v.get("at") is not None and v.get("from") != v.get("to") else None
    m = re.match(r"\s*(\w+)\s*->\s*(\w+)\s*@\s*([\d.]+)", str(v))
    return (float(m.group(3)), m.group(1), m.group(2), origin) if m and m.group(1) != m.group(2) else None


def script_lines(path):
    """{(beat, n): (HOST, text)} from the Direction 3 table of the marketing script, plus {beat: row text}. Stage
    directions in parentheses after the dialogue (e.g. beat 8's alternatives, "(v2, 4 Oct: ...)" revision notes) are not
    dialogue and are dropped."""
    txt = open(path).read()
    sec = txt[txt.index("## Direction 3"):]
    sec = sec[: sec.index("\n## ", 5)] if "\n## " in sec[5:] else sec
    out, rows = {}, {}
    for row in sec.splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|[^|]*\|[^|]*\|(.*)\|\s*$", row)
        if not m:
            continue
        beat, dlg = int(m.group(1)), m.group(2)
        rows[beat] = dlg
        dlg = re.sub(r"\s*\((?:Pick|pick)[^)]*\)\s*$", "", dlg.strip())
        dlg = re.sub(r"\s*\(v\d+,[^)]*\)\s*$", "", dlg)          # editorial revision note, e.g. "(v2, 4 Oct: ...)"
        parts = re.split(r"\*\*(HIYORI|MAO):\*\*", dlg)
        n = 0
        for host, text in zip(parts[1::2], parts[2::2]):
            n += 1
            out[(beat, n)] = (host, text.strip())
    return out, rows


def load_lines_json(vo_dir, tries=10):
    """lines.json, tolerating a write in progress (the VO director rewrites it as takes land)."""
    import time
    p = os.path.join(vo_dir, "lines.json")
    for i in range(tries):
        try:
            return json.load(open(p))
        except (json.JSONDecodeError, FileNotFoundError):
            if i == tries - 1:
                raise
            time.sleep(1.0)


def locate(vo_dir, rel):
    """Existing locations of a VO file: vo/<name> first (new takes), then vo/superseded/<name> or <stem>.vN.wav."""
    name = os.path.basename(rel)
    stem = os.path.splitext(name)[0]
    sup = os.path.join(os.path.dirname(rel), "superseded")
    cands = [rel, os.path.join(sup, name)]
    if os.path.isdir(os.path.join(vo_dir, sup)):          # versioned old takes: <stem>.v1.wav, newest first
        cands += [os.path.join(sup, f) for f in sorted(os.listdir(os.path.join(vo_dir, sup)), reverse=True)
                  if f.startswith(stem + ".") and f.endswith(".wav")]
    return [c for c in dict.fromkeys(cands) if os.path.exists(os.path.join(vo_dir, c))]


def beat8_variant(plan):
    leg = plan.get("shot11_legible")
    if not leg:
        return "all"
    for k, v in plan["beat8_variants"].items():
        if bool(v["cards"]) == bool(leg.get("cards")) and bool(v["logos"]) == bool(leg.get("logos")):
            return k
    return "all"


def resolve_lines(plan, vo_dir):
    """Script text per line + which WAV voices it. Prefers the new take in vo/; falls back to the old take (vo/ or
    vo/superseded/) as a labelled PLACEHOLDER when the line's re-voiced take has not landed. Durations are read from
    the chosen WAV itself (no time-stretch)."""
    import soundfile as sf
    script, rows = script_lines(expand(plan["script"]))
    lj = load_lines_json(vo_dir)
    out, notes = [], []
    var = beat8_variant(plan)
    for l in sorted(lj["lines"], key=lambda l: (l["beat"], l["line"])):
        key = (l["beat"], l["line"])
        if key not in script:
            raise SystemExit(f"lines.json {l['id']} has no line in the script table")
        host, text = script[key]
        if host != l["host"].upper():
            raise SystemExit(f"{l['id']}: script host {host} != VO host {l['host']}")
        l = dict(l)
        voiced = l["text"]
        if key == (8, 2):                            # MAO's beat 8 line: chosen by the shot 11 legibility selector
            v = plan["beat8_variants"][var]
            if v["text"] not in rows[8]:
                raise SystemExit(f"beat 8 variant {var!r} text not in the script: {v['text']!r}")
            text = v["text"]
            locs = [c for c in locate(vo_dir, v["file"])]
            if locs:
                l["file"], voiced = locs[0], v["text"]
            else:                                    # selected take not there yet: the existing take, labelled
                locs = locate(vo_dir, l["file"]) or locate(vo_dir, plan["beat8_variants"]["full"]["file"])
                l["file"] = locs[0]
                voiced = plan["beat8_variants"]["full"]["text"]
            l["variant"] = var
        else:
            locs = locate(vo_dir, l["file"])
            if not locs:
                raise SystemExit(f"{l['id']}: no WAV in vo/ or vo/superseded/ for {l['file']}")
            if voiced == text and locs[0] == l["file"]:
                pass                                 # the take for the current script text, in place
            else:
                l["file"] = locs[0]                  # newest available take; labelled if its words differ
        info = sf.info(os.path.join(vo_dir, l["file"]))
        l["duration"] = round(info.frames / info.samplerate, 3)
        l["alt_files"] = [c for c in locate(vo_dir, os.path.join("vo", os.path.basename(l["file"]))) if c != l["file"]]
        l["script_text"], l["voiced_text"] = text, voiced
        l["text"] = text
        l["placeholder"] = voiced.strip() != text.strip()
        if l["placeholder"]:
            notes.append(f"{l['id']}: PLACEHOLDER take {l['file']} voices {voiced!r}; script says {text!r}")
        out.append(l)
    return out, notes, var


LS_CFG = {"screen": {"w": 1440}, "margin": 24}   # livestream layout: no chat strip (asides cut, UX review T2/T3)


def screen_wh():
    from promo import livestream as LS
    return LS.screen_size(LS_CFG)              # (1440, 1032): the app screen takes the full height


def auto_take(plan, lines, vo_dir):
    """Segments with `text_check` + `fallback_trim`: measure the key text line through the segment's cam on the
    app screen (SCREEN). Below `min_px` (or footage missing) -> trim that beat's line at the silence after `after`
    (short fade) and voice only that prefix. Mutates `lines`; returns a report per segment."""
    import soundfile as sf

    from promo import livestream as LS
    from promo import vo as VO
    out = []
    for sg in plan["segments"]:
        tc, ft = sg.get("text_check"), sg.get("fallback_trim")
        if not ft:
            continue
        if not tc:                                   # take without a measured text box (e.g. a new retake): trim (safe)
            tc = {"box": [0, 0], "min_px": 24}
        p = clip_path(sg["clip"]) if tc["box"] != [0, 0] else None
        m = LS.text_height(p, float(sg.get("t_in", 0.0)) + 0.05, sg.get("cam", (0.5, 0.5, 1.0)), screen_wh(), tc["box"], tc.get("src_px")) if p else None
        ok = bool(m and m["px"] >= tc.get("min_px", 24) and m["inside"])
        ln = next(l for l in lines if l["beat"] == sg["beat"] and l["line"] == ft["line"])
        x, sr = sf.read(os.path.join(vo_dir, ln["file"]), dtype="float32", always_2d=True)
        cut = VO.cut_after(x.mean(1), sr, ln["text"], ft["after"]) if not ln.get("placeholder") else None
        rep = dict(segment=str(sg["id"]), clip=sg["clip"], measured_px=round(m["px"], 1) if m else None, min_px=tc.get("min_px", 24),
                   line=ln["id"], take="full" if ok else "trimmed", would_cut=cut)
        if not ok:
            if not cut:
                raise SystemExit(f"auto_take: no silence found after {ft['after']!r} in {ln['file']} (or the take is a placeholder)")
            ln["script_text"] = ln["text"]
            ln["text"] = cut["prefix"]
            ln["trim"] = {"end": cut["end"], "fade": cut["fade"]}
            ln["duration"] = cut["end"]
        out.append(rep)
    return out


def resolve_segments(plan):
    """Segments with `take: <role>` -> clip id from `takes` + that clip's `profiles` entry (segment keys win).
    `part: a|b` splits a take across two segments (a: t_in..until_src; b: continues, synced by `sync_b`)."""
    out = []
    for sg in plan["segments"]:
        sg = dict(sg)
        if sg.get("take"):
            clip = plan["takes"][sg["take"]]
            profs = plan.get("profiles") or {}
            prof = dict(profs.get(clip) or profs.get(sg["take"]) or {})   # clip profile, else the role's (one-line take swap)
            part = sg.get("part")
            if part == "b":
                prof = {"continue": True, **({"sync": prof["sync_b"]} if "sync_b" in prof else {}),
                        **{k: prof[k] for k in ("cam", "named") if k in prof}}
            elif part == "a":
                prof = {k: v for k, v in prof.items() if k in ("t_in", "until_src", "cam", "named")}
            prof.pop("sync_b", None)
            if part == "b" and out and "until_src" not in out[-1]:
                prof["from"] = {"line": 2, "plus": -0.15}   # take without a split profile: cut on the second line
            sg = {**prof, **{k: v for k, v in sg.items() if k not in ("take", "part")}, "clip": clip, "take": sg["take"]}
        out.append(sg)
    return out


def build(plan):
    fps = plan["fps"]
    fr = lambda t: int(round(t * fps))
    vo_dir = expand(plan["vo_dir"])
    lines, vo_notes, variant = resolve_lines(plan, vo_dir)
    plan = dict(plan, segments=resolve_segments(plan))
    takes = auto_take(plan, lines, vo_dir)                  # before timing: a trimmed line is shorter
    # ---- line times (global seconds)
    holds = {int(k): float(v) for k, v in (plan.get("holds") or {}).items()}
    hold_of = lambda b: holds.get(b, float(plan["hold"]))
    t = plan["lead_in"]
    prev_beat = None
    starts = {}
    for ln in lines:
        if prev_beat is not None:
            t += hold_of(prev_beat) + plan["cut_lead"] if ln["beat"] != prev_beat else plan["gap_line"]
        starts[(ln["beat"], ln["line"])] = round(t, 3)
        t += ln["duration"]
        prev_beat = ln["beat"]
    speech_end = t
    first = {b: min(v for (bb, _), v in starts.items() if bb == b) for b in {l["beat"] for l in lines}}
    dur_of = {(l["beat"], l["line"]): l["duration"] for l in lines}

    def at_line(beat, n, at):
        s = starts[(beat, n)]
        return s + (dur_of[(beat, n)] if at == "end" else float(at))

    # ---- segment frames
    segs = plan["segments"]
    f0s = []
    for sg in segs:
        frm = sg.get("from", "beat")
        if frm == "start":
            f0s.append(0)
        elif frm == "title_card":
            f0s.append(fr(plan["title_card"]))
        elif isinstance(frm, dict) and "t" in frm:          # absolute show time (e.g. the hook cut: VO carries over)
            f0s.append(fr(float(frm["t"])))
        elif isinstance(frm, dict):
            f0s.append(fr(at_line(sg["beat"], frm["line"], frm.get("plus", 0.0))))
        else:
            f0s.append(fr(first[sg["beat"]] - plan["cut_lead"]))
    end_f = fr(speech_end + hold_of(prev_beat))
    # a segment with `until_src` ends where its clip reaches that time (next segment then starts there)
    for i, sg in enumerate(segs):
        if "until_src" in sg:
            f0s.insert(i + 1, None)
            break
    f0s = [f for f in f0s if f is not None]
    bounds = []
    for i, sg in enumerate(segs):
        a = f0s[i]
        if "until_src" in sg:
            b = a + fr(sg["until_src"] - sg.get("t_in", 0.0))
            f0s[i + 1] = b if i + 1 < len(f0s) else b
        b = f0s[i + 1] if i + 1 < len(f0s) else end_f
        bounds.append([a, b])
    for i in range(len(bounds) - 1):            # until_src may have moved the next start
        bounds[i + 1][0] = bounds[i][1]
    cr = plan["credits"] if isinstance(plan["credits"], list) else [plan["credits"]]   # one card per entry (seconds)
    credits_f = (end_f, end_f + sum(fr(x) for x in cr))
    total_f = credits_f[1]

    shots, clip_t = [], {}
    for sg, (a, b) in zip(segs, bounds):
        s = {"id": str(sg["id"]), "beats": [a, b], "type": "livestream", "beat": sg["beat"]}
        dur = (b - a) / fps
        if sg.get("clip"):
            sc = {"source": sg["clip"]}
            t_in = float(sg.get("t_in", 0.0))
            if sg.get("continue"):
                t_in = clip_t[sg["clip"]]
            hold = 0.0
            if "sync" in sg:
                y = sg["sync"]
                vo_local = at_line(sg["beat"], y["line"], y["at"]) - a / fps
                need = y["src"] - vo_local          # clip time at segment start for the moment to land on cue
                if need >= t_in and not sg.get("continue"):
                    t_in = need
                else:
                    hold = max(0.0, vo_local - (y["src"] - t_in))
            if "end_src" in sg:
                hold = max(hold, dur - (sg["end_src"] - t_in))
            if sg.get("fit_clip") and clip_path(sg["clip"]):  # clip shorter than its segment: play it slower, never freeze
                import subprocess
                src_dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                                         "csv=p=0", clip_path(sg["clip"])], text=True).strip())
                show = dur - hold
                if show > 0 and src_dur - t_in - 0.05 < show:
                    sc["speed"] = round((src_dur - t_in - 0.05) / show, 3)
            sc["t_in"] = round(t_in, 3)
            if hold > 0:
                sc["hold_in"] = round(hold, 3)
            if sg.get("cam"):
                sc["cam"] = sg["cam"]
            if sg.get("matte"):
                sc["matte"] = sg["matte"]          # promo matte over cut UI at the crop edge (logged in the notes)
            tc_ = tod_change(sg["clip"], sg)
            shown = (t_in, t_in + max(0.0, dur - hold))
            if tc_ and shown[0] < tc_[0] < shown[1]:            # dissolve over the snap, only if this segment shows it
                sc["dissolve"] = [{"at": tc_[0], "dur": DISSOLVE, "why": f"time of day {tc_[1]} -> {tc_[2]} ({tc_[3]})"}]
            clip_t[sg["clip"]] = round(t_in + max(0.0, dur - hold), 4)
            s["screen"] = sc
        else:
            s["screen"] = sg["screen"]
        if sg.get("text_check"):
            s["text_check"] = sg["text_check"]
        if sg.get("named"):
            s["named"] = sg["named"]
        if sg.get("edge_check") is False:
            s["edge_check"] = False          # elements the VO line names: `promo check` livestream-named / named-upscale
        s["note"] = sg.get("note", "")
        shots.append(s)
    shots[0]["sfx"] = [{"sfx": "swell", "at": 0.0, "db": -6}]
    f = credits_f[0]
    for i, x in enumerate(cr):                 # 2 cards: 11a notice + licence line, 11b model credits (UX review T6)
        e = {"id": "11" + ("ab"[i] if len(cr) > 1 else ""), "beats": [f, f + fr(x)], "type": "live2d_credits", "size": 30,
             "note": ["Live2D notice + licence line", "Live2D model credits"][i] if len(cr) > 1 else "Live2D notice + model credits end card"}
        if len(cr) > 1:
            e["part"] = i + 1
        shots.append(e)
        f += fr(x)

    seg_of = lambda tg: next(s for s in shots if s["beats"][0] <= fr(tg) < s["beats"][1])
    vo_lines = []
    for ln in lines:
        tg = starts[(ln["beat"], ln["line"])]
        s = seg_of(tg)
        p = os.path.join(vo_dir, ln["file"])
        e = {"id": ln["id"], "shot": s["id"], "at": round(tg - s["beats"][0] / fps, 3), "host": ln["host"].capitalize(),
             "text": ln["text"], "file": ln["file"], "sha256": sha(p), "dur": ln["duration"]}
        if ln.get("alt_files"):
            e["alt_files"] = ln["alt_files"]       # same bytes may move to vo/superseded/ mid-build (sha decides)
        if ln.get("placeholder"):
            e["placeholder"] = True
            e["voiced_text"] = ln["voiced_text"]
        if ln.get("variant"):
            e["variant"] = ln["variant"]
        if ln.get("trim"):
            e["trim"] = ln["trim"]
            e["script_text"] = ln["script_text"]
        vo_lines.append(e)
    chat = []
    for c in plan.get("chat") or []:
        chat.append({"t": round(first[c["beat"]] - plan["cut_lead"] + c["plus"], 3), "user": c["user"].capitalize(), "text": c["text"]})
    return dict(shots=shots, vo_lines=vo_lines, chat=chat, total_f=total_f, fps=fps, speech=round(speech_end, 3), takes=takes,
                vo_notes=vo_notes, variant=variant,
                tts={l["host"]: l.get("voice") for l in lines})


TEMPLATE_HEAD = """# GENERATED by make_spec.py from plan.yaml + the script + {lines_json} — do not edit; edit plan.yaml and re-run.
# Direction 3 talk show, "Building in Public, episode one". Two Live2D Original Character hosts (Hiyori top, Mao
# bottom, left column for the whole show, no move) beside the full-height stream screen playing real app takes (no chat
# strip: the asides were cut); every element a line names is pushed in on (`named`, gated by `promo check`);
# EP 1 tag (no LIVE badge, no viewer counts); two credits cards.
# VO: pre-rendered Kokoro-82M lines (Apache-2.0; HIYORI af_bella, MAO bf_isabella), sha256-pinned, by the Promo Video Director.
# Footage: clip ids from the hero footage manifest (never paths). Missing takes are reported by `promo build`; for a
# timing review use make_preview.py (labelled placeholder cards, gitignored preview spec, never a deliverable).
"""


def render(d, plan):
    fps = d["fps"]
    spec = {
        "project": {"name": "commission-ai-talkshow", "title": "Building in Public, episode one"},
        "output": {"name": "commission-ai-talkshow", "resolution": 1080, "fps": fps, "duration": round(d["total_f"] / fps, 3)},
        "paths": {"build": "build", "out": "out"},
        "assets": "assets.yaml",
        "footage": "${HERO_FOOTAGE_MANIFEST:-/workspace/promo-reel/projects/commission-ai-hero/footage/manifest.yaml}",
        "style": {"font": {"path": "${PROMO_FONT:-/usr/share/fonts/truetype/sand-box/google/Inter/Inter-VariableFont_opsz,wght.ttf}"}},
        "timeline": {"bpm": 60 * fps, "beats": d["total_f"]},
        "livestream": {
            "hosts_side": "left",
            "screen": dict(LS_CFG["screen"]),
            "margin": LS_CFG["margin"],
            "slot_gap": 16,
            "keep_clear": [{"name": "street-notice", "box": plan["keep_clear"]}],
            "tag": "EP 1",
            **({"style": plan["style"]} if plan.get("style") else {}),
            "title": "Building in Public",
            **({"chat": {"max_lines": 4, "lines": d["chat"]}} if d["chat"] else {}),
            "hosts": [
                {"id": "hiyori", "model": "hiyori", "name": "Hiyori", "seed": 11},
                {"id": "mao", "model": "mao", "name": "Mao", "seed": 22},
            ],
        },
        "vo": {"engine": "files", "asset": "talkshow-vo", "model_asset": "kokoro-model", "voices_asset": "kokoro-voices",
               "lines": [{k: v for k, v in l.items() if k != "dur"} for l in d["vo_lines"]]},
        "sfx": {"library": {"swell": {"asset": "sfx-swell"}}},
        "shots": d["shots"],
        "mix": {"sr": 48000, "bus_db": {"sfx": -10.0, "vo": 1.5}, "vo_line_lufs": -16.0, "fade_out": 0.03,
                "masters": [{"name": "web", "suffix": "", "lufs": -14.0, "ceiling": -1.2, "max_true_peak": -1.0}]},
        "qa": {"min_caption_hold": 2.0, "lufs_tolerance": 0.5, "vo_max_wer": 0.0, "asr_model": "small.en",
               # heard-as -> script (ASR spelling only): Kokoro says "Hiii" (TTS override), whisper writes numerals
               "asr_aliases": {"commission ai": "commission-ai", "work tree": "worktree", "Hi everyone": "Hiii everyone",
                               "Episode 1": "episode one"}},
    }
    head = TEMPLATE_HEAD.format(lines_json=os.path.join(plan["vo_dir"], "lines.json"))
    head += f"# beat 8 MAO line: variant {d['variant']!r} (shot11_legible = {plan.get('shot11_legible')!r})\n"
    for n in d["vo_notes"]:
        head += f"# {n}\n"
    for t in d["takes"]:
        head += (f"# auto take ({t['segment']}, {t['clip']}): measured {t['measured_px']} px (min {t['min_px']}) -> {t['line']} {t['take'].upper()}"
                 + (f"; fallback cut would be at {t['would_cut']['end']} s" if t["take"] == "full" and t.get("would_cut") else "") + "\n")
    return head + yaml.safe_dump(json.loads(json.dumps(spec)), sort_keys=False, allow_unicode=True, width=160)  # no &id aliases


def main():
    plan = yaml.safe_load(open(os.path.join(HERE, "plan.yaml")))
    plan.setdefault("keep_clear", [0.66, 0.0, 1.0, 0.30])
    d = build(plan)
    text = render(d, plan)
    out = os.path.join(HERE, "promo.yaml")
    if "--check" in sys.argv:
        ok = os.path.exists(out) and open(out).read() == text
        print("promo.yaml up to date" if ok else "promo.yaml is STALE: re-run make_spec.py")
        sys.exit(0 if ok else 1)
    with open(out, "w") as f:
        f.write(text)
    tot = d["total_f"] / d["fps"]
    for t in d["takes"]:
        print(f"auto take {t['segment']}: {t['measured_px']} px (min {t['min_px']}) -> {t['line']} {t['take']} (cut point {t['would_cut']})")
    print(f"beat 8 variant: {d['variant']}")
    for n in d["vo_notes"]:
        print(n)
    print(f"wrote {out}: {len(d['shots'])} shots, {len(d['vo_lines'])} VO lines, speech ends {d['speech']:.2f} s, total {tot:.2f} s")
    for s in d["shots"]:
        sc = s.get("screen", {})
        print(f"  {s['id']:>4} [{s['beats'][0]/d['fps']:6.2f}-{s['beats'][1]/d['fps']:6.2f}] {sc.get('source') or ('card' if 'card' in sc else s['type'])}"
              f"  t_in={sc.get('t_in', '-')} hold_in={sc.get('hold_in', '-')}")


if __name__ == "__main__":
    main()
