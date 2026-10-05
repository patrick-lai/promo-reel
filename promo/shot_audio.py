"""Clip audio in the mix: a shot plays the soundtrack of a (generated) footage clip like a VO line. `promo clip-audio`.

Generic over shot types (cinema, screen, ...): reads `shot.get("audio")`, a dict or a list of dicts:

    audio: {from: source | plate | <clip id>,   source = the shot's `source` (or first seg's); plate = the shot's `plate`
                                                clip id (else look.backdrop.plate); anything else = a footage clip id
            t_in: <clip s>,   default: the shot's t_in (source) / plate_t_in (plate, else backdrop t) / 0 (clip id)
            dur: <clip s>,    default: the shot duration (minus `at`, times `speed`); shorter than the clip = trim
            at: <shot-local s> default 0,   db: 0.0 (extra gain after the loudness normalisation)
            lufs: -16.0,      integrated loudness of the line before `db`
            bus: vo | amb,    vo (default) = ducks music (and sfx by mix.duck.clip_sfx_db) and lands in the vo stem;
                              amb = room tone: gain only, no duck, its own `amb` stem, mix.bus_db.amb (default 0)
            fade: {in: 0.03, out: 0.08},  speed: 1.0 (pitch-preserving tempo),  id: <line id>,
            text: <what is said>, asr_aliases: {heard: script}   (QA read-back, same semantics as vo lines)}

Step output: build/vo/<shot>-<n>-clip.wav (build/audio/amb/ for bus amb), 48 kHz mono float32, normalised to `lufs`,
trimmed, faded. n = index of the line in the shot's list (0-based). events.json gets `clips` (global start time, bus, db);
`promo mix` places them. A clip without an audio stream (e.g. a UI screen recording) is an error naming the clip.
"""
from __future__ import annotations

import json
import os
import subprocess

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

from . import footage as FT
from .spec import SpecError

SR = 48000
BUSES = ("vo", "amb")
KEYS = {"from", "t_in", "dur", "at", "db", "lufs", "bus", "fade", "speed", "id", "text", "asr_aliases"}
OVERLAP_WARN = 0.25


class ShotAudioError(SpecError):
    pass


def shot_lines(shot):
    a = shot.get("audio")
    if not a:
        return []
    return [a] if isinstance(a, dict) else list(a)


def _clip_ref(spec, shot, a):
    """(clip id, default t_in) of an audio line's `from`."""
    src = a.get("from", "source")
    segs = shot.get("segs") or []
    if src == "source":
        cid = shot.get("source") or (segs[0].get("source") if segs else None)
        t0 = shot.get("t_in", segs[0].get("t_in", 0.0) if segs else 0.0)
        if not cid:
            raise ShotAudioError(f"shot {shot.id}: audio.from=source but the shot has no `source` clip")
        return str(cid), float(t0 or 0.0)
    if src == "plate":
        cid = shot.get("plate") if isinstance(shot.get("plate"), str) else None
        t0 = shot.get("plate_t_in")
        if not cid:
            try:
                from .shots import cinema as CN
                bd = CN.backdrop_cfg(CN.look_of(spec, shot))
                cid, t0 = bd["plate"], (bd["t"] if t0 is None else t0)
            except Exception:  # noqa: BLE001
                cid = None
        if not cid:
            raise ShotAudioError(f"shot {shot.id}: audio.from=plate but the shot has no `plate` clip (or look.backdrop.plate)")
        return str(cid), float(t0 or 0.0)
    return str(src), 0.0


