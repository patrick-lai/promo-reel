"""Character effects for VO, music and the whole mix: old radio, tape, telephone, vinyl. `promo fx`.

Spec (any of these; a preset name, or a mapping):
  vo:    {fx: vintage, lines: [{..., fx: {preset: radio, amount: 0.6}}]}   line `fx` replaces vo.fx; `fx: none` = a dry line
  music: {fx: tape}
  mix:   {fx: {preset: vintage, amount: [[0, 1], [24, 0.7], [35, 0]]}}      the summed mix (music + sfx + vo) before mastering

  fx: {preset: radio | tape | vintage | telephone | vinyl | crackle,   or  chain: [{type: hp, hz: 300}, ...] (a custom chain)
       amount: 0..1, or keyframes [[t, v], ...] in film seconds (in file seconds for `promo fx apply`),
       <stage name>: {param: value}   overrides one stage of the preset, e.g. hiss: {db: -44}, tube: {db: 9},
       seed: 0   the noise and wow pattern}

The character comes from the signal itself (band-limit, speaker resonance, tube or tape saturation, compression, wow and flutter);
noise is quiet, set relative to the program loudness (default hiss 50-60 dB under it), so the result never reads as static over a
clean voice. Filters are zero-phase so a partial `amount` blends dry and processed sound without comb filtering, and wow and flutter
move the whole signal (scaled by amount) instead of being mixed against a dry copy, which would flange. The processed sound is
matched to the input's loudness. Noise is seeded: the same spec renders the same samples.
"""
from __future__ import annotations

import copy
import os

import numpy as np
from scipy import signal
from scipy.signal import resample_poly

from .spec import SpecError

# stage type -> its parameters and their defaults
STAGES = {
    "hp": dict(hz=80.0, order=2),
    "lp": dict(hz=8000.0, order=2),
    "peak": dict(hz=1000.0, q=1.0, db=0.0),
    "drive": dict(db=0.0, bias=0.0),                                       # db = drive into the curve (0 = peaks just bend); bias > 0 = even harmonics (tube)
    "compress": dict(threshold=-12.0, ratio=3.0, attack=0.005, release=0.12),   # threshold in dB under the program's loud level
    "wow": dict(wow_hz=0.6, wow=0.0015, flutter_hz=6.5, flutter=0.0004),   # speed deviation as a fraction (0.0015 = 0.15 %)
    "hiss": dict(db=-55.0, tilt=0.0),                                      # dB under the program loudness; tilt > 0 = brighter
    "hum": dict(db=-62.0, hz=60.0),
    "crackle": dict(db=-46.0, rate=8.0),                                   # ticks per second (with an occasional pop), RMS dB under the program
}

PRESETS = {
    "radio": [  # a small tube set: narrow band, boxy cabinet, a speaker cone resonance, warm even-harmonic drive
        dict(name="hiss", type="hiss", db=-52.0, tilt=0.3),
        dict(name="hum", type="hum", db=-64.0, hz=60.0),
        dict(name="coupling", type="hp", hz=150.0, order=1),
        dict(name="tube", type="drive", db=6.0, bias=0.25),
        dict(name="comp", type="compress", threshold=-8.0, ratio=3.0, attack=0.004, release=0.15),
        # the speaker comes after the amp, so it also removes the harmonics the tube adds above the band
        dict(name="low_cut", type="hp", hz=300.0, order=3),
        dict(name="high_cut", type="lp", hz=3400.0, order=3),
        dict(name="cabinet", type="peak", hz=550.0, q=1.4, db=2.5),
        dict(name="speaker", type="peak", hz=1600.0, q=1.1, db=4.5),
    ],
    "tape": [  # a cassette: wow and flutter, head bump, soft top end, tape compression, a little hiss
        dict(name="wow", type="wow", wow_hz=0.55, wow=0.0018, flutter_hz=6.5, flutter=0.0005),
        dict(name="head_bump", type="peak", hz=90.0, q=0.9, db=2.5),
        dict(name="low_cut", type="hp", hz=35.0, order=2),
        dict(name="high_cut", type="lp", hz=9500.0, order=1),
        dict(name="tape", type="drive", db=2.0, bias=0.05),
        dict(name="hiss", type="hiss", db=-56.0, tilt=0.6),
    ],
    "telephone": [
        dict(name="drive", type="drive", db=6.0, bias=0.1),
        dict(name="comp", type="compress", threshold=-10.0, ratio=4.0, attack=0.003, release=0.1),
        dict(name="low_cut", type="hp", hz=420.0, order=4),
        dict(name="high_cut", type="lp", hz=3100.0, order=4),
        dict(name="presence", type="peak", hz=1900.0, q=1.2, db=3.0),
    ],
    "vinyl": [
        dict(name="wow", type="wow", wow_hz=0.55, wow=0.0008, flutter_hz=8.0, flutter=0.0002),
        dict(name="low_cut", type="hp", hz=45.0, order=2),
        dict(name="high_cut", type="lp", hz=11000.0, order=1),
        dict(name="warmth", type="peak", hz=200.0, q=0.8, db=1.5),
        dict(name="drive", type="drive", db=0.0, bias=0.05),
        dict(name="crackle", type="crackle", db=-42.0, rate=10.0),
        dict(name="hiss", type="hiss", db=-60.0, tilt=0.2),
        dict(name="hum", type="hum", db=-68.0, hz=60.0),
    ],
}
PRESETS["crackle"] = [  # only the surface: a light, steady crackle and a faint hiss, the tone untouched; on music or mix it never stops
    dict(name="crackle", type="crackle", db=-46.0, rate=9.0),
    dict(name="hiss", type="hiss", db=-62.0, tilt=0.3),
]
# an old radio broadcast heard off a cassette: the radio's tone, then the tape's movement and softness; hiss once (the radio's), not twice
PRESETS["vintage"] = [dict(PRESETS["tape"][0])] + copy.deepcopy(PRESETS["radio"]) + [
    dict(name="tape_high_cut", type="lp", hz=3000.0, order=1),
    dict(name="tape", type="drive", db=2.0, bias=0.05),
]

