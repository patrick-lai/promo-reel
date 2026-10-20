"""Ears for the agent: listen to a take, a file or a project's VO and mix, and hear what the numbers miss. `promo listen`.

  promo listen FILE [FILE ...] [--ear] [--runs 2] [--careful | --model M] [--max-usd 0.50] [--out DIR] [--json]
  promo -p PROJECT listen [--line ID ...] [--mix] [--ear] ...   each VO line as it sounds in the mix's VO stem, or (--mix) in the mix;
                                                                 the local checks read the VO stem either way, --mix adds `buried`
  promo listen compare A B [--careful | --model M] [--max-usd]   blind A/B in both orders: a winner only when both orders agree
  promo listen calibrate CASES.json [--runs 2] ...               files with planted defects at known times: how much the ear hears

Always (free, local): per window the numbers (LUFS, peak, flat tops, the floor, the tail, clicks, dead air) and the findings they
prove (clipping, artifact, pacing, cut_off, noise; with --mix also buried), plus a sheet PNG (waveform, spectrogram, loudness,
findings) the agent can look at.

--ear sends each window (a VO line, or 20 s of a long file) as mono mp3 to an audio model on OpenRouter (default gemini-3.8-flash,
--careful gemini-3.1-pro-preview) with a fixed rubric (RUBRIC_VERSION) and without the script: a model given the script hears the
script. It answers with what it heard, timed findings (ISSUES, severity 1 minor, 2 most viewers notice, 3 must fix) and 1-5 scores;
the script is compared with what it heard here, locally. Each window runs `--runs` times; a finding heard in every run, or matching a
local finding, is `solid`, the rest `maybe`. Calls are priced first (the whole command against --max-usd and the daily cap), logged in
the spend ledger with their billed cost, and cached by their exact request, so asking again is free.
Measured (docs/audio-stack-2026-10.md): the model alone hears robotic reads, cut-offs, dead air and hiss, but not clipping, clicks or a
voice buried under music, and it can "hear" the word it expects. The local detectors cover the first two, `--mix` (as vo-masking) the third.

It advises. `promo check` and the person decide: act on solid findings, keep a fix only when `compare` prefers it in both orders, and
never pick a take for the person by ear scores (they drift to the flattest read, as vo_score found).
"""
from __future__ import annotations

import argparse
import base64
import difflib
import hashlib
import json
import os
import subprocess
import sys

import numpy as np

from . import openrouter as OR

RUBRIC_VERSION = 1
DEFAULT_MODEL = "google/gemini-3.8-flash"
CAREFUL_MODEL = "google/gemini-3.1-pro-preview"   # gemini-4-argon answered garbage through OpenRouter (21 Oct 2026)
DEFAULT_MAX_USD = 0.50          # priced as if every answer used all MAX_TOKENS (~$0.025 a call); real calls cost a few tenths of a cent
MAX_TOKENS = 6000                # high reasoning (needed for a faithful transcript) used over 2,500 on a 6 s clip
REASONING_TOKENS = 4000
WINDOW_S = 20.0                 # a long file is heard in pieces: timestamps hold up and uploads stay small
PAD_S = 0.3                     # around a VO line, so its first and last sounds are inside the window
MATCH_S = 0.75                  # two findings of one issue this close are the same finding
ISSUES = ("robotic", "artifact", "clipping", "cut_off", "noise", "pacing", "mispronounced", "buried", "level_jump", "music_clash", "other")

