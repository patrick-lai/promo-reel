"""Study the reference for real: watch it, hear it, read it, then write the dossier. No dossier, no spec.

    promo refs add <url|file> --project projects/<name> [--id ID] [--why "the user's words"] [--force]
    promo refs check [--project projects/<name>]
    promo refs show  --project projects/<name> [--id ID]

`add` runs `promo.watch` WITH the transcript (unless PROMO_WATCH_ASR=0 is set explicitly, which only WARNs here and makes
`check` FAIL until a transcript exists) into `projects/<name>/reference/<id>/` (sheets/, cuts/, audio.wav, transcript.json,
watch.json, WATCH.md) and scaffolds `DOSSIER.md` there. Every required section starts with a `TODO:` line the agent must
replace with what it actually saw and heard. It also lists the reference in brief.yaml (empty `why` until the user's words
are put in, so `promo brief check` stays red).

`check` (the `references` gate of `promo check`) FAILs when a reference listed in brief.yaml has no dossier, a `TODO:` is left,
a section is empty, the artefacts (contact sheets, transcript, audio metrics) are missing, an "Evidence read" box is
unticked, or a NOT-transferable item has no matching `conflicts` entry (`ref: <id>`) in brief.yaml.

A dossier is a reading record, not a style preset: the agent's own summary of a reference never replaces the reference.
"""
from __future__ import annotations

import json
import os
import re
import sys

from . import brief as BR

# (key, heading, guidance). Headings are matched by their text, numbering is cosmetic.
SECTIONS = [
    ("narrative", "Narrative beats", "What happens, in order, with timestamps (mm:ss). One line per beat. Read every contact sheet and the cut stills."),
    ("people", "People & performance", "Are there humans? What do they do, say, feel? Eyes, hands, bodies, acting. Say 'none' only if you looked at every sheet."),
    ("dialogue", "Dialogue/VO", "Verbatim lines from transcript.json with timestamps and speaker if known. If there is no speech, say so and quote the transcript's emptiness."),
    ("sound", "Music & sound design", "Genre, tempo, build/drops, SFX, room tone, silence, how sound leads or follows picture; LUFS and rms curve from the audio metrics."),
    ("camera", "Camera & motion", "Moves, speed, lens/depth of field, handheld vs locked, how each cut is motivated (action, sound, eyeline)."),
    ("grade", "Grade & light", "Palette, contrast, practical vs. soft light, time of day, colour temperature, grain."),
    ("text", "On-screen text & graphics", "Titles, captions, UI, logos: what, where, how long, in what type. 'None' is a valid answer."),
    ("pacing", "Pacing numbers", "Cuts/s, median shot, cut-rate curve, holds, from watch.json (see the data comment), plus what the numbers feel like."),
    ("one_thing", "The ONE thing that makes it work", "One sentence. If you need two, you have not found it."),
    ("transferable", "What is transferable to this product", "Specific moves/qualities that can be done with real footage of this product. Name the shot you would shoot."),
    ("not_transferable", "What is NOT transferable and why",
     "One bullet per item (`- ...`); each becomes a `conflicts` entry in brief.yaml (`promo brief conflict add --ref <id>`) that the USER decides. "
     "E.g. people/dialogue vs 'real footage only'. Write `- none: <why>` only if truly nothing."),
    ("evidence", "Evidence read", None),
]
STILLS_MIN = 6


class RefsError(Exception):
    pass


def ref_dir(project_dir, rid):
    return os.path.join(project_dir, "reference", rid)


def slug(src):
    m = re.search(r"(?:v=|youtu\.be/)([\w-]{6,})", src)
    s = m.group(1) if m else os.path.splitext(os.path.basename(src.rstrip("/")))[0] or "ref"
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-").lower()[:40] or "ref"


def _wj(d):
    p = os.path.join(d, "watch.json")
    return json.load(open(p)) if os.path.isfile(p) else None


def word_count(d):
    p = os.path.join(d, "transcript.json")
    if not os.path.isfile(p):
        return None
    segs = (json.load(open(p)) or {}).get("segments") or []
    return sum(len(s.get("words") or []) or len((s.get("text") or "").split()) for s in segs)


