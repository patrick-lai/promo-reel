"""Mix + duck + master (port of build_mix.py, generic). `promo mix`.

Inputs: build/audio/events.json, build/audio/music-edit.wav, SFX wavs (assets), VO stems (build/vo/vo.json).
Spec (mix:): sr, bus_db {music, sfx, vo}, vo_line_lufs (each VO line levelled to it, then its own `db`; a `mute: true` line has no event, so no sound), duck {db, attack, release, pre, post, band}, fade_out, masters [...]
duck.band {lo, hi, db} (or `on` = 1000-5000 Hz, 12 dB): under speech the music's speech band dips by band.db, the rest by duck.db.
VO polish (promo/vo_polish.py): vo.polish / vo.lines[].polish on each VO line first, before its fx and levelling.
room (or {db, seed}): room tone, one seeded noise bed from the first VO line to the last at vo_line_lufs + db (default -60),
coloured like the takes' own pauses (pink when they are digital silence); it sits in the amb stem, so music-free lines never fall to silence.
SFX library entries may carry `duck_music: {db, dur}` (music dips under that SFX); `typing` entries use
{variants, gain_jitter [lo, hi], pan_jitter, seed} with ONE seeded rng consumed in event order (same as legacy).
Clip audio (events.json `clips`, promo/shot_audio.py): bus vo is placed in the vo stem and ducks music (+ sfx by duck.clip_sfx_db);
bus amb is gain only (bus_db.amb, own stem). mix-report.json `clips` lists each line's measured lufs / peak after its db.
Character effects (promo/audiofx.py): vo.fx / vo.lines[].fx on each VO line before its levelling (amount keyframes in film seconds),
music.fx on the music bed, mix.fx on the summed mix before mastering (the stems stay without it).
Outputs: build/audio/mix-<master>.wav, build/audio/stems/{music,sfx,vo[,amb]}.wav, build/audio/mix-report.json
"""
from __future__ import annotations

import json
import os

import numpy as np
import pyloudnorm as pyln
import soundfile as sf
from scipy.ndimage import minimum_filter1d
from scipy.signal import resample_poly

from . import audiofx
from . import bookends as BK
from . import vo as VO
from . import vo_polish
from .assets import asset_path, load_manifest
from .events import events_path
from .music import music_path
from .spec import SpecError


def db(v):
    return 10 ** (v / 20)


def load(p, sr_target):
    x, sr = sf.read(p, always_2d=True)
    x = x.astype(np.float64)
    if sr != sr_target:
        x = resample_poly(x, sr_target, sr, axis=0)
    if x.shape[1] == 1:
        x = np.repeat(x, 2, 1)
    return x


def smooth(gain, att, rel, SR):
    out = np.zeros_like(gain)
    s = 0.0
    a = np.exp(-1 / (att * SR))
    r = np.exp(-1 / (rel * SR))
    for i in range(0, len(gain), 48):          # 1 ms control rate
        tgt = gain[i]
        c = a if tgt > s else r
        s = tgt + (s - tgt) * (c ** 48)
        out[i:i + 48] = s
    return out


def _lufs(x, sr):
    from .shot_audio import lufs_of
    return lufs_of(x, sr)


def true_peak(x):
    up = resample_poly(x, 4, 1, axis=0)
    return 20 * np.log10(np.abs(up).max() + 1e-12)


def limiter(x, SR, ceil_db=-1.2, look=0.004, rel=0.08):
    """Look-ahead brickwall on a 4x-oversampled sidechain (true-peak aware)."""
    ceil = db(ceil_db)
    up = resample_poly(x, 4, 1, axis=0)
    pk = np.abs(up).max(1).reshape(-1, 4).max(1)[: len(x)]
    need = np.minimum(1.0, ceil / np.maximum(pk, 1e-9))
    L = int(look * SR)
    need = minimum_filter1d(need, size=2 * L + 1)                       # look-ahead window
    gain = np.ones_like(need)
    s = 1.0
    r = np.exp(-1 / (rel * SR))
    for i in range(len(need)):
        s = need[i] if need[i] < s else need[i] + (s - need[i]) * r
        gain[i] = s
    k = np.ones(L) / L                                                  # smooth attack (box filter over the look-ahead window)
    gain = np.minimum(gain, np.convolve(gain, k, mode="same"))
    return x * gain[:, None]