RUBRIC = f"""You are a re-recording mixer and voice director (rubric v{RUBRIC_VERSION}). Listen to this {{kind}} ({{dur:.1f}} s) as a viewer would.
Report every problem a careful listener would notice, with start and end times in seconds from the start of the clip:
robotic (flat, synthetic, monotone or sing-song read), artifact (click, glitch, warble, metallic or phasey sound, a splice),
clipping (distortion on loud sounds), cut_off (a word or sound cut off abruptly), noise (hiss, hum, background noise),
pacing (an unnatural pause, dead air, a rushed or dragged phrase), mispronounced (a word said wrongly or unclearly),
buried (the voice hard to follow under music or effects), level_jump (a sudden change in loudness), music_clash (music fighting
the voice), other. Severity: 1 minor, 2 most viewers would notice, 3 must fix before anyone hears it.
Report only what you actually heard; an empty list is a good answer for clean audio.
Also write down exactly the words you hear (not what you think was meant), and score 1-5: naturalness of the voice, clarity of
the words, balance of voice against other sound (5 if there is only a voice), overall polish."""

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["heard", "findings", "scores"], "properties": {
    "heard": {"type": "string"},
    "findings": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                            "required": ["t0", "t1", "issue", "severity", "note", "fix"], "properties": {
        "t0": {"type": "number"}, "t1": {"type": "number"}, "issue": {"type": "string", "enum": list(ISSUES)},
        "severity": {"type": "integer", "enum": [1, 2, 3]}, "note": {"type": "string"}, "fix": {"type": "string"}}}},
    "scores": {"type": "object", "additionalProperties": False, "required": ["naturalness", "clarity", "balance", "polish"],
               "properties": {k: {"type": "integer", "enum": [1, 2, 3, 4, 5]} for k in ("naturalness", "clarity", "balance", "polish")}}}}

AB_PROMPT = f"""Two versions of the same piece of audio follow: the first clip, then the second (rubric v{RUBRIC_VERSION}).
Which one is better as finished audio for a product video: a more natural voice, clearer words, fewer artifacts, cleaner edges,
better balance against music? Answer "same" when you cannot hear a difference that matters."""
AB_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["better", "why", "decisive_defect"], "properties": {
    "better": {"type": "string", "enum": ["first", "second", "same"]}, "why": {"type": "string"}, "decisive_defect": {"type": "string"}}}

CLIP_SAMPLES = 8               # flat-topped samples at one level before it reads as a clip ceiling
DEAD_AIR_S = 1.0              # silence this long inside a line reads as a mistake, not a pause
NOISE_DB = -40.0               # a floor this close under the loud level is heard as hiss (Ming's own sits at -41..-45)
# clicks: 1 ms frames of the window's top band (above 55 % of Nyquist) at least CLICK_DB over the median of the 60 ms around them
# and over the frames 5 ms either side, and no more than CLICK_FLOOR_DB under the window's average level. A click is broadband and
# over in 1-3 ms; speech is quiet up there (TTS made at 24 kHz has nothing above 12 kHz) and a "t" or "p" burst lasts 10 ms and more.
# Tuned on 12 clean takes from 4 voices and the 16 commission-ai-jev lines in its VO stem and mix (none flagged), and two planted clicks.
CLICK_DB, CLICK_FLOOR_DB = 30.0, 30.0
VO_MUSIC_MIN_DB = 10.0         # as qa.vo_music_min_db: a line less far over the music in 1-5 kHz is hard to follow


# ---------------------------------------------------------------- audio in
def decode(path, sr=48000):
    """Any audio or video file -> (mono float64, rate). A file soundfile reads keeps its own rate (resampling would smooth away the
    flat tops of a clipped take); anything else (mp4, m4a) comes through ffmpeg at `sr`."""
    import soundfile as sf
    if not os.path.isfile(path):
        raise SystemExit(f"promo listen: no such file: {path}")
    try:
        x, own = sf.read(path, dtype="float64", always_2d=True)
        return x.mean(1), own
    except (sf.LibsndfileError, RuntimeError):
        pass
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    if r.returncode or not r.stdout:
        raise SystemExit(f"promo listen: cannot read audio from {path}: {r.stderr.decode(errors='replace').strip()[:200] or 'no audio stream'}")
    return np.frombuffer(r.stdout, "<f4").astype(np.float64), sr


