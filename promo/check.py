"""QA gates (`promo check`): exit 1 if any FAIL, WARN does not fail. Report table + out/<name>-<tag>-check.json."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import re
import subprocess
import unicodedata

from . import assets as A
from .cache import Stamps
from .shots import get_type


class Report:
    def __init__(self):
        self.rows = []

    def add(self, gate, status, msg):
        self.rows.append(dict(gate=gate, status=status, msg=msg))

    @property
    def failed(self):
        return any(r["status"] == "FAIL" for r in self.rows)


def ffprobe_json(path, *args):
    return json.loads(subprocess.check_output(["ffprobe", "-v", "error", "-of", "json", *args, path]).decode())


def loudness(path):
    """ffmpeg ebur128 (peak=true): returns (integrated LUFS, true peak dBFS)."""
    r = subprocess.run(["ffmpeg", "-nostats", "-threads", "2", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    tail = r.stderr[r.stderr.rfind("Summary:"):]
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", tail)
    p = re.search(r"True peak:\s+Peak:\s+(-?[\d.]+) dBFS", tail) or re.search(r"Peak:\s+(-?[\d.]+) dBFS", tail)
    return (float(i.group(1)) if i else None), (float(p.group(1)) if p else None)


def norm_words(s, aliases=None):
    s = s.replace("\u2026", " ").replace("\u2019", "'").replace("\u2018", "'").replace("\u201c", '"').replace("\u201d", '"')
    s = unicodedata.normalize("NFKD", s).lower().replace("-", " ")
    s = re.sub(r"[^\w\s']", " ", s).replace("'", "")
    w = s.split()
    return w


def wer(ref, hyp):
    """Word error rate via edit distance on word lists."""
    if not ref:
        return 0.0 if not hyp else 1.0
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
            prev = cur
    return d[len(hyp)] / len(ref)


def transcribe(path, model_name):
    """Port of asr.py: pad 0.5 s front / 1 s back at 16 kHz, beam 5, temperature 0, no previous-text conditioning."""
    import librosa
    import numpy as np
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    m = transcribe.__dict__.setdefault("_m", {})
    if model_name not in m:
        m[model_name] = WhisperModel(model_name, device="cpu", compute_type="float32", cpu_threads=2)
    y, sr = librosa.load(path, sr=16000)
    yp = np.concatenate([np.zeros(8000), y, np.zeros(16000)]).astype(np.float32)
    segs, _ = m[model_name].transcribe(yp, beam_size=5, temperature=0, condition_on_previous_text=False, without_timestamps=True)
    return " ".join(s.text.strip() for s in segs)


def _anime_effective_dpr(spec, warns, limit=1.5):
    """Anime shots frame footage in a viewport narrower than the frame (band / contain): restate their soft-upscale WARNs
    with the real effective scale (viewport px per source px), and drop them when that is within the limit."""
    from . import footage as FT
    out = []
    for w in warns:
        sid = w.split(":")[0].replace("shot ", "")
        s = next((x for x in spec.shots if x.id == sid), None)
        if s is None or s.type not in ("anime", "cinema", "screen"):
            out.append(w)
            continue
        if s.type == "cinema":
            from .shots.cinema import viewport
        elif s.type == "screen":
            from .shots.screen import viewport
        else:
            from .shots.anime import viewport
        vp = viewport(spec, s)
        mag = FT.max_magnification(s) * (vp[2] - vp[0]) / 1920
        if mag > limit:
            out.append(w.replace(w.split(":")[1].split(" push-in")[0], f" {mag:.2f}x effective"))
    return out


def line_max_wer(line, default):
    """The most word errors a VO line may have in the read-back: the project's `qa.vo_max_wer`, or the line's own `max_wer` (a line that is meant to be too fast to follow)."""
    return float(line.get("max_wer", default))


def _aliased(line, heard, qa):
    for k, v in {**(qa.get("asr_aliases") or {}), **(line.get("asr_aliases") or {})}.items():
        heard = re.sub(re.escape(k), v, heard, flags=re.I)
    return heard


def heard_wer(line, heard, qa):
    """WER of what whisper heard against the line's script text, after the project's and the line's `asr_aliases` (heard-as -> script word)."""
    return wer(norm_words(line["text"]), norm_words(_aliased(line, heard, qa)))


