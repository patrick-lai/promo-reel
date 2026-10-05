"""Put the draft next to each reference: same time-normalised frames, same numbers, speech and sound included.

    promo compare-ref <draft.mp4> --project projects/<name> [--id REF] [--n 10] [--draft-people yes|no]

For each reference in brief.yaml writes, in `projects/<name>/out/compare/`:
    <ref-id>-vs-draft.png    reference row above, draft row below; frame k of n sits at (k+0.5)/n of each video's runtime
    <ref-id>-vs-draft.json   metrics + gaps        <ref-id>-vs-draft.md   the same as a table
Metrics: duration, cuts/s, median shot, integrated LUFS, tempo guess, speech present (y/n, word count, words/min),
people present (MANUAL: from `people:` on the reference in brief.yaml and `--draft-people`; the tool cannot see people).
`gaps` states facts only ("reference has speech (212 words), draft has none"); the Intent & Reference lens judges them.
Reference numbers come from its watch.json / transcript.json when present, otherwise they are measured the same way as the draft.
`transcribe` is injectable (tests); PROMO_WATCH_ASR=0 turns speech detection off (speech then reads `unknown`).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from . import brief as BR
from . import refs as RF
from . import watch as W


class CompareError(Exception):
    pass


def _speech(words):
    return None if words is None else dict(present=words > 0, words=words)


def measure(path, workdir, transcribe=None):
    """Metrics of a video the way `promo watch` would report them (no sheets): dict."""
    path = Path(path)
    info = W.probe(path)
    cuts = W.detect_cuts(path)
    bounds = [0.0] + cuts + [info["duration"]]
    lens = [b - a for a, b in zip(bounds, bounds[1:])]
    m = dict(duration=round(info["duration"], 2), n_cuts=len(cuts), cuts_per_s=round(len(cuts) / info["duration"], 3),
             median_shot=round(statistics.median(lens), 2), has_audio=info["audio"], lufs=None, tempo_bpm=None, words=None)
    if info["audio"]:
        wav = Path(workdir) / (path.stem + "-audio.wav")
        if W.extract_audio(path, wav):
            try:
                am = W.audio_metrics(wav)
                m["lufs"], m["tempo_bpm"] = am.get("lufs_integrated"), am.get("tempo_bpm")
            except Exception as e:      # noqa: BLE001
                m["audio_error"] = str(e)
            if os.environ.get("PROMO_WATCH_ASR", "1") != "0":
                tr = (transcribe or W.transcribe)(wav)
                if tr is not None:
                    m["words"] = sum(len(s.get("words") or []) or len((s.get("text") or "").split()) for s in tr.get("segments") or [])
    else:
        m["words"] = 0
    return m


def ref_metrics(project_dir, rid):
    """Reference metrics from its watch.json + transcript.json, or None if they are missing."""
    d = RF.ref_dir(project_dir, rid)
    w = RF._wj(d)
    if not w:
        return None
    sl, am = w.get("shot_len") or {}, w.get("audio_metrics") or {}
    words = RF.word_count(d)
    return dict(duration=round(w["duration"], 2), n_cuts=w.get("n_cuts"), cuts_per_s=sl.get("cuts_per_s"), median_shot=sl.get("median"),
                has_audio=bool(w.get("audio")), lufs=am.get("lufs_integrated"), tempo_bpm=am.get("tempo_bpm"),
                words=words if w.get("audio") else 0)


def sheet(ref_video, draft_video, out_png, n=10, thumb_w=320, ref_label="REFERENCE", draft_label="DRAFT"):
    """Two rows of n frames at the same fractions of each runtime."""
    rows = []
    for label, vid in ((ref_label, ref_video), (draft_label, draft_video)):
        dur = W.probe(Path(vid))["duration"]
        tmp = Path(tempfile.mkdtemp(prefix="cmpref-"))
        ims = []
        for k in range(n):
            frac = (k + 0.5) / n
            dst = tmp / f"{k:02d}.jpg"
            if W.grab(Path(vid), frac * dur, dst, thumb_w):
                ims.append((frac, frac * dur, Image.open(dst).convert("RGB")))
        if not ims:
            raise CompareError(f"no frames could be read from {vid}")
        rows.append((label, dur, ims))
    rh = [max(im.height for _, _, im in ims) for _, _, ims in rows]
    bar = 22
    W_ = n * thumb_w
    H = sum(h + bar for h in rh)
    canvas = Image.new("RGB", (W_, H), (12, 12, 14))
    dr = ImageDraw.Draw(canvas)
    y = 0
    for (label, dur, ims), h in zip(rows, rh):
        dr.rectangle([0, y, W_, y + bar], fill=(30, 30, 36))
        dr.text((6, y + 4), f"{label}  {dur:.1f} s   (frame k at (k+0.5)/{n} of the runtime)", fill=(255, 255, 255), font=W._font(14))
        y += bar
        for k, (frac, t, im) in enumerate(ims):
            canvas.paste(im, (k * thumb_w, y))
            dr.text((k * thumb_w + 4, y + 3), f"{frac * 100:3.0f}% {t:5.1f}s", fill=(255, 235, 120), font=W._font(12))
        y += h
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    canvas.save(out_png)
    return out_png


def gaps(ref, dr, ref_people=None, draft_people=None):
    g = []
    if ref.get("words") and not dr.get("words"):
        g.append(f"reference has speech ({ref['words']} words), draft has {'none' if dr.get('words') == 0 else 'unknown (no transcript)'}")
    if ref.get("has_audio") and not dr.get("has_audio"):
        g.append("reference has an audio track, draft has none")
    if ref.get("words") is None or dr.get("words") is None:
        g.append("speech could not be measured on one side (no ASR): read the reference transcript yourself")
    if ref.get("cuts_per_s") and dr.get("cuts_per_s") and not 0.5 <= dr["cuts_per_s"] / ref["cuts_per_s"] <= 2.0:
        g.append(f"cut rate {dr['cuts_per_s']}/s vs reference {ref['cuts_per_s']}/s (x{dr['cuts_per_s'] / ref['cuts_per_s']:.2f})")
    if ref.get("median_shot") and dr.get("median_shot") and not 0.5 <= dr["median_shot"] / ref["median_shot"] <= 2.0:
        g.append(f"median shot {dr['median_shot']} s vs reference {ref['median_shot']} s")
    if ref.get("lufs") is not None and dr.get("lufs") is not None and abs(ref["lufs"] - dr["lufs"]) > 6:
        g.append(f"loudness {dr['lufs']} LUFS vs reference {ref['lufs']} LUFS")
    if ref.get("tempo_bpm") and dr.get("tempo_bpm") and abs(dr["tempo_bpm"] - ref["tempo_bpm"]) / ref["tempo_bpm"] > 0.15:
        g.append(f"tempo guess {dr['tempo_bpm']} BPM vs reference {ref['tempo_bpm']} BPM (librosa guesses; confirm by ear)")
    if ref_people is True and draft_people is False:
        g.append("reference has people, draft has none")
    if ref_people is None or draft_people is None:
        g.append("people present: MANUAL, not set (`people:` on the reference in brief.yaml, `--draft-people yes|no`)")
    return g


def _yn(v):
    return {True: "yes", False: "no", None: "MANUAL"}[v]


def md(rid, ref, dr, g, png, ref_people, draft_people):
    sp = lambda m: "unknown" if m.get("words") is None else (f"yes, {m['words']} words" if m["words"] else "no")  # noqa: E731
    wpm = lambda m: "-" if not m.get("words") or not m.get("duration") else f"{m['words'] / m['duration'] * 60:.0f}"  # noqa: E731
    rows = [("duration (s)", ref["duration"], dr["duration"]), ("cuts / s", ref["cuts_per_s"], dr["cuts_per_s"]),
            ("median shot (s)", ref["median_shot"], dr["median_shot"]), ("integrated LUFS", ref["lufs"], dr["lufs"]),
            ("tempo guess (BPM)", ref["tempo_bpm"], dr["tempo_bpm"]), ("speech present", sp(ref), sp(dr)),
            ("words / min", wpm(ref), wpm(dr)), ("people present (manual)", _yn(ref_people), _yn(draft_people))]
    L = [f"# {rid} vs draft", "", f"![sheet]({os.path.basename(png)})", "", "| metric | reference | draft |", "|---|---|---|"]
    L += [f"| {a} | {b if b is not None else '-'} | {c if c is not None else '-'} |" for a, b, c in rows]
    L += ["", "## Gaps (facts, not verdicts)", ""] + ([f"- {x}" for x in g] or ["- none beyond the table"])
    return "\n".join(L) + "\n"


def compare(draft, project_dir, only=None, n=10, draft_people=None, transcribe=None, out_dir=None):
    """Build the sheet + metrics for every reference of the brief; returns {ok, results: [...]}."""
    if not os.path.isfile(draft):
        raise CompareError(f"draft not found: {draft}")
    b = BR.load(project_dir)
    refs = [r for r in b.get("references") or [] if not only or r.get("id") == only]
    if not refs:
        raise CompareError("brief.yaml lists no reference" + (f" {only!r}" if only else "") + ": `promo refs add` first")
    out = out_dir or os.path.join(project_dir, "out", "compare")
    os.makedirs(out, exist_ok=True)
    work = tempfile.mkdtemp(prefix="cmpref-m-")
    dm = measure(draft, work, transcribe)
    res = []
    for r in refs:
        rid = r["id"]
        rv = RF.video_of(project_dir, rid, b)
        if not rv:
            raise CompareError(f"reference {rid}: video not found (reference/{rid}/video.mp4 or the brief's path)")
        rm = ref_metrics(project_dir, rid) or measure(rv, work, transcribe)
        png = sheet(rv, draft, os.path.join(out, f"{rid}-vs-draft.png"), n, ref_label=f"REFERENCE {rid}")
        rp = r.get("people") if isinstance(r.get("people"), bool) else None
        g = gaps(rm, dm, rp, draft_people)
        rec = dict(ref=rid, reference=rm, draft=dm, people=dict(reference=rp, draft=draft_people), gaps=g, sheet=png,
                   draft_file=os.path.abspath(draft), reference_file=rv)
        json.dump(rec, open(os.path.join(out, f"{rid}-vs-draft.json"), "w"), indent=1)
        open(os.path.join(out, f"{rid}-vs-draft.md"), "w").write(md(rid, rm, dm, g, png, rp, draft_people))
        res.append(rec)
    return dict(ok=True, out=out, results=res)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="promo compare-ref", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft")
    ap.add_argument("--project", required=True)
    ap.add_argument("--id")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--draft-people", choices=("yes", "no"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        r = compare(a.draft, a.project, a.id, a.n, None if a.draft_people is None else a.draft_people == "yes")
    except (CompareError, BR.BriefError) as e:
        print(f"promo compare-ref: {e}", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(r, indent=1))
    else:
        for x in r["results"]:
            print(f"{x['ref']}: {x['sheet']}  ({len(x['gaps'])} gap(s))")
            for g in x["gaps"]:
                print(f"  - {g}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