def mp3(x, sr):
    """Mono mp3 at 96 kbps: what the ear hears (a 20 s window is ~240 kB)."""
    r = subprocess.run(["ffmpeg", "-v", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-c:a", "libmp3lame", "-b:a", "96k", "-f", "mp3", "-"],
                       input=np.asarray(x, "<f4").tobytes(), capture_output=True, check=True)
    return r.stdout


def file_windows(path):
    x, sr = decode(path)
    name = os.path.basename(path)
    n = max(1, int(np.ceil(len(x) / sr / WINDOW_S - 1e-9)))
    if n == 1:
        return [dict(label=name, kind="voice-over clip", x=x, sr=sr, offset=0.0, text=None)]
    step = int(WINDOW_S * sr)
    return [dict(label=f"{name}@{i * WINDOW_S:g}s", kind="piece of a mix", x=x[i * step:(i + 1) * step], sr=sr, offset=i * WINDOW_S, text=None)
            for i in range(n)]


def project_windows(spec, lines=None, mix=False):
    """One window per VO line placed in the mix: the VO stem (how the voice itself sounds after polish and fx) or, with `mix`, the
    first master (how it sits against music and effects) for the ear. The line id comes from the window, never from the model.
    The local checks always read the VO stem (`voice`): in the mix the music carries on under every pause and past every line's end,
    which would read as hiss and a cut-off; the mix's own local check is the line's `vo_music_db` (buried under the music)."""
    import soundfile as sf

    from .check import vo_music_db
    rp = os.path.join(spec.audio_dir, "mix-report.json")
    stem = os.path.join(spec.audio_dir, "stems", "vo.wav")
    src = os.path.join(spec.audio_dir, f"mix-{spec.masters[0]['name']}.wav") if mix else stem
    if not (os.path.exists(rp) and os.path.exists(src) and os.path.exists(stem)):
        raise SystemExit("promo listen: no mix yet; run `promo build` (or `promo mix`) first")
    spec_lines = {str(ln.get("id", ln.get("shot"))): ln for ln in (spec.raw.get("vo") or {}).get("lines") or []}
    ratios = (vo_music_db(spec) or {}) if mix else {}

    def cut(path, a, b):
        sr = sf.info(path).samplerate
        x, _ = sf.read(path, start=int(a * sr), stop=int(b * sr), dtype="float64", always_2d=True)
        return x.mean(1), sr
    out = []
    for t0, t1, lid, text in json.load(open(rp))["vo"]:
        if lines and str(lid) not in lines:
            continue
        a = max(0.0, t0 - PAD_S)
        x, sr = cut(src, a, t1 + PAD_S)
        voice, vsr = (x, sr) if src == stem else cut(stem, a, t1 + PAD_S)
        ln = spec_lines.get(str(lid), {})
        # the project's and the line's asr_aliases (heard-as -> script word), as vo-script uses them: "1" read as "one" is not an error
        out.append(dict(label=str(lid), kind="voice-over line in a mix" if mix else "voice-over line", x=x, sr=sr, voice=voice, voice_sr=vsr,
                        offset=a, vo_music_db=ratios.get(str(lid)), text=ln.get("text", text),
                        aliases={**(spec.qa.get("asr_aliases") or {}), **(ln.get("asr_aliases") or {})}))
    missing = sorted(set(lines or ()) - {w["label"] for w in out})
    if missing:
        raise SystemExit(f"promo listen: no VO line {', '.join(missing)} in the mix (lines: {', '.join(spec_lines) or 'none'})")
    return out


# ---------------------------------------------------------------- local numbers
def _clicks(x, sr):
    from scipy.ndimage import median_filter

    from .audiofx import _filt, _sos
    hp = _filt(x, _sos("high", 0.55 * sr / 2, 4, sr))
    hop = max(1, int(0.001 * sr))
    n = len(hp) // hop
    if n < 61:
        return []
    e = 10 * np.log10(np.mean(hp[: n * hop].reshape(n, hop) ** 2, 1) + 1e-20)
    near = np.maximum(np.r_[np.full(5, -200.0), e[:-5]], np.r_[e[5:], np.full(5, -200.0)])
    average = 10 * np.log10(np.mean(x ** 2) + 1e-20)
    hit = (e - median_filter(e, size=61, mode="nearest") > CLICK_DB) & (e - near > CLICK_DB) & (e > average - CLICK_FLOOR_DB)
    return [round(i / 1000, 3) for i in np.nonzero(hit & ~np.r_[False, hit[:-1]])[0]]


def metrics(x, sr):
    import pyloudnorm as pyln

    from .vo_score import tail_db
    hop = int(0.02 * sr)
    n = len(x) // hop
    fr = 10 * np.log10(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20) if n else np.array([-200.0])
    loud = float(np.percentile(fr, 90))
    sound = np.nonzero(fr > loud - 45)[0]
    gaps = []                                                   # silences between the first and last sound of the window
    if len(sound):
        for a, b in zip(sound, sound[1:]):
            if (b - a) * 0.02 >= DEAD_AIR_S:
                gaps.append([round((a + 1) * 0.02, 2), round(b * 0.02, 2)])
    # a flat top: three equal samples in a row on a loud sample, at any level (a clip at 0.8 is as clipped as one at 1.0), counted only
    # at a level where CLIP_SAMPLES of them sit: a clipped take keeps hitting its ceiling, while coarse audio (macOS `say`) repeats a
    # sample now and then at many different levels
    flat = (np.abs(x[:-2]) >= 0.1) & (x[:-2] == x[1:-1]) & (x[1:-1] == x[2:])
    levels, counts = np.unique(np.abs(x[:-2][flat]), return_counts=True)
    flat &= np.isin(np.abs(x[:-2]), levels[counts >= CLIP_SAMPLES])
    clipped = []                                                # stretches of flat tops, 0.25 s apart or more
    for i in np.nonzero(flat)[0] / sr:
        if clipped and i - clipped[-1][1] < 0.25:
            clipped[-1][1] = round(float(i), 2)
        else:
            clipped.append([round(float(i), 2), round(float(i), 2)])
    return dict(dur=round(len(x) / sr, 2), lufs=round(float(pyln.Meter(sr).integrated_loudness(x)), 1) if len(x) > sr // 2 else None,
                peak_dbfs=round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 1), flat_tops=int(flat.sum()), clipped=clipped,
                floor_db=round(float(np.percentile(fr, 10)) - loud, 1), tail_db=round(float(tail_db(x.astype(np.float32), sr)), 1),
                dead_air=gaps, clicks=_clicks(x, sr))