def video_of(project_dir, rid, b=None):
    """The reference video file: reference/<id>/video.mp4, else watch.json's source, else the brief's path."""
    d = ref_dir(project_dir, rid)
    p = os.path.join(d, "video.mp4")
    if os.path.isfile(p):
        return p
    w = _wj(d)
    if w and os.path.isfile(w.get("source", "")):
        return w["source"]
    for r in (b or (BR.load(project_dir) if BR.exists(project_dir) else {})).get("references") or []:
        if r.get("id") == rid and r.get("path") and os.path.isfile(r["path"]):
            return r["path"]
    return None


# ---------------------------------------------------------------- scaffold
def scaffold(project_dir, rid, src, why, w):
    d = ref_dir(project_dir, rid)
    sheets = sorted(os.listdir(os.path.join(d, "sheets"))) if os.path.isdir(os.path.join(d, "sheets")) else []
    cuts = sorted(os.listdir(os.path.join(d, "cuts"))) if os.path.isdir(os.path.join(d, "cuts")) else []
    am = (w or {}).get("audio_metrics") or {}
    sl = (w or {}).get("shot_len") or {}
    nwords = word_count(d)
    has_audio = bool((w or {}).get("audio"))
    data = {
        "pacing": f"duration {w.get('duration')} s; {w.get('n_cuts')} cuts; cuts/s {sl.get('cuts_per_s')}; shot mean {sl.get('mean')} median {sl.get('median')} "
                  f"min {sl.get('min')} max {sl.get('max')}; cut-rate curve per fifth {w.get('cut_rate_curve')}; motion/s {w.get('motion_per_s')}" if w else "",
        "sound": f"LUFS {am.get('lufs_integrated')}; peak {am.get('peak_dbfs')} dBFS; tempo guess {am.get('tempo_bpm')} BPM; rms curve per 2 s {am.get('rms_curve_2s')}" if am else "no audio metrics",
        "dialogue": f"transcript.json: {nwords} words" if nwords is not None else "NO transcript.json (ASR missing or PROMO_WATCH_ASR=0): get one before filling this",
    }
    L = [f"# DOSSIER: {rid}", "",
         f"- source: {src}", f"- why the user gave it (their words): {why or '(empty: fill brief.yaml references[].why)'}",
         f"- artefacts: `{os.path.relpath(d)}/` (WATCH.md, watch.json, sheets/, cuts/, audio.wav, transcript.json)",
         f"- {w.get('width')}x{w.get('height')} @ {w.get('fps', 0):.2f} fps, {w.get('duration')} s, audio {'yes' if has_audio else 'no'}" if w else "- (watch.json missing)",
         "", "Rules: replace every TODO line with what you actually saw and heard (timestamps, quotes). Do not summarise the",
         "reference into a style name. Do not tick an Evidence box you did not do. A reference that is live action with people,",
         "dialogue and sound design is not a 'look'.", ""]
    for i, (key, head, guide) in enumerate(SECTIONS, 1):
        L += [f"## {i}. {head}", ""]
        if key == "evidence":
            L += ["TODO: tick each box only after doing it, and list the files you opened.", ""]
            for s in sheets:
                L.append(f"- [ ] contact sheet read: sheets/{s}")
            if has_audio:
                L.append("- [ ] transcript.json read in full" + (f" ({nwords} words)" if nwords is not None else ""))
                L.append("- [ ] audio read: listened to audio.wav (or read the audio metrics + rms curve) and noted music/SFX/silence")
            else:
                L.append("- [x] no audio track in this reference (ffprobe)")
            n = min(STILLS_MIN, len(cuts))
            L.append(f"- [ ] {n} full-res stills examined (name them here, cuts/cut-NNN.jpg): ")
        else:
            L += [f"TODO: {guide}", ""]
            if data.get(key):
                L += [f"<!-- data (auto): {data[key]} -->", ""]
    open(os.path.join(d, "DOSSIER.md"), "w").write("\n".join(L) + "\n")
    return os.path.join(d, "DOSSIER.md")