def lines(spec, shots=None):
    """Resolved audio lines [{id, shot, n, bus, clip, t_in, dur, out_dur, at, t, db, lufs, fade, speed, text, asr_aliases, file}]
    in timeline order. Pure (no media access): `t` is the global start, `file` the build path of the rendered WAV."""
    out = []
    for shot in (shots if shots is not None else spec.shots):
        for n, a in enumerate(shot_lines(shot)):
            if not isinstance(a, dict):
                raise ShotAudioError(f"shot {shot.id}: audio[{n}] must be a mapping")
            bad = sorted(set(a) - KEYS)
            if bad:
                raise ShotAudioError(f"shot {shot.id}: unknown audio keys {bad} (known: {sorted(KEYS)})")
            bus = a.get("bus", "vo")
            if bus not in BUSES:
                raise ShotAudioError(f"shot {shot.id}: audio.bus must be one of {BUSES}, got {bus!r}")
            cid, t_def = _clip_ref(spec, shot, a)
            at = float(a.get("at", 0.0))
            speed = float(a.get("speed", 1.0))
            if speed <= 0:
                raise ShotAudioError(f"shot {shot.id}: audio.speed must be > 0")
            dur = float(a["dur"]) if a.get("dur") is not None else max(0.0, shot.dur - at) * speed
            fade = a.get("fade") or {}
            name = f"{shot.id}-{n}-clip.wav"
            sub = os.path.join(spec.audio_dir, "amb") if bus == "amb" else spec.vo_dir
            out.append(dict(id=str(a.get("id", f"{shot.id}-{n}-clip")), shot=shot.id, n=n, bus=bus, clip=cid,
                            t_in=float(a["t_in"]) if a.get("t_in") is not None else t_def, dur=dur, out_dur=dur / speed, at=at,
                            t=spec.g(shot.id, at), db=float(a.get("db", 0.0)), lufs=float(a.get("lufs", -16.0)),
                            fade=dict(**{"in": float(fade.get("in", 0.03)), "out": float(fade.get("out", 0.08))}), speed=speed,
                            text=a.get("text"), asr_aliases=a.get("asr_aliases") or {}, file=os.path.join(sub, name)))
    return out


def has_lines(spec):
    return any(shot_lines(s) for s in spec.shots)


def event_rows(spec):
    """The `clips` entries of events.json: global start time + bus + gain; file relative to the build dir."""
    return [dict(id=l["id"], shot=l["shot"], t=l["t"], bus=l["bus"], db=l["db"], lufs=l["lufs"],
                 file=os.path.relpath(l["file"], spec.build), text=l["text"]) for l in lines(spec)]


# ---------------------------------------------------------------- media
_PROBE = {}


def audio_info(path):
    """{'audio': bool, 'duration': s|None} via ffprobe (cached per path+mtime)."""
    st = os.stat(path)
    k = (path, st.st_size, st.st_mtime_ns)
    if k not in _PROBE:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index:format=duration", "-of", "json", path],
                           capture_output=True, text=True)
        j = json.loads(r.stdout or "{}")
        d = (j.get("format") or {}).get("duration")
        _PROBE[k] = dict(audio=bool(j.get("streams")), duration=float(d) if d else None)
    return _PROBE[k]


def clip_file(spec, l):
    """Path of the line's clip, with clear errors: unknown id, missing file, no audio stream."""
    try:
        p = FT.clip_path(spec, l["clip"])
    except SpecError as e:
        raise ShotAudioError(f"shot {l['shot']} audio[{l['n']}]: {e}")
    if not os.path.exists(p):
        raise ShotAudioError(f"shot {l['shot']} audio[{l['n']}]: clip {l['clip']!r} file not found: {p}")
    if not audio_info(p)["audio"]:
        raise ShotAudioError(f"shot {l['shot']} audio[{l['n']}]: clip {l['clip']!r} has no audio stream ({p}); "
                             "UI screen recordings are silent; use a generated clip with sound, or drop the audio key")
    return p


def lufs_of(x, sr):
    """Integrated loudness of a mono/stereo float array; blocks shorter than 0.4 s use the RMS (K-weighting needs 400 ms)."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1:
        x = x[:, None]
    if len(x) >= int(0.4 * sr) + 1:
        return float(pyln.Meter(sr).integrated_loudness(x))
    rms = float(np.sqrt(np.mean(x ** 2) + 1e-20))
    return 20 * np.log10(rms) - 0.691


def peak_db(x):
    return float(20 * np.log10(np.abs(x).max() + 1e-12))


def _atempo(speed):
    f, s = [], speed
    while s > 2.0:
        f.append("atempo=2.0")
        s /= 2.0
    while s < 0.5:
        f.append("atempo=0.5")
        s /= 0.5
    f.append(f"atempo={s:.6f}")
    return ",".join(f)


def extract(path, t_in, dur, speed=1.0, sr=SR):
    """Mono float32 [t_in, t_in+dur) of the clip's first audio stream at `sr` (ffmpeg), tempo-changed by `speed`."""
    cmd = ["ffmpeg", "-v", "error", "-nostdin", "-ss", f"{t_in:.4f}", "-t", f"{dur:.4f}", "-i", path, "-map", "0:a:0", "-vn", "-ac", "1", "-ar", str(sr)]
    if abs(speed - 1.0) > 1e-9:
        cmd += ["-af", _atempo(speed)]
    cmd += ["-f", "f32le", "-"]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise ShotAudioError(f"ffmpeg could not read the audio of {path}: {r.stderr.decode(errors='replace')[-300:]}")
    return np.frombuffer(r.stdout, dtype="<f4").astype(np.float64)


