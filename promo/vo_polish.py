"""Clean-up for each VO line before the mix levels it (`vo.polish`): rumble cut, quiet pauses, softer "s" sounds, a little glue.

Spec:
  vo:    {polish: on, lines: [{..., polish: off}]}          line `polish` replaces vo.polish; absent = off (old projects mix as before)
  polish: on | off | {<stage>: {param: value} | off, ...}  a mapping starts from every stage at its defaults

Stages (in this order; levels in dB relative to the line's loud level, so they hold for quiet and loud takes alike):
  hp:       high-pass at `hz` (rumble, mic thumps, DC)
  compress: gentle feed-forward compression (promo/audiofx.py's compressor) for an even read.
  deess:    turns down the `lo`-`hi` band only while it carries most of the sound (an "s", "sh", "t"); `threshold` is the band's
            level against the whole signal, `ratio` and `max` limit the cut. The split is zero-phase, so the band recombines exactly.
  gate:     downward expander for the pauses between words: below `threshold` the level falls `ratio` times faster, at most
            `range` dB. It is fully open from `look` s before a word to `hold` s after it; the `close` and `open` ramps run
            inside the pause (offline, so it can look ahead), so onsets and soft endings stay.
            A local voice (Ming) leaves a floor ~40 dB under its speech, hosted voices ~60 dB: this takes Ming's down to theirs.
The result is matched to the input's loud level (the mix levels each line afterwards anyway).
"""
from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.ndimage import maximum_filter1d

from .audiofx import _compress, _filt, _program_db, _sos
from .spec import SpecError

STAGES = {     # in chain order: the de-esser after the compressor (which lifts the quieter "s" sounds), the gate last (or the compressor's
    # make-up would lift the pauses it quietened)
    "hp": dict(hz=80.0, order=2),
    "compress": dict(threshold=-10.0, ratio=2.0, attack=0.01, release=0.12),
    "deess": dict(lo=5000.0, hi=9000.0, threshold=-10.0, ratio=3.0, max=8.0),
    # tuned on real takes: Ming's pauses are short (150-300 ms), so the open window and ramps stay short to reach them
    "gate": dict(threshold=-32.0, ratio=4.0, range=18.0, look=0.02, hold=0.04, open=0.012, close=0.04),
}
OFF = (None, False, "off", "none")


def resolve(polish, where="polish"):
    """The spec value of a `polish` key -> {stage: params} in chain order, or None (off). Raises SpecError on anything unknown."""
    if polish in OFF:
        return None
    if polish is True or polish == "on":
        polish = {}
    if not isinstance(polish, dict):
        raise SpecError(f"{where}: must be on, off or a mapping of stages ({', '.join(STAGES)}), got {polish!r}")
    bad = sorted(set(polish) - set(STAGES))
    if bad:
        raise SpecError(f"{where}: unknown stages {bad}; stages: {', '.join(STAGES)}")
    out = {}
    for name, defaults in STAGES.items():
        v = polish.get(name, {})
        if v in OFF:
            continue
        if v is True or v == "on":
            v = {}
        if not isinstance(v, dict):
            raise SpecError(f"{where}.{name}: must be off or a mapping of parameters, e.g. {{{next(iter(defaults))}: {next(iter(defaults.values()))}}}")
        unknown = sorted(set(v) - set(defaults))
        if unknown:
            raise SpecError(f"{where}.{name}: unknown parameters {unknown}; known: {', '.join(defaults)}")
        for k, val in v.items():
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise SpecError(f"{where}.{name}: {k} must be a number, got {val!r}")
        s = {k: float(val) for k, val in {**defaults, **v}.items()}
        if name == "deess" and not 0 < s["lo"] < s["hi"]:
            raise SpecError(f"{where}.deess: needs 0 < lo < hi, got lo {s['lo']:g}, hi {s['hi']:g}")
        if name in ("gate", "deess", "compress") and s["ratio"] < 1:
            raise SpecError(f"{where}.{name}: ratio must be >= 1, got {s['ratio']:g}")
        out[name] = s
    return out


def line_polish(raw, line_id):
    """The polish of a VO line: its own `polish` (also `off`), else vo.polish."""
    vo = raw.get("vo") or {}
    for line in vo.get("lines") or []:
        if str(line.get("id", line.get("shot"))) == line_id and "polish" in line:
            return line["polish"]
    return vo.get("polish")