_SOUNDEX = {**dict.fromkeys("bfpv", "1"), **dict.fromkeys("cgjkqsxz", "2"), **dict.fromkeys("dt", "3"), "l": "4", "m": "5", "n": "5", "r": "6"}


def soundex(word):
    """American Soundex: words that sound alike get one code ("two" / "to", "routes" / "roots"); a word with digits stays as it is."""
    if not word.isalpha():
        return word
    out, last = word[0], _SOUNDEX.get(word[0], "")
    for c in word[1:]:
        code = _SOUNDEX.get(c, "")
        if code and code != last:
            out += code
        if c not in "hw":                                       # h and w do not separate two letters with the same code
            last = code
    return (out + "000")[:4]


def lost_words(line, heard, qa):
    """Share of the script's words missing from what whisper heard (1 - longest common subsequence / script words). Extra heard
    words do not count: a window of the mix can catch the next line's first word or a lyric in the music. Words match by sound
    (Soundex): over music whisper spells "Two" as "to" or "routes" as "roots", which a viewer hears the same."""
    ref = [soundex(w) for w in norm_words(line["text"])]
    hyp = [soundex(w) for w in norm_words(_aliased(line, heard, qa))]
    if not ref:
        return 0.0
    d = [0] * (len(hyp) + 1)
    for r in ref:
        prev = 0
        for j, h in enumerate(hyp, 1):
            cur = d[j]
            d[j] = prev + 1 if r == h else max(d[j], d[j - 1])
            prev = cur
    return 1 - d[len(hyp)] / len(ref)


def vo_music_db(spec):
    """{line id: dB} how far each VO line sits over the music in the speech band (1-5 kHz) while it speaks, from the stems; None
    when the project has no music or no mix yet."""
    import numpy as np
    import soundfile as sf
    from scipy import signal
    rp = os.path.join(spec.audio_dir, "mix-report.json")
    sd = os.path.join(spec.audio_dir, "stems")
    if not (spec.raw.get("music") and os.path.exists(rp) and os.path.exists(os.path.join(sd, "music.wav"))):
        return None
    rep = json.load(open(rp))
    vo, sr = sf.read(os.path.join(sd, "vo.wav"), dtype="float32")
    mu, _ = sf.read(os.path.join(sd, "music.wav"), dtype="float32")
    sos = signal.butter(4, [1000, 5000], btype="band", fs=sr, output="sos")
    v = signal.sosfiltfilt(sos, vo.mean(1))
    m = signal.sosfiltfilt(sos, mu.mean(1)) * 10 ** (rep["bus_db"]["music"] / 20)    # the music stem is before its bus gain
    hop = int(0.05 * sr)
    out = {}
    for t0, t1, sid, _ in rep["vo"]:
        a = int(t0 * sr)
        n = (min(int(t1 * sr), len(v)) - a) // hop
        if n < 1:
            continue
        fv = np.mean(v[a:a + n * hop].reshape(n, hop) ** 2, 1)
        fm = np.mean(m[a:a + n * hop].reshape(n, hop) ** 2, 1)
        on = fv > fv.max() * 0.01                                # 50 ms frames within 20 dB of the line's loudest: speaking
        out[str(sid)] = float(10 * np.log10(fv[on].mean() / (fm[on].mean() + 1e-20)))
    return out