def process(x, sr, lufs, fade_in, fade_out):
    """Loudness-normalise to `lufs` (per line, like mix.vo_line_lufs) and apply linear fades."""
    L = lufs_of(x, sr)
    if not np.isfinite(L) or L < -70:
        raise ShotAudioError("the extracted window is silent")
    x = x * 10 ** ((lufs - L) / 20)
    n = len(x)
    ni, no = min(n, int(round(fade_in * sr))), min(n, int(round(fade_out * sr)))
    if ni > 0:
        x[:ni] *= np.linspace(0.0, 1.0, ni)
    if no > 0:
        x[n - no:] *= np.linspace(1.0, 0.0, no)
    return x


def render_line(spec, l):
    p = clip_file(spec, l)
    info = audio_info(p)
    if info["duration"] is not None and l["t_in"] >= info["duration"] - 1e-3:
        raise ShotAudioError(f"shot {l['shot']} audio[{l['n']}]: t_in {l['t_in']:.2f}s is past the end of clip {l['clip']!r} ({info['duration']:.2f}s)")
    x = extract(p, l["t_in"], l["dur"], l["speed"])
    if len(x) < int(0.05 * SR):
        raise ShotAudioError(f"shot {l['shot']} audio[{l['n']}]: clip {l['clip']!r} gave {len(x) / SR:.3f}s of audio at t_in={l['t_in']:.2f}")
    try:
        x = process(x, SR, l["lufs"], l["fade"]["in"], l["fade"]["out"])
    except ShotAudioError as e:
        raise ShotAudioError(f"shot {l['shot']} audio[{l['n']}]: clip {l['clip']!r}: {e} (t_in={l['t_in']:.2f}, dur={l['dur']:.2f})")
    os.makedirs(os.path.dirname(l["file"]), exist_ok=True)
    sf.write(l["file"], x.astype(np.float32), SR, subtype="FLOAT")
    return len(x) / SR


def run(spec, force=False):
    res = []
    for l in lines(spec):
        d = render_line(spec, l)
        print("clip-audio", l["id"], l["bus"], f"{d:.2f}s", "from", l["clip"], flush=True)
        res.append(dict(id=l["id"], dur=round(d, 3), file=l["file"]))
    return res


def outputs(spec):
    return [l["file"] for l in lines(spec)]


def digest_parts(spec):
    """What changes the rendered WAVs: clip bytes + window + loudness + fades + speed (not `at` / `db` / `text`: those only move or
    regain the line in the mix, which has its own digest through events.json)."""
    from .cache import file_sig
    parts = []
    for l in lines(spec):
        try:
            sig = file_sig(FT.clip_path(spec, l["clip"]))
        except SpecError:
            sig = "unknown-clip"
        parts.append([l["id"], l["file"], l["clip"], sig, l["t_in"], l["dur"], l["lufs"], l["fade"], l["speed"]])
    return parts


def audio_keys_digest(spec):
    """Every shot's raw `audio` entries (for stale checks of anything that depends on them)."""
    return [[s.id, s.get("audio")] for s in spec.shots if s.get("audio")]