def local_findings(m):
    """What the numbers alone can tell, as findings in the ear's own form (times from the window start)."""
    out = []
    for a, b in m["clipped"]:
        out.append(dict(t0=a, t1=max(b, a + 0.05), issue="clipping", severity=3, note="flat-topped samples: the waveform was cut off at a level",
                        fix="re-voice or lower the gain before the clip; nothing in post un-clips it"))
    for t in m["clicks"]:
        out.append(dict(t0=t, t1=t + 0.01, issue="artifact", severity=2, note="a click: a 1-3 ms burst far over its surroundings",
                        fix="another take, or move the cut that made it"))
    for a, b in m["dead_air"]:
        out.append(dict(t0=a, t1=b, issue="pacing", severity=2, note=f"{b - a:.1f} s of silence inside the line",
                        fix="close the gap (another take, or split the line)"))
    if m["tail_db"] > -35.0:
        out.append(dict(t0=max(0.0, m["dur"] - 0.3), t1=m["dur"], issue="cut_off", severity=3, note=f"ends {m['tail_db']} dB under its loudest, mid-sound",
                        fix="re-voice, or move the cut into a silence"))
    if m["floor_db"] > NOISE_DB:
        out.append(dict(t0=0.0, t1=m["dur"], issue="noise", severity=2, note=f"the floor is only {-m['floor_db']:.0f} dB under the voice",
                        fix="vo.polish (gate), a cleaner take, or less music bleed"))
    return [dict(f, seen="local", backed=True, solid=True) for f in out]


# ---------------------------------------------------------------- the ear
def _cache_dir():
    return OR._tools_dir() / "listen-cache"


def _ask(body, price, max_usd):
    """(answer dict, billed?) for one request; the cache key is the exact request with each clip replaced by its hash."""
    key_body = json.loads(json.dumps(body))
    for part in key_body["messages"][0]["content"]:
        if part.get("type") == "input_audio":
            part["input_audio"]["data"] = hashlib.sha256(base64.b64decode(part["input_audio"]["data"])).hexdigest()
    key = hashlib.sha256(json.dumps(key_body, sort_keys=True).encode()).hexdigest()[:24]
    p = _cache_dir() / f"{key}.json"
    if p.exists():
        return json.loads(p.read_text()), False
    text = OR.listen(body, price, max_usd).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    try:
        ans = json.loads(text)
    except ValueError:
        raise OR.OpenRouterError(f"{body['model']} did not answer in JSON: {text[:160]!r}") from None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(ans))
    return ans, True


