"""QA gates (`promo check`): exit 1 if any FAIL, WARN does not fail. Report table + out/<name>-<tag>-check.json."""
from __future__ import annotations

import hashlib
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
    r = subprocess.run(["ffmpeg", "-nostats", "-i", path, "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
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


def run(spec):
    rep = Report()
    qa = spec.raw.get("qa", {})
    hold_min = qa.get("min_caption_hold", 2.0)
    stamps = Stamps(spec.build)

    # 1. assets + lint (lint already ran at load)
    probs = A.validate(spec)
    rep.add("assets", "FAIL" if probs else "PASS", "; ".join(probs) if probs else "manifest complete; spec lint clean")
    from . import footage as FT
    try:
        bad = [r for r in FT.verify(spec) if not r["ok"]]
        rep.add("footage", "FAIL" if bad else "PASS", "; ".join(r["error"] for r in bad) if bad else f"{len(FT.referenced(spec))} referenced clips present, sha256 match")
        dpr_w, demo = FT.qa_findings(spec)
        rep.add("footage-dpr", "WARN" if dpr_w else "PASS", "; ".join(dpr_w) if dpr_w else "no soft-upscale risk (dpr >= 2 or push-in <= 1.5x)")
        rep.add("footage-demo", "WARN" if demo else "PASS", f"demo-mode footage in use: {', '.join(demo)}" if demo else "no demo-mode footage")
    except FT.FootageError as e:
        rep.add("footage", "FAIL", str(e))
    probs = spec.validate()
    rep.add("timeline", "FAIL" if probs else "PASS", "; ".join(probs) if probs else f"{len(spec.shots)} shots contiguous 0..{spec.timeline.beats} beats")

    # 5. beat grid
    sub = qa.get("beat_subdivision", 1)
    bad = [s.id for s in spec.shots if any(abs(b * sub - round(b * sub)) > 1e-9 for b in (s.b0, s.b1))]
    expect = round(spec.duration * spec.fps)
    tot = spec.total_frames()
    msgs = []
    if bad:
        msgs.append(f"shots off the beat grid: {bad}")
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
    rep.add("beat-grid", "FAIL" if msgs else "PASS", "; ".join(msgs) if msgs else f"all cuts on beats, {tot} frames, rendered segments match")

    # 2/3/4. per-output checks
    for m in spec.masters:
        out = spec.output_path(m.get("suffix", ""))
        nm = os.path.basename(out)
        if not os.path.exists(out):
            for g in ("duration", "video-format", "loudness"):
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

    # 7b. livestream layout: screen share, chat lines, single side move, keep-clear rectangles
    from . import livestream as LS
    for gate, status, msg in LS.check(spec, ctx):
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
            import faster_whisper  # noqa: F401
            have = True
        except ImportError:
            have = False
        if not have:
            rep.add("vo-script", "WARN", "skipped: faster-whisper not installed")
        else:
            meta = {str(x["shot"]): x for x in json.load(open(vj))["lines"]}
            bad, maxw_ = [], qa.get("vo_max_wer", 0.0)
            for ln in lines:
                sid = str(ln["shot"])
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
                ref_s = ln["text"]
                hyp_s = txt
                for k, v in (ln.get("asr_aliases") or {}).items():       # alias: heard-as -> script word
                    hyp_s = re.sub(re.escape(k), v, hyp_s, flags=re.I)
                w = wer(norm_words(ref_s), norm_words(hyp_s))
                if w > maxw_:
                    bad.append(f"{sid}: WER {w:.2f} (heard {txt!r})")
            rep.add("vo-script", "FAIL" if bad else "PASS", "; ".join(bad) if bad else f"{len(lines)} lines match the script (WER <= {maxw_})")

    # 10. stale check: steps whose stamped input digest no longer matches (same logic as `promo status`)
    from .cli import cmd_status
    stale = [f"{x['step']}" for x in cmd_status(spec, None)["steps"] if x["status"] == "stale"]
    rep.add("stale", "WARN" if stale else "PASS", f"stale (rebuild needed): {', '.join(stale)}" if stale else "no stale steps (missing steps are reported by the other gates)")

    os.makedirs(spec.out, exist_ok=True)
    path = os.path.join(spec.out, f"{spec.name}-{spec.tag}-check.json")
    with open(path, "w") as f:
        json.dump(dict(ok=not rep.failed, failed=rep.failed, results=rep.rows), f, indent=1)
    return dict(ok=not rep.failed, failed=rep.failed, path=path, results=rep.rows)


def print_report(payload):
    rows = payload["results"]
    w = max(len(r["gate"]) for r in rows)
    for r in rows:
        print(f"{r['status']:<4}  {r['gate']:<{w}}  {r['msg']}")
    print(f"\n{'FAILED' if payload['failed'] else 'OK'} -> {payload['path']}")