def spec_polish(raw):
    """Every `polish` value a promo.yaml sets: [(where, value)] (vo.polish, vo.lines[i].polish)."""
    vo = raw.get("vo") if isinstance(raw.get("vo"), dict) else {}
    out = [("vo.polish", vo["polish"])] if "polish" in vo else []
    for i, line in enumerate(vo.get("lines") or []):
        if isinstance(line, dict) and "polish" in line:
            out.append((f"vo.lines[{i}].polish", line["polish"]))
    return out


def _levels(x, sr, win):
    """RMS level in dB of `win`-second windows on a 1 ms grid (mono mix of the channels)."""
    hop = max(1, int(0.001 * sr))
    p = signal.convolve(x.mean(1) ** 2 if x.ndim == 2 else x ** 2, np.ones(max(1, int(win * sr))) / max(1, int(win * sr)), mode="same")
    return 10 * np.log10(p[::hop] + 1e-20), hop


def _ballistics(want_db, attack, release):
    """One-pole smoothing of a gain curve in dB on the 1 ms grid: `attack` while the cut deepens, `release` while it lets go."""
    ca, cr = np.exp(-1 / (max(attack, 1e-4) * 1000)), np.exp(-1 / (max(release, 1e-4) * 1000))
    out = np.empty_like(want_db)
    st = 0.0
    for i, w in enumerate(want_db):
        st = w + (st - w) * (ca if w < st else cr)
        out[i] = st
    return out


def _to_samples(g_db, hop, n):
    return 10 ** (np.repeat(g_db, hop)[:n] / 20)


def _gate_db(x, s, ref_db, sr):
    """The gate's cut in dB on the 1 ms grid (0 = open, -range = closed) and the grid's hop, decided on the take as it came
    (the compressor narrows the gap between words and pauses)."""
    lvl, hop = _levels(x, sr, 0.01)
    # the loudest level near each moment: the gate is fully open from `look` s before a word to `hold` s after it
    near = maximum_filter1d(lvl, size=int((s["look"] + s["hold"]) * 1000) + 1, origin=-int((s["look"] - s["hold"]) * 500))
    under = np.minimum(0.0, near - (ref_db + s["threshold"]))
    want = np.maximum(-s["range"], under * (s["ratio"] - 1))
    # ramps only ever lift the cut: closing eases in after a word (forward pass), opening eases out before the next one
    # (backward pass), so the ramps sit in the pause and a word is never reached by a gain below the open level
    g = _ballistics(want, s["close"], 1e-4)
    return _ballistics(g[::-1], s["open"], 1e-4)[::-1], hop


def _deess(x, s, ref_db, sr):
    if s["lo"] >= 0.45 * sr:                                            # the take has no top band to tame (e.g. 8 kHz audio)
        return x
    band = _filt(x, _sos("band", [s["lo"], s["hi"]], 2, sr))
    lb, hop = _levels(band, sr, 0.005)
    lf, _ = _levels(x, sr, 0.005)
    over = np.maximum(0.0, (lb - lf) - s["threshold"]) * (lb > ref_db - 30)   # only audible sibilance, never a breath in a pause
    cut = -np.minimum(s["max"], over * (1 - 1 / s["ratio"]))
    g = _to_samples(_ballistics(cut, 0.002, 0.04), hop, len(x))[:, None]
    return x - band + band * g


def process(x, sr, polish):
    """Apply a resolved polish (see `resolve`) to float audio (n,) or (n, ch) at `sr`. Returns the same shape."""
    if not polish:
        return x
    mono = x.ndim == 1
    y = np.asarray(x, dtype=np.float64)
    y = y[:, None] if mono else y
    if len(y) < sr // 10 or not np.any(y):
        return x
    ref = _program_db(y, sr)
    gate = _gate_db(y, polish["gate"], ref, sr) if "gate" in polish else None
    for name, s in polish.items():
        if name == "hp":
            y = _filt(y, _sos("high", s["hz"], s["order"], sr))
        elif name == "deess":
            y = _deess(y, s, _program_db(y, sr), sr)
        elif name == "compress":
            y = _compress(y, s, _program_db(y, sr), sr)
    makeup = ref - _program_db(y, sr)
    y *= 10 ** (makeup / 20)
    if gate is not None:
        # the make-up gain lifts the pauses too (the compressor never touched them): a closed gate also takes that back, so `range`
        # is how much further under the words the pauses end up
        g, hop = gate
        rng = polish["gate"]["range"]
        y = y * _to_samples(g * (rng + max(0.0, makeup)) / rng if rng > 0 else g, hop, len(y))[:, None]
    return y[:, 0] if mono else y


def apply(x, sr, polish, where="polish"):
    """`process` straight from a spec value."""
    return process(x, sr, resolve(polish, where))