def _body(model, prompt, clips, schema, seed):
    content = [{"type": "text", "text": prompt}] + [{"type": "input_audio", "input_audio": {"data": base64.b64encode(c).decode(), "format": "mp3"}}
                                                     for c in clips]
    return {"model": model, "messages": [{"role": "user", "content": content}], "temperature": 0.3, "seed": seed, "max_tokens": MAX_TOKENS,
            "reasoning": {"max_tokens": REASONING_TOKENS}, "response_format": {"type": "json_schema", "json_schema": {"name": "listen", "strict": True, "schema": schema}}}


def _same(a, b):
    return a["issue"] == b["issue"] and a["t0"] - MATCH_S <= b["t1"] and b["t0"] - MATCH_S <= a["t1"]


def _merge(runs, local):
    """One list from `runs` answers: a finding heard in every run, or matching a local finding, is solid."""
    groups = []
    for r, ans in enumerate(runs):
        for f in ans["findings"]:
            g = next((g for g in groups if _same(g[0], f) and r not in g[1]), None)
            if g:
                g[0].setdefault("_all", [g[0]]).append(f)
                g[1].add(r)
            else:
                groups.append([dict(f), {r}])
    out = []
    for f, seen in groups:
        allf = f.pop("_all", [f])
        backed = any(_same(f, x) for x in local)
        out.append(dict(t0=round(float(np.median([x["t0"] for x in allf])), 2), t1=round(float(np.median([x["t1"] for x in allf])), 2),
                        issue=f["issue"], severity=int(round(np.median([x["severity"] for x in allf]))), note=f["note"], fix=f["fix"],
                        seen=f"{len(seen)}/{len(runs)}", backed=backed, solid=len(seen) == len(runs) or backed))
    return sorted(out, key=lambda f: (-f["solid"], -f["severity"], f["t0"]))


def _script_findings(text, heard, dur, aliases=None):
    """Words the script has and the ear did not hear the same: wrong or swapped words, with a time guessed from their place in the line."""
    from .check import _aliased, norm_words, soundex
    ref, hyp = norm_words(text), norm_words(_aliased({}, heard, {"asr_aliases": aliases or {}}))
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=ref, b=hyp, autojunk=False).get_opcodes():
        if op in ("replace", "delete"):
            said = " ".join(hyp[j1:j2]) or "nothing"
            # words that sound alike are minor: mostly spelling ("two" / "to"), though Soundex also hides "override" / "overwrite"
            alike = [soundex(w) for w in ref[i1:i2]] == [soundex(w) for w in hyp[j1:j2]]
            out.append(dict(t0=round(dur * i1 / max(1, len(ref)), 2), t1=round(dur * i2 / max(1, len(ref)), 2), issue="mispronounced",
                            severity=1 if alike else 2,
                            note=f"script {' '.join(ref[i1:i2])!r}, heard {said!r}", fix="re-voice the line, or spell the word as it is said",
                            seen="script", backed=False, solid=False))
    return out


def plan_price(model, windows, runs, compare=False):
    m = OR.listen_model(model)
    return sum(OR.listen_estimate(m, len(w["x"]) / w["sr"] * (2 if compare else 1), MAX_TOKENS) for w in windows) * runs


def ear(windows, model=DEFAULT_MODEL, runs=2, max_usd=DEFAULT_MAX_USD, log=print):
    """Each window heard `runs` times; findings get absolute times (window offset added here). Mutates and returns `windows`."""
    total = plan_price(model, windows, runs)
    OR.guard(total, max_usd)
    log(f"ear: {len(windows)} window(s) x {runs} run(s) on {model}, at most ${total:.4f}")
    m = OR.listen_model(model)
    for w in windows:
        clip = mp3(w["x"], w["sr"])
        dur = len(w["x"]) / w["sr"]
        answers, billed = [], 0
        for r in range(runs):
            ans, paid = _ask(_body(model, RUBRIC.format(kind=w["kind"], dur=dur), [clip], SCHEMA, seed=r + 1),
                             OR.listen_estimate(m, dur, MAX_TOKENS), max_usd)
            answers.append(ans)
            billed += paid
        heard = _merge(answers, w["findings"])
        if w.get("text"):
            heard += _script_findings(w["text"], answers[0]["heard"], dur, w.get("aliases"))
        w["findings"] = _absolute(w, [f for f in w["findings"] if not any(_same(f, h) for h in heard)] + heard)
        w["ear"] = dict(model=model, heard=answers[0]["heard"], scores={k: round(float(np.mean([a["scores"][k] for a in answers])), 1)
                                                                          for k in answers[0]["scores"]}, new_calls=billed)
    return windows