# ---------------------------------------------------------------- QA gates
def _line_spans(spec):
    """[(start, end, label)] of every vo-bus line: clip lines (real WAV length when rendered) and VO lines (vo.json)."""
    spans = []
    for l in lines(spec):
        if l["bus"] != "vo":
            continue
        d = l["out_dur"]
        if os.path.exists(l["file"]):
            try:
                d = sf.info(l["file"]).duration
            except Exception:  # noqa: BLE001
                pass
        spans.append((l["t"], l["t"] + d, f"clip {l['id']}"))
    vj = os.path.join(spec.vo_dir, "vo.json")
    if os.path.exists(vj):
        ev_path = os.path.join(spec.audio_dir, "events.json")
        try:
            vt = json.load(open(ev_path)).get("vo", {}) if os.path.exists(ev_path) else {}
            for m in json.load(open(vj))["lines"]:
                k = str(m.get("id", m["shot"]))
                if k in vt:
                    spans.append((vt[k], vt[k] + float(m["dur"]), f"vo {k}"))
        except Exception:  # noqa: BLE001
            pass
    return sorted(spans)


def check(spec, stamps=None, qa=None):
    """Gate rows [(gate, status, msg)]: `shot-audio` (FAIL: referenced clip missing / without audio; WARN: vo-bus lines overlapping
    > 0.25 s) and `shot-audio-asr` (clip lines with `text` read back through whisper when qa.vo_max_wer is set)."""
    try:
        ls = lines(spec)
    except SpecError as e:
        return [("shot-audio", "FAIL", str(e))]
    if not ls:
        return [("shot-audio", "PASS", "no shot audio")]
    rows, bad = [], []
    for l in ls:
        try:
            clip_file(spec, l)
        except SpecError as e:
            bad.append(str(e))
    warn = []
    sp = _line_spans(spec)
    for (a0, a1, an), (b0, b1, bn) in zip(sp, sp[1:]):
        ov = min(a1, b1) - b0
        if ov > OVERLAP_WARN:
            warn.append(f"{an} and {bn} overlap {ov:.2f}s on the vo bus at {b0:.2f}s (dialogue overlaps are usually mistakes)")
    if bad:
        rows.append(("shot-audio", "FAIL", "; ".join(bad)))
    elif warn:
        rows.append(("shot-audio", "WARN", "; ".join(warn)))
    else:
        rows.append(("shot-audio", "PASS", f"{len(ls)} audio lines: clips present with audio, no vo-bus overlaps > {OVERLAP_WARN}s"))
    qa = qa if qa is not None else spec.qa
    maxw = qa.get("vo_max_wer")
    if maxw is None or bad:
        return rows
    todo = [l for l in ls if l["text"]]
    skipped = [l["id"] for l in ls if not l["text"]]
    if not todo:
        rows.append(("shot-audio-asr", "PASS", f"skipped: no audio line has `text` ({len(skipped)} line(s) without `text`)"))
        return rows
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        rows.append(("shot-audio-asr", "WARN", "skipped: faster-whisper not installed"))
        return rows
    import hashlib
    import re

    from .check import norm_words, transcribe, wer
    model = qa.get("asr_model", "small.en")
    fails = []
    for l in todo:
        if not os.path.exists(l["file"]):
            fails.append(f"{l['id']}: no rendered audio (run `promo clip-audio`)")
            continue
        h = hashlib.sha256(open(l["file"], "rb").read()).hexdigest() + model
        st = stamps.get(f"asr_clip_{l['id']}") if stamps else None
        if st and st.get("digest") == h:
            txt = st["text"]
        else:
            txt = transcribe(l["file"], model)
            if stamps:
                stamps.write(f"asr_clip_{l['id']}", h, text=txt)
        hyp = txt
        for k, v in {**(qa.get("asr_aliases") or {}), **l["asr_aliases"]}.items():
            hyp = re.sub(re.escape(k), v, hyp, flags=re.I)
        w = wer(norm_words(l["text"]), norm_words(hyp))
        if w > maxw:
            fails.append(f"{l['id']}: WER {w:.2f} (heard {txt!r})")
    note = f"; {len(skipped)} line(s) without `text` skipped" if skipped else ""
    rows.append(("shot-audio-asr", "FAIL" if fails else "PASS", "; ".join(fails) if fails else f"{len(todo)} clip lines match their text (WER <= {maxw}){note}"))
    return rows