def vo_masking(spec, qa):
    """(status, msg) for `vo-masking`: each VO line's `vo_music_db`. WARNs a line under `qa.vo_music_min_db` (default 10): whisper still
    hears words a viewer strains for."""
    if not spec.raw.get("music"):
        return "PASS", "no music under the VO"
    ratios = vo_music_db(spec)
    if ratios is None:
        return "WARN", "no mix yet (run `promo build`)"
    want = float(qa.get("vo_music_min_db", 10.0))
    low = [f"{sid} {r:.1f} dB" for sid, r in ratios.items() if r < want]
    worst = min(ratios.values()) if ratios else None
    if low:
        return "WARN", (f"VO over the music in 1-5 kHz under {want:g} dB (listen; duck more, `mix.duck.band`, or lower bus_db.music): "
                        + ", ".join(low))
    return "PASS", f"every line >= {want:g} dB over the music in 1-5 kHz (lowest {worst:.1f} dB)" if worst is not None else "no VO in the mix"


def vo_mix_asr(spec, stamps, qa, lines):
    """(status, msg) for `vo-mix-asr`: each VO line read back by whisper from the first master's mix (music, SFX and ducking in),
    against its script. FAILs a line the mix makes lose words that its clean take did not; WARNs instead on a line with character fx
    (its own or mix.fx), where some loss can be the effect. Each window is the line's whole span, even where the next line overlaps
    it (vo-fit reports that): cutting it at the next start would count the overlapped words as lost, and extra words do not count."""
    import tempfile

    import soundfile as sf

    from . import audiofx
    from . import mix as MX
    wav = MX.master_path(spec, spec.masters[0]["name"])
    rp = os.path.join(spec.audio_dir, "mix-report.json")
    if not (os.path.exists(wav) and os.path.exists(rp)):
        return "WARN", "no mix yet (run `promo build`)"
    marks = json.load(open(rp))["vo"]                            # [t0, t1, id, text]; a muted line has none
    model = qa.get("asr_model", "small.en")
    by_id = {str(ln.get("id", ln["shot"])): ln for ln in lines}
    info = sf.info(wav)
    bad, soft, n = [], [], 0
    for t0, t1, sid, _ in marks:
        ln = by_id.get(str(sid))
        if ln is None:
            continue
        y, sr = sf.read(wav, start=int(t0 * info.samplerate), stop=int(t1 * info.samplerate), dtype="float32", always_2d=True)
        y = y.mean(1)
        key = hashlib.sha256(y.tobytes()).hexdigest() + model
        st = stamps.get(f"asr_mix_{sid}")
        if st and st.get("digest") == key:
            heard = st["text"]
        else:
            with tempfile.NamedTemporaryFile(suffix=".wav") as f:
                sf.write(f.name, y, sr)
                heard = transcribe(f.name, model)
            stamps.write(f"asr_mix_{sid}", key, text=heard)
        st = stamps.get(f"asr_{sid}")                            # the clean take's read-back (vo-script, just before)
        clean = lost_words(ln, st["text"], qa) if st else 0.0
        lost = lost_words(ln, heard, qa)
        n += 1
        if lost > max(line_max_wer(ln, qa.get("vo_max_wer", 0.0)), clean) + 1e-9:
            msg = f"{sid}: {lost:.0%} of its words lost in the mix (heard {heard.strip()!r})"
            (soft if audiofx.line_fx(spec.raw, str(sid)) or (spec.raw.get("mix") or {}).get("fx") else bad).append(msg)
    if bad:
        return "FAIL", "; ".join(bad + soft) + " (duck the music more, `mix.duck.band`, or lower bus_db.music)"
    if soft:
        return "WARN", "; ".join(soft) + " (lines with character fx: listen)"
    return "PASS", f"{n} lines read back from the {spec.masters[0]['name']} mix with no words lost"