def master(x, SR, target, ceil=-1.2):
    m = pyln.Meter(SR)
    y = x.copy()
    for _ in range(12):
        L = m.integrated_loudness(y)
        y = y * db(target - L)
        y = limiter(y, SR, ceil)
        L2 = m.integrated_loudness(y)
        if abs(L2 - target) < 0.1 and true_peak(y) <= ceil + 0.15:
            break
    return y, m.integrated_loudness(y), true_peak(y)


def master_path(spec, name):
    return os.path.join(spec.audio_dir, f"mix-{name}.wav")


def duck_band(duck):
    """mix.duck.band -> {lo, hi, db} or None (full-band ducking only). `band: on` = 1-5 kHz down 12 dB under speech."""
    b = (duck or {}).get("band")
    if b in (None, False, "off"):
        return None
    b = {} if b is True or b == "on" else b
    if not isinstance(b, dict) or set(b) - {"lo", "hi", "db"}:
        raise SpecError(f"mix.duck.band: expected on, off or {{lo, hi, db}}, got {b!r}")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in b.values()):
        raise SpecError(f"mix.duck.band: lo, hi and db must be numbers, got {b!r}")
    out = {"lo": 1000.0, "hi": 5000.0, "db": 12.0, **{k: float(v) for k, v in b.items()}}
    if not 20 <= out["lo"] < out["hi"] <= 20000:
        raise SpecError(f"mix.duck.band: needs 20 <= lo < hi <= 20000 Hz, got lo {out['lo']:g}, hi {out['hi']:g}")
    return out


def room_cfg(cfg):
    """mix.room -> {db, seed} or None. `room: on` = a bed 60 dB under the VO level (mix.vo_line_lufs)."""
    r = (cfg or {}).get("room")
    if r in (None, False, "off"):
        return None
    r = {} if r is True or r == "on" else r
    if not isinstance(r, dict) or set(r) - {"db", "seed"}:
        raise SpecError(f"mix.room: expected on, off or {{db, seed}}, got {r!r}")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in r.values()):
        raise SpecError(f"mix.room: db and seed must be numbers, got {r!r}")
    if not -90 <= r.get("db", -60.0) <= -20:
        raise SpecError(f"mix.room: db is how far under the VO level the bed sits, -90..-20, got {r['db']:g}")
    return {"db": float(r.get("db", -60.0)), "seed": int(r.get("seed", 0))}


def room_tone(pauses, n, SR, level_db, seed):
    """`n` samples of seeded noise at `level_db` dBFS RMS, coloured like `pauses` ([(mono audio, sr)]: the takes' own quiet
    stretches), or pink when they hold no sound to take a colour from (a hosted voice's pauses are digital silence).
    Returns (bed, "takes" | "pink")."""
    from scipy import signal
    f = np.fft.rfftfreq(n, 1 / SR)
    heard = [(p, sr) for p, sr in pauses if len(p) >= 2048 and audiofx._rms_db(p) > -90]
    if sum(len(p) / sr for p, sr in heard) >= 0.3:
        power = np.zeros(len(f))
        for p, sr in heard:                                  # power-weighted average of each take's spectrum, on the bed's grid
            fp, pp = signal.welch(p, sr, nperseg=2048)
            power += np.interp(f, fp, pp, right=0.0) * len(p)
        mag, colour = np.sqrt(power), "takes"
    else:
        mag, colour = 1 / np.sqrt(np.maximum(f, 20.0)), "pink"
    y = np.fft.irfft(np.fft.rfft(np.random.default_rng(seed).standard_normal(n)) * mag, n)
    y = audiofx._filt(y, audiofx._sos("high", 80.0, 2, SR))
    return y * 10 ** ((level_db - audiofx._rms_db(y)) / 20), colour