def add(src, project_dir, rid=None, why="", force=False, watch_fn=None):
    """Watch `src` into reference/<id>/, scaffold DOSSIER.md, list it in brief.yaml. `watch_fn(src, out)` is injectable."""
    if watch_fn is None:
        from . import watch
        watch_fn = lambda s, o: watch.run(s, o)       # noqa: E731
    rid = rid or slug(src)
    d = ref_dir(project_dir, rid)
    dossier = os.path.join(d, "DOSSIER.md")
    if os.path.exists(dossier) and not force:
        raise RefsError(f"{dossier} exists (use --force to re-watch and re-scaffold; your notes would be overwritten)")
    warnings = []
    asr_off = os.environ.get("PROMO_WATCH_ASR") == "0"
    if asr_off:
        warnings.append("PROMO_WATCH_ASR=0: no transcript. `promo refs check` FAILs until transcript.json exists "
                        "(dialogue is half of a live-action reference).")
    os.makedirs(d, exist_ok=True)
    watch_fn(src, d)
    w = _wj(d)
    if w is None:
        raise RefsError(f"watch produced no watch.json in {d}")
    if w.get("audio") and not os.path.isfile(os.path.join(d, "transcript.json")) and not asr_off:
        warnings.append("no transcript.json: ASR is not installed (pip install faster-whisper) or found no engine; "
                        "write transcript.json by hand (engine: manual) after listening, or the check will FAIL.")
    b = BR.load(project_dir) if BR.exists(project_dir) else None
    if b is not None:
        refs_ = b.setdefault("references", [])
        ent = next((r for r in refs_ if r.get("id") == rid), None)
        if ent is None:
            ent = {"id": rid, ("url" if re.match(r"https?://", src) else "path"): src, "why": ""}
            refs_.append(ent)
        if why:
            ent["why"] = why
        BR.save(project_dir, b)
        why = ent.get("why", "")
    else:
        warnings.append(f"no brief.yaml: run `promo brief init --project {project_dir}` with the user's exact words, then list this reference.")
    path = scaffold(project_dir, rid, src, why, w)
    return dict(id=rid, dir=d, dossier=path, sheets=len(w.get("sheets") or []), cuts=w.get("n_cuts"), words=word_count(d), warnings=warnings)


# ---------------------------------------------------------------- check
def parse_sections(text):
    """{key: body} by heading text; also returns the list of headings found."""
    parts = re.split(r"^##\s+", text, flags=re.M)[1:]
    out = {}
    for p in parts:
        head, _, body = p.partition("\n")
        h = re.sub(r"^\d+\.\s*", "", head).strip().lower()
        for key, title, _g in SECTIONS:
            if h.startswith(title.lower()):
                out[key] = body
    return out


def _strip(body):
    return re.sub(r"<!--.*?-->", "", body, flags=re.S).strip()


def dossier_problems(project_dir, rid, b=None):
    """[str]: everything wrong with one reference's dossier + artefacts (empty = complete)."""
    d = ref_dir(project_dir, rid)
    P = []
    p = os.path.join(d, "DOSSIER.md")
    if not os.path.isfile(p):
        return [f"{rid}: no dossier ({os.path.relpath(p)}): `promo refs add <url|file> --project {project_dir} --id {rid}`"]
    txt = open(p).read()
    if "TODO:" in txt:
        n = txt.count("TODO:")
        P.append(f"{rid}: {n} `TODO:` marker(s) left in DOSSIER.md")
    secs = parse_sections(txt)
    for key, title, _g in SECTIONS:
        if key not in secs:
            P.append(f"{rid}: section missing: {title}")
        elif key != "evidence" and len(_strip(secs[key]).split()) < 4 and "TODO:" not in secs[key]:
            P.append(f"{rid}: section '{title}' is empty")
    # artefacts: sheets, transcript / audio
    w = _wj(d)
    if w is None:
        P.append(f"{rid}: watch.json missing (run `promo refs add`)")
    else:
        sheets = [s for s in (w.get("sheets") or []) if os.path.isfile(os.path.join(d, s))]
        if not sheets:
            P.append(f"{rid}: contact sheets missing (sheets/sheet-NN.png)")
        if w.get("audio"):
            if not w.get("audio_metrics"):
                P.append(f"{rid}: audio metrics missing in watch.json ({w.get('audio_metrics_error', 'soundfile/librosa not installed?')})")
            if not os.path.isfile(os.path.join(d, "transcript.json")):
                P.append(f"{rid}: transcript.json missing (needs ASR; or write it by hand with engine: manual after listening)")
            if not os.path.isfile(os.path.join(d, "audio.wav")):
                P.append(f"{rid}: audio.wav missing")
    # evidence boxes
    ev = secs.get("evidence", "")
    boxes = re.findall(r"^\s*-\s*\[( |x|X)\]\s*(.*)$", ev, flags=re.M)
    if not boxes:
        P.append(f"{rid}: Evidence read has no checklist")
    unticked = [t for c, t in boxes if c == " "]
    if unticked:
        P.append(f"{rid}: {len(unticked)} Evidence read box(es) unticked: {unticked[0][:60]}")
    for c, t in boxes:
        if c != " " and "full-res stills" in t:
            need = int(re.match(r"\s*(\d+)", t).group(1)) if re.match(r"\s*(\d+)", t) else 0
            named = len(set(re.findall(r"cut-\d+", t)))
            if named < need:
                P.append(f"{rid}: evidence says {need} stills examined but names {named} (cuts/cut-NNN.jpg)")
    # NOT transferable -> conflicts
    nt = [l.strip()[2:].strip() for l in _strip(secs.get("not_transferable", "")).splitlines() if l.strip().startswith("- ")]
    nt = [x for x in nt if x and not x.lower().startswith("none")]
    if nt and "TODO:" not in secs.get("not_transferable", ""):
        confl = [c for c in ((b or {}).get("conflicts") or []) if c.get("ref") == rid]
        if len(confl) < len(nt):
            P.append(f"{rid}: {len(nt)} NOT-transferable item(s) but {len(confl)} conflict(s) with ref: {rid} in brief.yaml "
                     f"(`promo brief conflict add --ref {rid} --what ... --rule ...`, then the user decides)")
    return P