def vo_audio_gates(spec, meta):
    """[(gate, status, msg)] on the VO takes themselves (no whisper): `vo-fit` FAILs a line that runs past the film's end (the mix
    cuts it off) and WARNs one that runs into the next line; `vo-clip` WARNs a clipped take; `vo-tail` WARNs a take that ends mid-sound."""
    import numpy as np
    import soundfile as sf

    from .events import vo_times
    from .shot_audio import OVERLAP_WARN
    from .vo_score import TAIL_CUT_DB, tail_db
    times = vo_times(spec)
    spans, clipped, cut = [], [], []
    for m in meta:
        lid = str(m.get("id", m["shot"]))
        x, sr = sf.read(os.path.join(spec.vo_dir, m["file"]), dtype="float32", always_2d=True)
        x = x.mean(1)
        if lid in times:
            spans.append((times[lid], times[lid] + len(x) / sr, lid))
        # three equal samples in a row at full scale is a flat top: the take clipped (a float take above 1.0 that was not clipped never repeats like that)
        flat = (np.abs(x[:-2]) >= 0.999) & (x[:-2] == x[1:-1]) & (x[1:-1] == x[2:])
        if flat.any():
            clipped.append(f"{lid} ({int(flat.sum())} flat-topped samples)")
        td = tail_db(x, sr)
        if td > TAIL_CUT_DB:
            cut.append(f"{lid} ({td:.0f} dB just before its end)")
    spans.sort()
    late = [f"{lid} ends at {b:.2f}s, after the film's end at {spec.duration:.2f}s (the mix cuts it off)" for a, b, lid in spans
            if b > spec.duration + 1e-3]
    over = [f"{an} runs {a1 - b0:.2f}s into {bn} at {b0:.2f}s" for (a0, a1, an), (b0, b1, bn) in zip(spans, spans[1:]) if a1 - b0 > OVERLAP_WARN]
    return [("vo-fit", "FAIL" if late else ("WARN" if over else "PASS"),
             "; ".join(late + over) or f"{len(spans)} lines end inside the film, none runs > {OVERLAP_WARN}s into the next"),
            ("vo-clip", "WARN" if clipped else "PASS", "clipped takes (re-voice them): " + ", ".join(clipped) if clipped else "no clipped takes"),
            ("vo-tail", "WARN" if cut else "PASS", "cut off mid-sound (listen; re-voice or move the cut): " + ", ".join(cut) if cut else "every take ends in its own silence")]