def _absolute(w, findings):
    """Findings sorted (solid, worst, earliest first) with `at`: the time in the listened file or project."""
    for f in findings:
        f["at"] = round(w["offset"] + f["t0"], 2)
    return sorted(findings, key=lambda f: (-f["solid"], -f["severity"], f["t0"]))


def hear_locally(windows):
    """The free part: numbers and local findings for each window."""
    for w in windows:
        w["metrics"] = metrics(w["voice"], w["voice_sr"]) if "voice" in w else metrics(w["x"], w["sr"])
        found = local_findings(w["metrics"])
        if w.get("vo_music_db") is not None and w["vo_music_db"] < VO_MUSIC_MIN_DB:
            found.append(dict(t0=0.0, t1=w["metrics"]["dur"], issue="buried", severity=2, seen="local", backed=True, solid=True,
                              note=f"the voice is only {w['vo_music_db']:.1f} dB over the music in 1-5 kHz",
                              fix="duck more, `mix.duck.band`, or lower bus_db.music"))
        w["findings"] = _absolute(w, found)
    return windows


def compare(a, b, model=DEFAULT_MODEL, max_usd=DEFAULT_MAX_USD):
    """Blind A/B in both orders. {winner: "A" | "B" | "unsure", orders: [...]}: a winner only when both orders name the same file."""
    xa, sra = decode(a)
    xb, srb = decode(b)
    ca, cb = mp3(xa, sra), mp3(xb, srb)
    m = OR.listen_model(model)
    each = OR.listen_estimate(m, len(xa) / sra + len(xb) / srb, MAX_TOKENS)
    OR.guard(2 * each, max_usd)
    picks = []
    for first, second, names in ((ca, cb, ("A", "B")), (cb, ca, ("B", "A"))):
        ans, _ = _ask(_body(model, AB_PROMPT, [first, second], AB_SCHEMA, seed=1), each, max_usd)
        picks.append(dict(first=names[0], pick={"first": names[0], "second": names[1]}.get(ans["better"], "same"), why=ans["why"],
                          decisive_defect=ans["decisive_defect"]))
    p1, p2 = picks[0]["pick"], picks[1]["pick"]
    return dict(winner=p1 if p1 == p2 and p1 != "same" else "unsure", orders=picks)


# ---------------------------------------------------------------- calibration
def calibrate(cases_path, model=DEFAULT_MODEL, runs=2, max_usd=DEFAULT_MAX_USD, log=print):
    """Score the ear on files with planted defects: cases.json [{file, text?, expect: [{issue, t0, t1}]}] (paths relative to it).
    A planted defect is caught by a solid finding of its issue within MATCH_S of its span; on a file with `expect: []` a solid finding
    of severity >= 2 is a false alarm. Counted for the whole ear (local detectors + script diff + model) and for the model alone."""
    base = os.path.dirname(os.path.abspath(cases_path))
    cases = json.load(open(cases_path))
    wins = []
    for c in cases:
        ws = hear_locally(file_windows(os.path.join(base, c["file"])))
        for w in ws:
            w["text"] = c.get("text")
        wins.append(ws)
    OR.guard(sum(plan_price(model, ws, runs) for ws in wins), max_usd)
    tally = dict(planted=0, caught=0, caught_by_model=0, false_alarms=0, false_alarms_by_model=0, maybes=0)
    rows = []
    for c, ws in zip(cases, wins):
        ear(ws, model, runs, max_usd, log=lambda *a: None)
        found = [dict(f, t0=f["at"], t1=f["at"] + f["t1"] - f["t0"]) for w in ws for f in w["findings"]]
        by_model = [f for f in found if f["seen"] not in ("local", "script")]
        hits = []
        for e in c["expect"]:
            hit = any(f["solid"] and _same(e, f) for f in found)
            tally["planted"] += 1
            tally["caught"] += hit
            tally["caught_by_model"] += any(f["solid"] and _same(e, f) for f in by_model)
            hits.append(f"{e['issue']}{'+' if hit else '-'}")
        if not c["expect"]:
            tally["false_alarms"] += sum(f["solid"] and f["severity"] >= 2 for f in found)
            tally["false_alarms_by_model"] += sum(f["solid"] and f["severity"] >= 2 for f in by_model)
        tally["maybes"] += sum(not f["solid"] for f in found)
        rows.append(dict(file=c["file"], expect=[e["issue"] for e in c["expect"]], result=hits or ["clean"],
                         heard=[f"{f['issue']}@{f['t0']:.1f}s s{f['severity']} {f['seen']}{' backed' if f['backed'] else ''}" for f in found],
                         scores=[w["ear"]["scores"] for w in ws]))
        log(f"  {c['file']:<28} {' '.join(hits) or 'clean':<22} {'; '.join(rows[-1]['heard'])[:120]}")
    return dict(model=model, runs=runs, rubric=RUBRIC_VERSION, **tally, rows=rows)