def check(project_dir, b=None):
    """[(gate, status, msg)] for the `references` gate."""
    b = b if b is not None else (BR.load(project_dir) if BR.exists(project_dir) else None)
    if b is None:
        return [("references", "FAIL", "no brief.yaml")]
    refs_ = b.get("references") or []
    if not refs_:
        return [("references", "WARN", "brief.yaml lists no references (fine only if the user gave none; otherwise `promo refs add`)")]
    probs = []
    for r in refs_:
        probs += dossier_problems(project_dir, r.get("id") or "?", b)
    if probs:
        return [("references", "FAIL", "; ".join(probs))]
    return [("references", "PASS", f"{len(refs_)} reference dossier(s) complete: " + ", ".join(r["id"] for r in refs_))]


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="promo refs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a_ = sub.add_parser("add", help="watch a reference (with transcript) and scaffold its dossier")
    a_.add_argument("src")
    a_.add_argument("--project", required=True)
    a_.add_argument("--id")
    a_.add_argument("--why", default="", help="the user's own words about this reference")
    a_.add_argument("--force", action="store_true")
    c_ = sub.add_parser("check", help="dossier completeness for every reference in brief.yaml")
    c_.add_argument("--project", required=True)
    c_.add_argument("--json", action="store_true")
    s_ = sub.add_parser("show", help="print the dossier(s)")
    s_.add_argument("--project", required=True)
    s_.add_argument("--id")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "add":
            r = add(a.src, a.project, a.id, a.why, a.force)
            print(f"reference {r['id']}: {r['dir']}  ({r['sheets']} sheets, {r['cuts']} cuts, {'no transcript' if r['words'] is None else str(r['words']) + ' words transcribed'})")
            print(f"dossier to fill: {r['dossier']}")
            for w in r["warnings"]:
                print(f"WARN  {w}", file=sys.stderr)
        elif a.cmd == "check":
            rows = check(a.project)
            if a.json:
                print(json.dumps(dict(ok=not any(s == "FAIL" for _, s, _ in rows), results=[dict(gate=g, status=s, msg=m) for g, s, m in rows]), indent=1))
            else:
                for g, s, m in rows:
                    print(f"{s:<4}  {g}  {m.replace('; ', chr(10) + '      ')}")
            return 1 if any(s == "FAIL" for _, s, _ in rows) else 0
        else:
            ids = [a.id] if a.id else [r["id"] for r in BR.load(a.project).get("references") or []]
            for rid in ids:
                p = os.path.join(ref_dir(a.project, rid), "DOSSIER.md")
                print(open(p).read() if os.path.isfile(p) else f"(no dossier for {rid})")
    except (RefsError, BR.BriefError) as e:
        print(f"promo refs: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