DESCRIPTIONS = {
    "radio": "small tube radio: 300-3400 Hz, boxy cabinet, speaker resonance, warm drive, quiet hiss + hum",
    "tape": "cassette: wow and flutter, head bump, soft top, tape saturation, quiet hiss",
    "vintage": "an old radio heard off a tape: the radio's tone + the tape's wow and softness",
    "telephone": "phone line: 420-3100 Hz, hard compression, a little grit, no noise",
    "vinyl": "record: soft top, warmth, light wow, crackle, faint hiss",
    "crackle": "only a light, steady vintage crackle + faint hiss; the tone is untouched (on music or mix: a bed that never stops)",
}


def _err(where, msg):
    return SpecError(f"{where}: {msg}")


def resolve(fx, where="fx"):
    """The spec value of an `fx` key -> {chain: [stages], amount} or None (no effect). Raises SpecError on anything unknown."""
    if fx is None or fx is False or fx == "none":
        return None
    if isinstance(fx, str):
        fx = {"preset": fx}
    if not isinstance(fx, dict):
        raise _err(where, f"must be a preset name or a mapping, got {fx!r}")
    if ("preset" in fx) == ("chain" in fx):
        raise _err(where, f"give exactly one of `preset` (one of {sorted(PRESETS)}) or `chain`")
    if "preset" in fx:
        if fx["preset"] not in PRESETS:
            raise _err(where, f"unknown preset {fx['preset']!r}; presets: {', '.join(sorted(PRESETS))}")
        chain = copy.deepcopy(PRESETS[fx["preset"]])
        names = {s["name"]: s for s in chain}
        for k, v in fx.items():
            if k in ("preset", "amount", "seed"):
                continue
            if k not in names:
                raise _err(where, f"{k!r} is not a stage of {fx['preset']}; stages: {', '.join(names)}")
            if not isinstance(v, dict):
                raise _err(where, f"{k} must be a mapping of parameters, e.g. {{db: -44}}")
            names[k].update(v)
    else:
        if not isinstance(fx["chain"], list) or not fx["chain"]:
            raise _err(where, "`chain` must be a non-empty list of stages")
        extra = sorted(set(fx) - {"chain", "amount", "seed"})
        if extra:
            raise _err(where, f"unknown keys {extra} next to `chain`")
        chain = [dict(s, name=s.get("name", f"{i}-{s.get('type')}")) if isinstance(s, dict) else s for i, s in enumerate(fx["chain"])]
    for s in chain:
        if not isinstance(s, dict) or s.get("type") not in STAGES:
            raise _err(where, f"stage {s!r}: `type` must be one of {', '.join(STAGES)}")
        bad = sorted(set(s) - set(STAGES[s["type"]]) - {"type", "name"})
        if bad:
            raise _err(where, f"stage {s['name']} ({s['type']}): unknown parameters {bad}; known: {', '.join(STAGES[s['type']])}")
        for k, v in s.items():
            if k not in ("type", "name") and not isinstance(v, (int, float)):
                raise _err(where, f"stage {s['name']}: {k} must be a number, got {v!r}")
    amount = fx.get("amount", 1.0)
    if isinstance(amount, (int, float)):
        if not 0 <= amount <= 1:
            raise _err(where, f"amount must be between 0 and 1, got {amount}")
    elif not (isinstance(amount, list) and amount and all(isinstance(k, (list, tuple)) and len(k) == 2
                                                                and all(isinstance(v, (int, float)) for v in k) and 0 <= k[1] <= 1 for k in amount)):
        raise _err(where, "amount must be a number 0..1 or keyframes [[t, value], ...] with values 0..1")
    return dict(chain=[{k: (float(v) if k not in ("type", "name") else v) for k, v in {**STAGES[s["type"]], **s}.items()} for s in chain],
                amount=amount, seed=int(fx.get("seed", 0)))