def run(spec):
    rep = Report()
    qa = spec.qa
    hold_min = qa.get("min_caption_hold", 2.0)
    stamps = Stamps(spec.build)

    # 1. assets + lint (lint already ran at load)
    probs = A.validate(spec)
    rep.add("assets", "FAIL" if probs else "PASS", "; ".join(probs) if probs else "manifest complete; spec lint clean")
    try:
        dr = A.drafts(A.load_manifest(spec))
    except A.AssetError:
        dr = []
    if dr:
        rep.add("assets-draft", "WARN", "licence still `status: draft` (terms pending confirmation; clear before publishing): " + ", ".join(dr))
    from . import footage as FT
    try:
        bad = [r for r in FT.verify(spec) if not r["ok"]]
        rep.add("footage", "FAIL" if bad else "PASS", "; ".join(r["error"] for r in bad) if bad else f"{len(FT.referenced(spec))} referenced clips present, sha256 match")
        dpr_w, demo = FT.qa_findings(spec)
        dpr_w = _anime_effective_dpr(spec, dpr_w)
        rep.add("footage-dpr", "WARN" if dpr_w else "PASS", "; ".join(dpr_w) if dpr_w else "no soft-upscale risk (dpr >= 2 or push-in <= 1.5x)")
        rep.add("footage-demo", "WARN" if demo else "PASS", f"demo-mode footage in use: {', '.join(demo)}" if demo else "no demo-mode footage")
        from . import glitch as GL
        gl = GL.findings(spec)
        rep.add("footage-glitch", "FAIL" if gl else "PASS", ("; ".join(gl) + ": re-record with capture/lib/recorder.mjs (a reviewed false positive goes in "
                "the clip's glitch_ok)") if gl else "no one-frame paint glitches in the referenced captures")
    except FT.FootageError as e:
        rep.add("footage", "FAIL", str(e))
    from .mix import spec_problems
    probs = spec.validate() + spec_problems(spec.raw)
    rep.add("timeline", "FAIL" if probs else "PASS", "; ".join(probs) if probs else f"{len(spec.shots)} shots contiguous 0..{spec.timeline.beats} beats")

    # 5. beat grid. preset @2 with pacing.strict_beat false snaps to phrases instead (docs/PRODUCT-DEFAULTS.md):
    # an off-beat cut is not a FAIL. Version 1 and legacy specs stay on the beat.
    sub = qa.get("beat_subdivision", 1)
    loose = ((spec.style or {}).get("pacing") or {}).get("strict_beat") is False
    # the very end may stop off-grid (trimmed to where the music ends, e.g. timeline.beats: 224.76695); every cut stays on the grid
    last = spec.shots[-1] if spec.shots else None
    off = [s.id for s in spec.shots if any(abs(b * sub - round(b * sub)) > 1e-9 for b in (s.b0, s.b1)
                                           if not (s is last and b == s.b1 and abs(b - spec.timeline.beats) < 1e-9))]
    expect = round(spec.duration * spec.fps)
    tot = spec.total_frames()
    msgs = []
    if off and not loose:
        msgs.append(f"shots off the beat grid: {off}")
    if tot != expect:
        msgs.append(f"timeline frames {tot} != duration*fps {expect}")
    for s in spec.shots:
        p = spec.seg_path(s.id)
        if os.path.exists(p):
            try:
                n = int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", p]).decode())
                if n != s.n:
                    msgs.append(f"segment {s.id}: {n} frames != {s.n}")
            except Exception as e:  # noqa: BLE001
                msgs.append(f"segment {s.id}: unreadable ({e})")
    tail = f"; ends off-grid at beat {spec.timeline.beats:g} (tail trimmed to output.duration)" if abs(spec.timeline.beats - round(spec.timeline.beats * sub) / sub) > 1e-9 else ""
    if msgs:
        grid_msg = "; ".join(msgs)
    elif loose and off:
        grid_msg = f"phrase sync (per-beat lock off): cuts off the beat {off}; {tot} frames, rendered segments match" + tail
    elif loose:
        grid_msg = f"phrase sync (per-beat lock off); cuts on beats, {tot} frames, rendered segments match" + tail
    else:
        grid_msg = f"all cuts on beats, {tot} frames, rendered segments match" + tail
    rep.add("beat-grid", "FAIL" if msgs else "PASS", grid_msg)

    # 2/3/4. per-output checks
    for m in spec.masters:
        out = spec.output_path(m.get("suffix", ""))
        nm = os.path.basename(out)
        if not os.path.exists(out):
            for g in ("duration", "video-format", "loudness", "true-peak"):
                rep.add(g, "FAIL", f"{nm}: output missing (run `promo build`)")
            continue
        j = ffprobe_json(out, "-show_streams", "-show_format")
        v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
        a = next((s for s in j["streams"] if s["codec_type"] == "audio"), None)
        dur = float(j["format"]["duration"])
        ok = abs(dur - spec.duration) <= 1 / spec.fps + 1e-6 and a is not None
        rep.add("duration", "PASS" if ok else "FAIL", f"{nm}: {dur:.3f}s (want {spec.duration}), audio {'present' if a else 'MISSING'}")
        nfr = int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", out]).decode())
        n_, d_ = v["r_frame_rate"].split("/")
        fps = float(n_) / float(d_)
        ok = (v["width"], v["height"]) == (spec.OW, spec.OH) and abs(fps - spec.fps) < 1e-3 and nfr == expect
        rep.add("video-format", "PASS" if ok else "FAIL", f"{nm}: {v['width']}x{v['height']} {fps:g}fps {nfr} frames (want {spec.OW}x{spec.OH} {spec.fps}fps {expect})")
        L, tp = loudness(out)
        tol = qa.get("lufs_tolerance", 0.5)
        ok = L is not None and abs(L - m["lufs"]) <= tol and tp is not None and tp <= m.get("max_true_peak", -1.0)
        rep.add("loudness", "PASS" if ok else "FAIL", f"{nm}: {L} LUFS (target {m['lufs']}±{tol}), true peak {tp} dBTP (max {m.get('max_true_peak', -1.0)})")
        # true peak on its own: the master WAV (before the encoder) and the encoded file must both stay <= max_true_peak
        mx = m.get("max_true_peak", -1.0)
        mw = os.path.join(spec.audio_dir, f"mix-{m['name']}.wav")
        wtp = None
        if os.path.exists(mw):
            import soundfile as _sf

            from .mix import true_peak as _tp
            wtp = round(float(_tp(_sf.read(mw, always_2d=True)[0])), 2)
        bad = [x for x in (tp, wtp) if x is not None and x > mx] or ([] if tp is not None else ["unmeasured"])
        rep.add("true-peak", "FAIL" if bad else "PASS", f"{nm}: encoded {tp} dBTP, master WAV {wtp} dBTP (max {mx} dBTP)")

    # 6/7. captions: hold + safe zone
    from .render import RenderContext
    ctx = RenderContext.from_spec(spec)
    zone, maxw = ctx.caption["zone"], ctx.caption["max_w"]
    holds, zones = [], []
    for s in spec.shots:
        caps = get_type(s.type).captions(ctx, s)
        for c in caps:
            t1 = min(c["t1"], s.dur)
            hold = t1 - c["t0"]
            need = c.get("min_hold") or hold_min
            if c["role"] == "caption":
                if hold < need - 1e-9:
                    holds.append(("FAIL", f"shot {s.id} caption {c['text']!r} visible {hold:.2f}s < {need}s"))
                if s.dur < hold_min - 1e-9:
                    holds.append(("FAIL", f"shot {s.id} lasts {s.dur:.2f}s < {hold_min}s but has a caption"))
                b = c["box"]
                if b:
                    w = b[2] - b[0]
                    if not (b[0] >= zone["x0"] and b[2] <= zone["x1"] and b[1] >= zone["y0"] and b[3] <= zone["y1"]) or w > maxw:
                        zones.append(f"shot {s.id} caption {c['text']!r} box {[round(x, 1) for x in b]} outside zone {zone} or wider than {maxw}")
            elif c["role"] == "label" and hold < need - 1e-9:
                holds.append(("WARN", f"shot {s.id} label {c['text']!r} visible {hold:.2f}s < {need}s"))
    hf = [m for st, m in holds if st == "FAIL"]
    hw = [m for st, m in holds if st == "WARN"]
    rep.add("caption-hold", "FAIL" if hf else ("WARN" if hw else "PASS"), "; ".join(hf + hw) if (hf or hw) else f"all captions >= {hold_min}s")
    rep.add("caption-zone", "FAIL" if zones else "PASS", "; ".join(zones) if zones else "all caption pills inside the safe zone")

    # 6b. dissolves at the cuts (blended by promo/assemble.py): the style allows them, and no text sits in a window, where it would
    # double up with the held frame and lose part of its hold
    from .spec import SpecError, cuts
    try:
        cl = cuts(spec)
    except SpecError:
        cl = []                                     # the timeline gate above already FAILs it with the reason
    if cl:
        allowed = ((spec.style or {}).get("transitions") or {}).get("allowed") or ["cut"]
        bad = [] if "dissolve" in allowed else [f"cut_in dissolve on shots {', '.join(c['shot'] for c in cl)} but style.transitions.allowed is {allowed}"]
        warn = []
        for c in cl:
            i = next(k for k, s in enumerate(spec.shots) if s.id == c["shot"])
            a, b = spec.shots[i - 1], spec.shots[i]
            for s, w0, w1 in ((a, a.dur - c["a"] / spec.fps, a.dur), (b, 0.0, c["b"] / spec.fps)):
                warn += [f"shot {s.id} {x['role']} {x['text']!r} is on screen during the dissolve into {c['shot']}"
                         for x in get_type(s.type).captions(ctx, s) if x["t0"] < w1 - 1e-9 and min(x["t1"], s.dur) > w0 + 1e-9]
        rep.add("cut-in", "FAIL" if bad else "WARN" if warn else "PASS", "; ".join(bad + warn) or
                f"{len(cl)} dissolve{'s' if len(cl) > 1 else ''} ({', '.join(c['shot'] for c in cl)}), no text inside a window")

    # 7b. style-preset gates (anime-opening: bar cuts, holds, band, UI-clear cards, fx at cuts, claims, markers ...)
    from . import genvideo
    for g, st_, msg in genvideo.plate_gate(spec):
        rep.add(g, st_, msg)
    from . import style_check
    for g, st_, msg in style_check.run(spec):
        rep.add(g, st_, msg)

    # 7a'. previz: a strip of the current directing scene exists (promo/previz.py)
    from . import previz as PZ
    for gate, status, msg in PZ.gates(spec):
        rep.add(gate, status, msg)
    pv = FT.previz_entries(spec)
    rep.add("previz-not-footage", "FAIL" if pv else "PASS", f"footage manifest points at previz blockouts: {', '.join(pv)} (record the real screen)" if pv
            else "no previz file is registered as footage")

    # 7b. livestream layout: screen share, chat lines, single side move, keep-clear rectangles
    from . import livestream as LS
    for gate, status, msg in LS.check(spec, ctx):
        rep.add(gate, status, msg)
    # 7b'. podcast / VTuber show: model licences + credits, framing, subtitles, lint, voice licences, claims with evidence
    from . import podcast as PC
    for gate, status, msg in PC.check(spec, ctx):
        rep.add(gate, status, msg)

    # 7c. generic gates for every project (promo/generic_check.py): named >= 18 px on clip shots and the claims audit
    # (folded in from the hero's per-project tools), plus the WARN-only text-edge / empty-frame / caption-truth / long-hold
    from . import generic_check as GC
    for gate, status, msg in GC.run(spec, ctx):
        rep.add(gate, status, msg)

    # 7c". shared gates for every project, any skill (promo/shared_check.py): muted-hook, end-card-hold
    from . import shared_check as SC
    for gate, status, msg in SC.gates(spec, ctx):
        rep.add(gate, status, msg)

    # 7c'. opt-in platform gates (`platform: x` in promo.yaml, promo/x_check.py)
    from . import x_check as XC
    for gate, status, msg in XC.gates(spec, ctx):
        rep.add(gate, status, msg)

    # 7d. project-level: the locked brief, reference dossiers, intent review of the newest round (promo/brief.py, promo/refs.py)
    from . import brief as BRIEF
    for gate, status, msg in BRIEF.gates(spec):
        rep.add(gate, status, msg)

    # 8. contact sheet
    from . import contact
    try:
        png, js = contact.contact_paths(spec)
        if os.path.exists(spec.output_path(spec.masters[0].get("suffix", ""))):
            contact.run(spec)
        info = json.load(open(js)) if os.path.exists(js) else None
        ok = os.path.exists(png) and info and info["tiles"] == len(spec.shots)
        rep.add("contact-sheet", "PASS" if ok else "FAIL",
                f"{os.path.basename(png)}: {info['tiles']} tiles for {len(spec.shots)} shots" if info else f"{os.path.basename(png)} not generated (needs the assembled output)")
    except Exception as e:  # noqa: BLE001
        rep.add("contact-sheet", "FAIL", str(e))

    # 9. VO vs script
    vj = os.path.join(spec.vo_dir, "vo.json")
    lines = spec.raw.get("vo", {}).get("lines", [])
    if not lines:
        rep.add("vo-script", "PASS", "no VO")
    elif not os.path.exists(vj):
        rep.add("vo-script", "WARN", "no VO stems (run `promo vo`)")
    else:
        try:
            importlib.import_module("faster_whisper")
            have = True
        except ImportError:
            have = False
        if not have:
            rep.add("vo-script", "WARN", "skipped: faster-whisper not installed")
            rep.add("vo-mix-asr", "WARN", "skipped: faster-whisper not installed")
        else:
            meta = {str(x.get("id", x["shot"])): x for x in json.load(open(vj))["lines"]}
            bad, maxw_ = [], qa.get("vo_max_wer", 0.0)
            for ln in lines:
                sid = str(ln.get("id", ln["shot"]))
                if sid not in meta:
                    bad.append(f"{sid}: no stem")
                    continue
                p = os.path.join(spec.vo_dir, meta[sid]["file"])
                h = hashlib.sha256(open(p, "rb").read()).hexdigest()
                key = f"asr_{sid}"
                st = stamps.get(key)
                if st and st.get("digest") == h + qa.get("asr_model", "small.en"):
                    txt = st["text"]
                else:
                    txt = transcribe(p, qa.get("asr_model", "small.en"))
                    stamps.write(key, h + qa.get("asr_model", "small.en"), text=txt)
                w = heard_wer(ln, txt, qa)
                if w > line_max_wer(ln, maxw_):
                    bad.append(f"{sid}: WER {w:.2f} (heard {txt!r})")
            rep.add("vo-script", "FAIL" if bad else "PASS", "; ".join(bad) if bad else f"{len(lines)} lines match the script (WER <= {maxw_})")
            rep.add("vo-mix-asr", *vo_mix_asr(spec, stamps, qa, lines))
    if lines and os.path.exists(vj):
        for gate, status, msg in vo_audio_gates(spec, json.load(open(vj))["lines"]):
            rep.add(gate, status, msg)
        rep.add("vo-masking", *vo_masking(spec, qa))

    # 9b. shot audio (clip soundtrack lines, promo/shot_audio.py): clips present with sound, vo-bus overlaps, ASR read-back
    from . import shot_audio
    for gate, status, msg in shot_audio.check(spec, stamps, qa):
        rep.add(gate, status, msg)

    # 10. stale check: steps whose stamped input digest no longer matches (same logic as `promo status`)
    from .cli import cmd_status
    stale = [f"{x['step']}" for x in cmd_status(spec, None)["steps"] if x["status"] == "stale"]
    rep.add("stale", "WARN" if stale else "PASS", f"stale (rebuild needed): {', '.join(stale)}" if stale else "no stale steps (missing steps are reported by the other gates)")

    # the files measured, by content: `promo flow draft verify` attaches this report only to a draft that is one of them
    from .genvideo import sha256
    outputs = [dict(file=os.path.abspath(o), sha256=sha256(o)) for o in (spec.output_path(m.get("suffix", "")) for m in spec.masters) if os.path.exists(o)]
    os.makedirs(spec.out, exist_ok=True)
    path = os.path.join(spec.out, f"{spec.name}-{spec.tag}-check.json")
    with open(path, "w") as f:
        json.dump(dict(ok=not rep.failed, failed=rep.failed, results=rep.rows, outputs=outputs), f, indent=1)
    return dict(ok=not rep.failed, failed=rep.failed, path=path, results=rep.rows, outputs=outputs)


def print_report(payload):
    rows = payload["results"]
    w = max(len(r["gate"]) for r in rows)
    for r in rows:
        print(f"{r['status']:<4}  {r['gate']:<{w}}  {r['msg']}")
    print(f"\n{'FAILED' if payload['failed'] else 'OK'} -> {payload['path']}")
