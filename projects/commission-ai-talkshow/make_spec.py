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


def auto_take(plan, lines, vo_dir):
    """Segments with `text_check` + `fallback_trim`: measure the key text line through the segment's cam on the
    1440-px screen. Below `min_px` (or footage missing) -> trim that beat's line at the silence after `after`
    (short fade) and voice only that prefix. Mutates `lines`; returns a report per segment."""
    import soundfile as sf

    from promo import livestream as LS
    from promo import vo as VO
    out = []
    for sg in plan["segments"]:
        tc, ft = sg.get("text_check"), sg.get("fallback_trim")
        if not (tc and ft):
            continue
        p = clip_path(sg["clip"])
        m = LS.text_height(p, float(sg.get("t_in", 0.0)) + 0.05, sg.get("cam", (0.5, 0.5, 1.0)), 1440, tc["box"], tc.get("src_px")) if p else None
        ok = bool(m and m["px"] >= tc.get("min_px", 24) and m["inside"])
        ln = next(l for l in lines if l["beat"] == sg["beat"] and l["line"] == ft["line"])
        x, sr = sf.read(os.path.join(vo_dir, ln["file"]), dtype="float32", always_2d=True)
        cut = VO.cut_after(x.mean(1), sr, ln["text"], ft["after"])
        rep = dict(segment=str(sg["id"]), clip=sg["clip"], measured_px=round(m["px"], 1) if m else None, min_px=tc.get("min_px", 24),
                   line=ln["id"], take="full" if ok else "trimmed", would_cut=cut)
        if not ok:
            if not cut:
                raise SystemExit(f"auto_take: no silence found after {ft['after']!r} in {ln['file']}")
            ln["script_text"] = ln["text"]
            ln["text"] = cut["prefix"]
            ln["trim"] = {"end": cut["end"], "fade": cut["fade"]}
            ln["duration"] = cut["end"]
        out.append(rep)
    return out


def build(plan):
    fps = plan["fps"]
    fr = lambda t: int(round(t * fps))
    vo_dir = expand(plan["vo_dir"])
    lj = json.load(open(os.path.join(vo_dir, "lines.json")))
    lines = sorted(lj["lines"], key=lambda l: (l["beat"], l["line"]))
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
    credits_f = (end_f, end_f + fr(plan["credits"]))
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
            sc["t_in"] = round(t_in, 3)
            if hold > 0:
                sc["hold_in"] = round(hold, 3)
            if sg.get("cam"):
                sc["cam"] = sg["cam"]
            clip_t[sg["clip"]] = round(t_in + max(0.0, dur - hold), 4)
            s["screen"] = sc
        else:
            s["screen"] = sg["screen"]
        if sg.get("text_check"):
            s["text_check"] = sg["text_check"]
        s["note"] = sg.get("note", "")
        shots.append(s)
    shots[0]["sfx"] = [{"sfx": "swell", "at": 0.0, "db": -6}]
    shots.append({"id": "11", "beats": list(credits_f), "type": "live2d_credits", "size": 30,
                  "note": "Live2D notice + model credits end card"})

    seg_of = lambda tg: next(s for s in shots if s["beats"][0] <= fr(tg) < s["beats"][1])
    vo_lines = []
    for ln in lines:
        tg = starts[(ln["beat"], ln["line"])]
        s = seg_of(tg)
        p = os.path.join(vo_dir, ln["file"])
        e = {"id": ln["id"], "shot": s["id"], "at": round(tg - s["beats"][0] / fps, 3), "host": ln["host"].capitalize(),
             "text": ln["text"], "file": ln["file"], "sha256": sha(p), "dur": ln["duration"]}
        if ln.get("trim"):
            e["trim"] = ln["trim"]
            e["script_text"] = ln["script_text"]
        vo_lines.append(e)
    chat = []
    for c in plan["chat"]:
        chat.append({"t": round(first[c["beat"]] - plan["cut_lead"] + c["plus"], 3), "user": c["user"].capitalize(), "text": c["text"]})
    return dict(shots=shots, vo_lines=vo_lines, chat=chat, total_f=total_f, fps=fps, speech=round(speech_end, 3), takes=takes,
                tts={l["host"]: l.get("voice") for l in lines})


TEMPLATE_HEAD = """# GENERATED by make_spec.py from plan.yaml + {lines_json} — do not edit; edit plan.yaml and re-run.
# Direction 3 talk show, "Building in Public, episode one". Two Live2D Original Character hosts (Hiyori top, Mao
# bottom, left column for the whole show, no move) beside the stream screen playing real app takes; chat strip =
# HIYORI's own scripted asides only (never voiced); EP 1 tag (no LIVE badge, no viewer counts); credits end card.
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
            "screen": {"w": 1440},
            "margin": 24,
            "slot_gap": 16,
            "keep_clear": [{"name": "street-notice", "box": plan["keep_clear"]}],
            "tag": "EP 1",
            "title": "Building in Public",
            "chat": {"max_lines": 4, "lines": d["chat"]},
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
    for t in d["takes"]:
        head += (f"# auto take ({t['segment']}, {t['clip']}): measured {t['measured_px']} px (min {t['min_px']}) -> {t['line']} {t['take'].upper()}"
                 + (f"; fallback cut would be at {t['would_cut']['end']} s" if t["take"] == "full" and t.get("would_cut") else "") + "\n")
    return head + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True, width=160)


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
    print(f"wrote {out}: {len(d['shots'])} shots, {len(d['vo_lines'])} VO lines, speech ends {d['speech']:.2f} s, total {tot:.2f} s")
    for s in d["shots"]:
        sc = s.get("screen", {})
        print(f"  {s['id']:>4} [{s['beats'][0]/d['fps']:6.2f}-{s['beats'][1]/d['fps']:6.2f}] {sc.get('source') or ('card' if 'card' in sc else s['type'])}"
              f"  t_in={sc.get('t_in', '-')} hold_in={sc.get('hold_in', '-')}")


if __name__ == "__main__":
    main()