def amount_curve(amount, n, sr, t0=0.0):
    """Per-sample amount for a stream that starts at `t0` seconds (keyframes are absolute, held flat outside their range)."""
    if isinstance(amount, (int, float)):
        return np.full(n, float(amount))
    ks = sorted(amount, key=lambda k: k[0])
    return np.interp(t0 + np.arange(n) / sr, [float(k[0]) for k in ks], [float(k[1]) for k in ks])


# ---------------------------------------------------------------- stages
def _rms_db(x):
    return 10 * np.log10(np.mean(x ** 2) + 1e-20)


def _program_db(x, sr):
    """Loudness of the program in dB RMS over its loud parts (a voice's pauses do not pull the reference down)."""
    hop = max(1, int(0.05 * sr))
    m = x.mean(1)
    n = len(m) // hop
    if n < 2:
        return _rms_db(m)
    blk = 10 * np.log10(np.mean(m[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-20)
    loud = blk[blk > blk.max() - 20]
    return float(10 * np.log10(np.mean(10 ** (loud / 10))))


def _sos(kind, hz, order, sr):
    hz = [min(float(f), 0.45 * sr) for f in hz] if isinstance(hz, list) else min(float(hz), 0.45 * sr)
    return signal.butter(int(order), hz, btype=kind, fs=sr, output="sos")


def _peak_sos(hz, q, gain_db, sr):
    """RBJ peaking biquad."""
    a = 10 ** (gain_db / 40)
    w = 2 * np.pi * hz / sr
    al = np.sin(w) / (2 * q)
    b = [1 + al * a, -2 * np.cos(w), 1 - al * a]
    d = [1 + al / a, -2 * np.cos(w), 1 - al / a]
    return np.array([[b[0] / d[0], b[1] / d[0], b[2] / d[0], 1.0, d[1] / d[0], d[2] / d[0]]])


def _filt(x, sos):
    return signal.sosfiltfilt(sos, x, axis=0) if len(x) > 3 * 6 * len(sos) else x


def _drive(x, s, ref_db, sr):
    """Oversampled tanh saturation, level-independent: at db 0 the program's loud RMS sits at 0.3 on the curve (peaks just bend),
    each dB of drive pushes it further in; the result is scaled back to the input's level."""
    k = 0.3 * 10 ** ((s["db"] - ref_db) / 20)
    up = resample_poly(x, 4, 1, axis=0)
    b = s["bias"]
    y = (np.tanh(up * k + b) - np.tanh(b)) / k
    y = resample_poly(y, 1, 4, axis=0)[: len(x)]
    return _filt(y, _sos("high", 20.0, 2, sr)) if b else y              # the bias leaves an offset that follows the envelope


def _compress(x, s, ref_db, sr):
    """Feed-forward compressor on a 1 ms control rate; threshold relative to the program's loud level."""
    hop = max(1, int(0.001 * sr))
    n = -(-len(x) // hop)
    pad = np.zeros((n * hop - len(x), x.shape[1]))
    lvl = 10 * np.log10(np.mean(np.vstack([x, pad]).reshape(n, hop, -1) ** 2, axis=(1, 2)) + 1e-20)
    thr = ref_db + s["threshold"]
    want = np.minimum(0.0, (thr - lvl) * (1 - 1 / s["ratio"]))         # gain reduction in dB (<= 0)
    ca, cr = np.exp(-1 / (s["attack"] * 1000)), np.exp(-1 / (s["release"] * 1000))
    g = np.zeros(n)
    st = 0.0
    for i, w in enumerate(want):
        c = ca if w < st else cr
        st = w + (st - w) * c
        g[i] = st
    gain = np.repeat(10 ** (g / 20), hop)[: len(x)]
    return x * gain[:, None]


def _wow(x, s, amt, sr, rng):
    """Tape speed wander: a modulated read position. Depth scales with amount, so a partial amount is a gentler wow, never a flange."""
    t = np.arange(len(x)) / sr
    slow = signal.sosfiltfilt(_sos("low", 1.2, 2, sr), rng.standard_normal(len(x))) if len(x) > 64 else np.zeros(len(x))
    slow = slow - slow.mean()                                           # zero-mean, or its running sum would drift the timing
    slow = slow / (np.abs(slow).max() + 1e-12)
    speed = (s["wow"] * (0.7 * np.sin(2 * np.pi * s["wow_hz"] * t + rng.uniform(0, 2 * np.pi)) + 0.3 * slow)
             + s["flutter"] * np.sin(2 * np.pi * s["flutter_hz"] * t + rng.uniform(0, 2 * np.pi)))
    off = np.cumsum(speed) / sr                                         # deviation in speed integrates to a position offset
    off -= off.mean()
    pos = t + off * amt                                                 # the offset (not the speed) scales, so amount 0 lands back on time
    return np.stack([np.interp(pos, t, x[:, c]) for c in range(x.shape[1])], 1)


def _noise(kind, s, n, ch, ref_db, sr, rng):
    t = np.arange(n) / sr
    if kind == "hiss":
        w = np.fft.rfft(rng.standard_normal(n))
        f = np.fft.rfftfreq(n, 1 / sr)
        f[0] = f[1] if n > 1 else 1.0
        y = np.fft.irfft(w * (f / 1000.0) ** (-0.5 + 0.5 * s["tilt"]), n)       # pink, tilted toward white by `tilt`
        y *= 10 ** ((1.0 * np.sin(2 * np.pi * 0.07 * t + rng.uniform(0, 6.28))) / 20)   # a slow drift, as a real noise floor has
    elif kind == "hum":
        y = sum(a * np.sin(2 * np.pi * s["hz"] * h * t + rng.uniform(0, 6.28)) for h, a in ((1, 1.0), (2, 0.5), (3, 0.25), (4, 0.1)))
    else:
        # many tiny bright ticks with a heavy-tailed size (most barely there, a few clear) plus a soft, darker pop now and then
        y = np.zeros(n)
        ticks, pops = np.zeros(n), np.zeros(n)
        L = int(0.003 * sr)
        for i in rng.integers(0, max(1, n - L), int(s["rate"] * n / sr)):
            ticks[i:i + L] += rng.standard_normal(L) * np.exp(-np.arange(L) / (rng.uniform(0.0002, 0.0007) * sr)) * min(rng.pareto(2.5), 6.0)
        Lp = int(0.012 * sr)
        for i in rng.integers(0, max(1, n - Lp), int(s["rate"] / 12 * n / sr)):
            pops[i:i + Lp] += rng.standard_normal(Lp) * np.exp(-np.arange(Lp) / (0.002 * sr)) * rng.uniform(1.5, 4.0)
        if n > 64:
            ticks = signal.sosfiltfilt(_sos("band", [1200.0, min(9000.0, 0.45 * sr)], 2, sr), ticks)
            pops = signal.sosfiltfilt(_sos("band", [250.0, 2500.0], 2, sr), pops)
        y = ticks + pops * 0.6
    y = y * 10 ** ((ref_db + s["db"] - _rms_db(y)) / 20)
    return np.repeat(y[:, None], ch, 1)


def process(x, sr, fx, t0=0.0):
    """Apply a resolved fx (see `resolve`) to float audio (n,) or (n, ch) at `sr`; `t0` = the stream's start in the amount's clock.
    Returns the same shape; the processed part is matched to the input's loudness."""
    if fx is None:
        return x
    mono = x.ndim == 1
    x = np.asarray(x, dtype=np.float64)
    x = x[:, None] if mono else x
    if not len(x) or not np.any(x):
        return x[:, 0] if mono else x
    amt = amount_curve(fx["amount"], len(x), sr, t0)
    if amt.max() <= 1e-4:
        return x[:, 0] if mono else x
    rng = np.random.default_rng(fx["seed"])
    on = amt > 0.05 if np.count_nonzero(amt > 0.05) > sr // 2 else np.ones(len(x), bool)    # where the effect is on: noise and levels refer to it
    ref_db = _program_db(x[on], sr)
    dry = x
    for s in fx["chain"]:                                               # movement first: it applies to the dry part of the blend too
        if s["type"] == "wow":
            dry = _wow(dry, s, amt, sr, rng)
    y = dry
    for s in fx["chain"]:
        k = s["type"]
        if k in ("hp", "lp"):
            y = _filt(y, _sos("high" if k == "hp" else "low", s["hz"], s["order"], sr))
        elif k == "peak":
            y = _filt(y, _peak_sos(s["hz"], s["q"], s["db"], sr))
        elif k == "drive":
            y = _drive(y, s, _program_db(y, sr), sr)
        elif k == "compress":
            y = _compress(y, s, _program_db(y, sr), sr)
        elif k in ("hiss", "hum", "crackle"):
            y = y + _noise(k, s, len(y), y.shape[1], ref_db, sr, rng)
    y *= 10 ** ((ref_db - _program_db(y[on], sr)) / 20)                # matched before the blend, so where amount reaches 0 the input is untouched
    out = dry * (1 - amt)[:, None] + y * amt[:, None]
    return out[:, 0] if mono else out


def apply(x, sr, fx, t0=0.0, where="fx"):
    """`process` straight from a spec value (preset name or mapping)."""
    return process(x, sr, resolve(fx, where), t0)


def spec_fx(raw):
    """Every `fx` value a promo.yaml sets: [(where, value)] (music.fx, vo.fx, vo.lines[i].fx, mix.fx)."""
    out = []
    for key in ("music", "vo", "mix"):
        if isinstance(raw.get(key), dict) and "fx" in raw[key]:
            out.append((f"{key}.fx", raw[key]["fx"]))
    for i, line in enumerate((raw.get("vo") or {}).get("lines") or []):
        if isinstance(line, dict) and "fx" in line:
            out.append((f"vo.lines[{i}].fx", line["fx"]))
    return out


def line_fx(raw, line_id):
    """The fx of a VO line: its own `fx` (also `none`), else vo.fx."""
    vo = raw.get("vo") or {}
    for line in vo.get("lines") or []:
        if str(line.get("id", line.get("shot"))) == line_id and "fx" in line:
            return line["fx"]
    return vo.get("fx")


# ---------------------------------------------------------------- CLI
def main(argv):
    """`promo fx list | apply IN OUT --preset P [--amount A] [--set stage.param=value ...] | audition IN [--out DIR]`."""
    import argparse
    import json

    import soundfile as sf
    ap = argparse.ArgumentParser(prog="promo fx", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="presets and their stages")
    a = sub.add_parser("apply", help="process one file")
    a.add_argument("src")
    a.add_argument("out")
    a.add_argument("--preset", required=True)
    a.add_argument("--amount", default="1", help="0..1, or JSON keyframes '[[0, 1], [5, 0]]' in file seconds")
    a.add_argument("--set", action="append", default=[], metavar="STAGE.PARAM=VALUE", help="override a stage parameter, e.g. hiss.db=-44")
    u = sub.add_parser("audition", help="render the file through every preset (+ the dry original) to compare by ear")
    u.add_argument("src")
    u.add_argument("--out", help="output dir (default: <src dir>/fx-audition)")
    u.add_argument("--amount", type=float, default=1.0)
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for name, chain in PRESETS.items():
            print(f"{name:10s} {DESCRIPTIONS[name]}")
            print("           stages: " + ", ".join(f"{s['name']} ({s['type']})" for s in chain))
        return 0
    try:
        x, sr = sf.read(args.src, always_2d=True)
    except (OSError, RuntimeError) as e:
        print(f"promo fx: cannot read {args.src}: {e}")
        return 2
    try:
        if args.cmd == "apply":
            try:
                fx = {"preset": args.preset, "amount": json.loads(args.amount)}
            except ValueError:
                raise SpecError(f"--amount {args.amount!r}: expected a number or JSON keyframes like '[[0, 1], [5, 0]]'")
            for kv in args.set:
                key, _, val = kv.partition("=")
                stage, _, param = key.partition(".")
                if not (stage and param and val):
                    raise SpecError(f"--set {kv!r}: expected STAGE.PARAM=VALUE, e.g. hiss.db=-44")
                fx.setdefault(stage, {})[param] = float(val)
            y = apply(x, sr, fx, where="promo fx")
            sf.write(args.out, (y / max(1.0, np.abs(y).max() / 0.98)).astype(np.float32), sr, subtype="FLOAT")
            print(args.out)
            return 0
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.src)), "fx-audition")
        os.makedirs(out, exist_ok=True)
        stem = os.path.splitext(os.path.basename(args.src))[0]
        sf.write(os.path.join(out, f"{stem}-dry.wav"), x.astype(np.float32), sr, subtype="FLOAT")
        for name in PRESETS:
            y = apply(x, sr, {"preset": name, "amount": args.amount}, where="promo fx")
            p = os.path.join(out, f"{stem}-{name}.wav")
            sf.write(p, (y / max(1.0, np.abs(y).max() / 0.98)).astype(np.float32), sr, subtype="FLOAT")
            print(p)
        return 0
    except SpecError as e:
        print(e)
        return 2