def spec_problems(raw):
    """Errors in the mix's own keys that need no media: vo.polish values, mix.duck.band and mix.room. Kept out of Spec.validate, whose module
    every shot's render hash covers, so these keys never force a re-render."""
    errs = []
    for where, polish in vo_polish.spec_polish(raw):
        try:
            vo_polish.resolve(polish, where)
        except SpecError as e:
            errs.append(str(e))
    for check in (lambda: duck_band((raw.get("mix") or {}).get("duck")), lambda: room_cfg(raw.get("mix"))):
        try:
            check()
        except SpecError as e:
            errs.append(str(e))
    return errs


def vo_line_gain_db(cfg, line, measured_lufs):
    """Gain that levels a VO line to `mix.vo_line_lufs`, plus the line's own `db` offset (quiet and loud lines keep their dynamics)."""
    return cfg.get("vo_line_lufs", -16.0) - measured_lufs + float(line.get("db", 0.0) or 0.0)


def run(spec, force=False):
    cfg = spec.raw.get("mix", {})
    SR = int(cfg.get("sr", 48000))
    dur = spec.duration
    N = int(dur * SR)
    ev = json.load(open(events_path(spec)))
    man = load_manifest(spec)

    def place(buf, x, t, gain_db=0.0, pan=0.0):
        i = int(round(t * SR))
        x = x * db(gain_db)
        if pan:
            x = x * np.array([1 - max(pan, 0), 1 + min(pan, 0)])
        j = min(N, i + len(x))
        buf[i:j] += x[: j - i]

    music = load(music_path(spec), SR) if spec.raw.get("music") else np.zeros((N, 2))   # music bed is optional
    if len(music) != N:                      # equal for a well-formed spec; pad/trim so a rounded duration still mixes
        music = np.vstack([music, np.zeros((max(0, N - len(music)), 2))])[:N]
    music = audiofx.apply(music, SR, (spec.raw.get("music") or {}).get("fx"), where="music.fx")
    outro = BK.resolve(spec.raw)["outro"]
    if outro and spec.raw.get("music"):      # the outro fades music that is still playing: hold the last bars rather than let the bed end early
        music = BK.extend_tail(music, SR, N)
    sfx = np.zeros((N, 2))
    vo = np.zeros((N, 2))
    lib = spec.raw.get("sfx", {}).get("library", {})
    S = {name: load(asset_path(spec, e["asset"], man), SR) for name, e in lib.items() if e.get("asset")}
    typing = {name: e for name, e in lib.items() if e.get("variants")}
    rngs = {name: np.random.default_rng(e.get("seed", 0)) for name, e in typing.items()}
    log = []
    for e in ev["sfx"]:
        name, t, g = e["sfx"], e["t"], e.get("db", 0.0)
        if name in typing:
            ty, rng = typing[name], rngs[name]
            lo, hi = ty.get("gain_jitter", [-2.5, 1.0])
            pj = ty.get("pan_jitter", 0.15)
            variants = ty["variants"]
            for kt in e["times"]:
                place(sfx, S[variants[rng.integers(0, len(variants))]], kt, g + rng.uniform(lo, hi), pan=rng.uniform(-pj, pj))
            log.append((t, name, len(e["times"]), g))
            continue
        place(sfx, S[name], t, g, e.get("pan", 0.0))
        log.append((t, name, 1, g))
    # VO: level each line to vo_line_lufs, place at its event time
    vo_marks = []
    room, pauses = room_cfg(cfg), []
    meta = json.load(open(os.path.join(spec.vo_dir, "vo.json"))) if os.path.exists(os.path.join(spec.vo_dir, "vo.json")) else dict(lines=[])
    spec_lines = {str(x.get("id", x["shot"])): x for x in (spec.raw.get("vo") or {}).get("lines") or []}
    for line in meta["lines"]:
        t = ev["vo"].get(str(line.get("id", line["shot"])))
        if t is None:
            continue
        # chain per line: level (gain) at the file's own rate -> resample to the mix rate (float, no clipping even
        # for full-scale Kokoro output) -> the master's true-peak limiter (4x oversampled) at the master ceiling
        x, sr0 = sf.read(os.path.join(spec.vo_dir, line["file"]), always_2d=True)
        x = x.astype(np.float64)
        lid = str(line.get("id", line["shot"]))
        if room:                                     # the take's own pauses colour the room tone; trim's edge fades stay out
            m, dur0 = x.mean(1), len(x) / sr0
            pauses += [(m[int((a + 0.02) * sr0): int((b - 0.02) * sr0)], sr0) for a, b in VO.silences(m, sr0) if a > 0.05 and b < dur0 - 0.05]
        x = vo_polish.apply(x, sr0, vo_polish.line_polish(spec.raw, lid), where=f"vo line {lid} polish")
        x = audiofx.apply(x, sr0, audiofx.line_fx(spec.raw, lid), t0=t, where=f"vo line {lid} fx")
        meter = pyln.Meter(sr0)
        L = meter.integrated_loudness(x) if len(x) > sr0 * 0.5 else -20
        x = x * db(vo_line_gain_db(cfg, spec_lines.get(lid) or line, L))
        if sr0 != SR:
            x = resample_poly(x, SR, sr0, axis=0)
        if x.shape[1] == 1:
            x = np.repeat(x, 2, 1)
        place(vo, x, t)
        vo_marks.append((t, t + len(x) / SR, str(line.get("id", line["shot"])), line["text"]))
    # clip audio (shot `audio:` lines, promo/shot_audio.py): bus vo = like a VO line (ducks music + sfx, vo stem), bus amb = gain only
    amb = np.zeros((N, 2))
    clip_marks, clip_log = [], []
    for c in ev.get("clips", []):
        x = load(os.path.join(spec.build, c["file"]), SR) * db(c.get("db", 0.0))
        if c["bus"] == "amb":
            place(amb, x, c["t"])
        else:
            place(vo, x, c["t"])
            clip_marks.append((c["t"], c["t"] + len(x) / SR))
        clip_log.append(dict(id=c["id"], shot=c.get("shot"), bus=c["bus"], t=c["t"], dur=round(len(x) / SR, 3), db=c.get("db", 0.0),
                             lufs=round(float(_lufs(x[:, :1], SR)), 2), peak_db=round(float(20 * np.log10(np.abs(x).max() + 1e-12)), 2)))
    room_log = None
    if room and vo_marks:
        # one continuous bed from just before the first line to just after the last: the lines are trimmed tight, so most of the
        # quiet sits between lines, and a bed per line would switch on and off at every line edge
        a, b = int(max(0.0, min(m[0] for m in vo_marks) - 0.3) * SR), int(min(dur, max(m[1] for m in vo_marks) + 0.5) * SR)
        level = cfg.get("vo_line_lufs", -16.0) + room["db"]
        bed, colour = room_tone(pauses, b - a, SR, level, room["seed"])
        k = min(int(0.4 * SR), (b - a) // 2)
        ramp = 0.5 - 0.5 * np.cos(np.linspace(0, np.pi, k))
        bed[:k] *= ramp
        bed[len(bed) - k:] *= ramp[::-1]
        amb[a:b] += bed[:, None]
        room_log = dict(db=room["db"], level_dbfs=round(level, 1), colour=colour, span=[round(a / SR, 3), round(b / SR, 3)])
    # music ducking under VO (and under SFX with duck_music)
    dk = cfg.get("duck", {})
    duck_db, att, rel = dk.get("db", 7.0), dk.get("attack", 0.12), dk.get("release", 0.35)
    pre, post = dk.get("pre", 0.12), dk.get("post", 0.1)
    band = duck_band(dk)
    g = np.zeros(N)
    gb = np.zeros(N)                                 # the speech band's extra duck under speech (mix.duck.band)
    gs = np.zeros(N)                                 # sfx duck under clip dialogue (mix.duck.clip_sfx_db, default 4 dB)
    for t0, t1, *_ in vo_marks + clip_marks:
        g[int(max(0, t0 - pre) * SR): int(min(dur, t1 + post) * SR)] = duck_db
        if band:
            gb[int(max(0, t0 - pre) * SR): int(min(dur, t1 + post) * SR)] = band["db"]
    for t0, t1 in clip_marks:
        gs[int(max(0, t0 - pre) * SR): int(min(dur, t1 + post) * SR)] = dk.get("clip_sfx_db", 4.0)
    for e in ev["sfx"]:
        d = (lib.get(e["sfx"]) or {}).get("duck_music")
        if d:
            a, b = int(e["t"] * SR), int((e["t"] + d["dur"]) * SR)
            g[a:b] = np.maximum(g[a:b], d["db"])
    duck = smooth(g, att, rel, SR)
    music_d = music * db(-duck)[:, None]
    if band:                                         # the 1-5 kHz part, where words live, dips further; the bass and the sheen stay
        mb = audiofx._filt(music, audiofx._sos("band", [band["lo"], band["hi"]], 4, SR))     # steep edges: the whole band dips by band.db
        music_d = (music - mb) * db(-duck)[:, None] + mb * db(-smooth(np.maximum(g, gb), att, rel, SR))[:, None]
    if clip_marks:
        sfx = sfx * db(-smooth(gs, att, rel, SR))[:, None]
    BUS = {"music": -5.0, "sfx": -8.0, "vo": 1.5, "amb": 0.0}
    BUS.update(cfg.get("bus_db", {}))
    mix = music_d * db(BUS["music"]) + sfx * db(BUS["sfx"]) + vo * db(BUS["vo"]) + amb * db(BUS["amb"])
    mix = audiofx.apply(mix, SR, cfg.get("fx"), where="mix.fx")
    sd = os.path.join(spec.audio_dir, "stems")
    os.makedirs(sd, exist_ok=True)
    stems = [("music", music_d), ("sfx", sfx * db(BUS["sfx"])), ("vo", vo * db(BUS["vo"]))]
    if room_log or any(c["bus"] == "amb" for c in ev.get("clips", [])):
        stems.append(("amb", amb * db(BUS["amb"])))
    for nm, x in stems:
        sf.write(os.path.join(sd, f"{nm}.wav"), x.astype(np.float32), SR, subtype="FLOAT")
    out = {}
    fo = cfg.get("fade_out")
    fade, ease = (float(fo.get("s", fo.get("dur", 0.03))), fo.get("ease")) if isinstance(fo, dict) else (None if fo is None else float(fo), None)
    if outro:                                # the picture's fade (promo/bookends.py): the same length and the same curve
        fade, ease = fade if fade is not None else outro["fade_s"], ease or outro["ease"]
    fade = 0.03 if fade is None else fade
    for m in spec.masters:
        y, L, tp = master(mix, SR, m["lufs"], m["ceiling"])
        if ease:
            y *= BK.fade_out_array(N, SR, fade, ease)[:, None]
        else:
            f0 = int(round(dur - fade, 6) * SR)
            y[f0:] *= np.linspace(1, 0, N - f0)[:, None]
        sf.write(master_path(spec, m["name"]), y.astype(np.float32), SR, subtype="FLOAT")
        out[m["name"]] = dict(lufs=round(float(L), 2), dbtp=round(float(tp), 2))
        print("master", m["name"], out[m["name"]], flush=True)
    with open(os.path.join(spec.audio_dir, "mix-report.json"), "w") as f:
        json.dump(dict(master=out, sfx=log, vo=vo_marks, bus_db=BUS, duck_db=duck_db, **(dict(duck_band=band) if band else {}), **(dict(room=room_log) if room_log else {}),
                       **(dict(clips=clip_log) if clip_log else {})), f, indent=1)
    return out