# ---------------------------------------------------------------- sheet
def sheet(windows, out_png, title):
    """Waveform, spectrogram and short-term loudness of the listened audio end to end, windows labelled, findings marked."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from scipy import signal
    from scipy.signal import resample_poly
    sr = windows[0]["sr"]
    xs = np.concatenate([w["x"] if w["sr"] == sr else resample_poly(w["x"], sr, w["sr"]) for w in windows])
    starts = np.cumsum([0] + [len(w["x"]) / w["sr"] for w in windows])[:-1]
    t = np.arange(len(xs)) / sr
    fig, ax = plt.subplots(3, 1, figsize=(max(10, min(40, len(xs) / sr / 2)), 7.5), dpi=100, sharex=True)
    ax[0].plot(t[::max(1, len(t) // 20000)], xs[::max(1, len(t) // 20000)], lw=0.4, color="#333")
    ax[0].set_ylim(-1, 1)
    f, tt, S = signal.spectrogram(xs, sr, nperseg=1024, noverlap=512)
    ax[1].pcolormesh(tt, f / 1000, 10 * np.log10(S / (S.max() + 1e-20) + 1e-12), vmin=-90, vmax=0, cmap="magma", shading="auto")
    ax[1].set_ylim(0, min(16, sr / 2000))
    ax[1].set_ylabel("kHz")
    hop = int(0.1 * sr)
    n = len(xs) // hop
    st = 10 * np.log10(np.convolve(np.mean(xs[: n * hop].reshape(n, hop) ** 2, 1), np.ones(4) / 4, mode="same") + 1e-12)
    ax[2].plot(np.arange(n) * 0.1, st, color="#d9480f")
    ax[2].set_ylim(max(-90, st.min() - 3), 0)
    ax[2].set_ylabel("dBFS (0.4 s)")
    ax[2].set_xlabel("seconds (windows end to end)")
    for w, s in zip(windows, starts):
        for a in ax:
            a.axvline(s, color="#1971c2", lw=0.8, alpha=0.6)
        ax[0].text(s + 0.05, 0.85, w["label"], fontsize=8, color="#1971c2")
        for fd in w["findings"]:
            col = {3: "#e03131", 2: "#f08c00", 1: "#868e96"}[fd["severity"]]
            ax[0].axvspan(s + fd["t0"], s + max(fd["t1"], fd["t0"] + 0.1), color=col, alpha=0.25 if fd["solid"] else 0.1)
            ax[0].text(s + fd["t0"], -0.95, fd["issue"], fontsize=7, color=col)
    ax[0].set_title(title, loc="left")
    fig.tight_layout()
    os.makedirs(os.path.dirname(out_png) or ".", exist_ok=True)
    fig.savefig(out_png)
    plt.close(fig)
    return out_png


# ---------------------------------------------------------------- CLI
def _model(a):
    return a.model or (CAREFUL_MODEL if a.careful else DEFAULT_MODEL)


def _print(windows):
    for w in windows:
        m = w["metrics"]
        print(f"{w['label']} @ {w['offset']:.2f}s  {m['dur']}s  LUFS {m['lufs']}  peak {m['peak_dbfs']} dBFS  flat-tops {m['flat_tops']}  "
              f"floor {m['floor_db']} dB  tail {m['tail_db']} dB  clicks {len(m['clicks'])}  dead air {len(m['dead_air'])}")
        e = w.get("ear")
        if e:
            print(f"   heard: {e['heard']!r}")
            print("   scores: " + ", ".join(f"{k} {v}" for k, v in e["scores"].items()))
        for f in w["findings"]:
            print(f"   {'SOLID' if f['solid'] else 'maybe'} s{f['severity']} {f['issue']:<13} at {f['at']:.2f}s ({f['seen']}{', backed' if f['backed'] and f['seen'] != 'local' else ''})"
                  f"  {f['note']}  -> {f['fix']}")


def main(argv, project=None):
    ap = argparse.ArgumentParser(prog="promo listen", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="audio or video files; `compare A B`; `calibrate CASES.json`")
    ap.add_argument("--line", action="append", help="with -p: only this VO line (repeat for more)")
    ap.add_argument("--mix", action="store_true", help="with -p: each line as it sits in the mix, not the VO stem")
    ap.add_argument("--ear", action="store_true", help="also send it to an audio model on OpenRouter (paid, cached)")
    ap.add_argument("--runs", type=int, default=2, help="times each window is heard (a finding in every run is solid)")
    ap.add_argument("--model", help=f"audio model (default {DEFAULT_MODEL})")
    ap.add_argument("--careful", action="store_true", help=f"use {CAREFUL_MODEL}")
    ap.add_argument("--max-usd", type=float, default=DEFAULT_MAX_USD, help="most this whole command may spend")
    ap.add_argument("--out", help="where the sheet and report go")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.files[:1] == ["compare"]:
            if len(a.files) != 3:
                raise SystemExit("promo listen compare A B: two files")
            r = compare(a.files[1], a.files[2], _model(a), a.max_usd)
            if a.json:
                print(json.dumps(r, indent=1))
            else:
                print(f"winner: {r['winner']}")
                for o in r["orders"]:
                    print(f"  {o['first']} played first -> {o['pick']}: {o['why']} (decisive: {o['decisive_defect']})")
            return 0
        if a.files[:1] == ["calibrate"]:
            if len(a.files) != 2:
                raise SystemExit("promo listen calibrate CASES.json")
            r = calibrate(a.files[1], _model(a), a.runs, a.max_usd)
            print(json.dumps(r, indent=1) if a.json else
                  f"caught {r['caught']}/{r['planted']} planted defects, {r['false_alarms']} false alarms on clean files, {r['maybes']} maybe findings "
                  f"({r['model']}, {r['runs']} runs, rubric v{r['rubric']})")
            return 0
        if project:
            from .home import resolve
            from .spec import load_spec
            spec = load_spec(resolve(project) if resolve(project).endswith(".yaml") else os.path.join(resolve(project), "promo.yaml"))
            windows = project_windows(spec, a.line, a.mix)
            out = a.out or os.path.join(spec.build, "listen")
            title = f"{spec.name}: {'mix' if a.mix else 'VO stem'}"
        elif a.files:
            windows = [w for f in a.files for w in file_windows(f)]
            out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.files[0])), "listen")
            title = ", ".join(os.path.basename(f) for f in a.files)
        else:
            raise SystemExit("promo listen: give files, or -p PROJECT (see --help)")
        hear_locally(windows)
        if a.ear:
            ear(windows, _model(a), a.runs, a.max_usd)
        png = sheet(windows, os.path.join(out, "sheet.png"), title)
        report = dict(sheet=png, windows=[{k: v for k, v in w.items() if k not in ("x", "voice")} for w in windows])
        with open(os.path.join(out, "report.json"), "w") as f:
            json.dump(report, f, indent=1)
        if a.json:
            print(json.dumps(report, indent=1))
        else:
            _print(windows)
            print(f"sheet: {png}\nreport: {os.path.join(out, 'report.json')}")
        return 0
    except OR.OpenRouterError as e:
        print(f"promo listen: {e}", file=sys.stderr)
        return 2
