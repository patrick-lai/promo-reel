"""`promo` command line. Global options: -p/--project promo.yaml, --scale {1,2}, --force, -v.

`--json` (check, status, timeline, assets, compare, footage verify/list): the JSON payload (always with `ok`) goes to
stdout ONLY; all progress/logging goes to stderr, so the CLI can be wrapped (e.g. as an MCP server) without parsing noise.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import sys
import time

from . import assets as A
from . import footage as FT
from .cache import PKG, Stamps, code_hash, digest, file_sig
from .spec import SpecError, load_spec

QA_ONLY_KEYS = ("named", "contact_at")
AUDIO_KEYS = ("audio",)         # shot `audio:` lines only change the clip-audio / events / mix steps, never the rendered picture
SHOT_CODE = ["render", "overlays", "spec", "footage", "shots/__init__", "shots/clip", "shots/card", "shots/livestream", "livestream", "live2d"]


def log(args, *a):
    if getattr(args, "verbose", False):
        print(*a, file=sys.stderr)


# ---------------------------------------------------------------- steps: plan (key, digest, outputs) + run
def shot_digest(spec, shot):
    clips = {cid: FT.verified_sha(spec, cid) for cid in sorted(FT.referenced(spec, {shot.id})) if os.path.exists(FT.clip_path(spec, cid))}
    plates = {k: v for k, v in (spec.raw.get("plates") or {}).items()}
    code = SHOT_CODE + (["shots/anime", "styles", "claims"] if shot.type == "anime" else [])
    if shot.type == "cinema":       # look defaults / serif fonts / claims come from the resolved preset
        code = code + ["shots/cinema", "grade", "pane3d", "styles", "claims"]
    if shot.type == "screen":       # cinema's copy / look code + the monitor tracker + the warp
        code = code + ["shots/screen", "screentrack", "shots/cinema", "grade", "styles", "claims"]
    extra = [spec.style, spec.raw.get("claims")] if shot.type in ("cinema", "screen") else []
    if shot.type == "anime":        # card text can come from claims tables; the band/typography from the resolved preset
        extra = [spec.style, spec.raw.get("claims"), spec.timeline.bpm]
    if shot.type in ("horizon", "dawn"):    # the show-level horizon_text layer (drawn into every horizon shot) + the resolved preset
        code = code + ["shots/horizon", "shots/brand", "pane3d", "styles"]
        extra = [spec.style, spec.raw.get("horizon_text"), spec.timeline.bpm]
    cfg = {k: v for k, v in shot.cfg.items() if k not in QA_ONLY_KEYS + AUDIO_KEYS}      # QA-only / audio-only keys never force a re-render
    return digest(cfg, shot.n, spec.raw.get("style"), plates, spec.scale, spec.fps, clips, spec.raw.get("livestream"),
                  os.environ.get("PROMO_DEBUG") == "1",
                  code_hash(*code, extra_files=spec.plugins), *extra)


def _sfx_outputs(spec):
    from . import sfx
    return [os.path.join(spec.sfx_dir, f"{n}.wav") for n in sfx.NAMES]


def plan(spec):
    """Ordered build steps: dicts(name, key, dig() -> str, outputs, run(args), deps). `dig` is lazy (may hash big files)."""
    from . import assemble, contact, events, mix, music, vo
    from .events import events_path
    from .music import music_path
    from .render import RenderContext
    from .shots import get_type
    steps = []

    def add(name, key, dig, outputs, run, deps=()):
        steps.append(dict(name=name, key=key, dig=dig, outputs=outputs, run=run, deps=list(deps)))

    add("sfx", "sfx", lambda: digest(code_hash("sfx")), _sfx_outputs(spec), lambda a: __import__("promo.sfx", fromlist=["x"]).run(spec, force=True))
    if spec.raw.get("vo"):
        def vo_dig():
            cfg, man = spec.raw["vo"], A.load_manifest(spec)
            if cfg.get("engine") == "files":
                return digest([[vo.line_id(l), l["shot"], l["text"], l.get("sha256"), file_sig(vo.line_file(spec, l, man))] for l in cfg["lines"]],
                              code_hash("vo"))
            # only what changes the audio: engine/voice/lang/speed + each line's shot/text/tts (not `at` / `asr_aliases`)
            cfg = dict({k: v for k, v in cfg.items() if k != "lines"}, lines=[[l["shot"], l["text"], l.get("tts")] for l in cfg["lines"]])
            models = {k: file_sig(A.asset_path(spec, cfg[k], man)) for k in ("model_asset", "voices_asset")}
            return digest(cfg, models, code_hash("vo"))
        add("vo", "vo", vo_dig, [vo.vo_json_path(spec)], lambda a: vo.run(spec))
    from . import shot_audio
    if shot_audio.has_lines(spec):                  # shot `audio:` lines: clip soundtrack extracted + normalised (cheap; picture untouched)
        add("clip-audio", "clip_audio", lambda: digest(shot_audio.digest_parts(spec), code_hash("shot_audio")),
            shot_audio.outputs(spec), lambda a: shot_audio.run(spec))
    if spec.raw.get("music"):                       # optional (a talk show may run without a music bed)
        add("music", "music", lambda: digest(spec.raw["music"], spec.raw.get("timeline"), file_sig(A.asset_path(spec, spec.raw["music"]["asset"])), code_hash("music")),
            [music_path(spec)], lambda a: music.run(spec))

    def shot_run(shot):
        def go(a):
            ctx = RenderContext.from_spec(spec)
            os.makedirs(spec.segs_dir, exist_ok=True)
            edl = get_type(shot.type).render(ctx, shot)
            with open(os.path.join(spec.segs_dir, f"{shot.id}.edl.json"), "w") as f:
                json.dump(edl, f, indent=1)
        return go
    for s in spec.shots:
        add(f"shot {s.id}", f"shot_{s.id}_{spec.OW}", (lambda s=s: shot_digest(spec, s)), [spec.seg_path(s.id)], shot_run(s))
    # QA-only shot keys (named boxes, contact_at) never make the events step stale (same rule as shot_digest)
    qa_free_shots = lambda: [{k: v for k, v in sh.items() if k not in QA_ONLY_KEYS} if isinstance(sh, dict) else sh
                             for sh in (spec.raw.get("shots") or [])] if spec.raw.get("shots") is not None else None
    add("events", "events", lambda: digest(qa_free_shots(), spec.raw.get("vo", {}).get("lines"), spec.raw.get("timeline"), spec.fps,
                                          code_hash("events", "spec", "shots/clip", "shot_audio", extra_files=spec.plugins)),
        [events_path(spec)], lambda a: events.write_events(spec))

    def mix_dig():
        man = A.load_manifest(spec)
        lib = spec.raw.get("sfx", {}).get("library", {})
        sfx_sigs = {n: file_sig(A.asset_path(spec, e["asset"], man)) for n, e in lib.items() if e.get("asset")}
        vj = os.path.join(spec.vo_dir, "vo.json")
        vo_sigs = {l["file"]: file_sig(os.path.join(spec.vo_dir, l["file"])) for l in json.load(open(vj))["lines"]} if os.path.exists(vj) else {}
        clip_sigs = {l["id"]: file_sig(l["file"]) for l in shot_audio.lines(spec)}
        return digest(spec.raw.get("mix"), spec.raw.get("sfx"), spec.duration, file_sig(events_path(spec)), clip_sigs,
                      file_sig(music_path(spec)) if spec.raw.get("music") else None,
                      file_sig(vj), vo_sigs, sfx_sigs, code_hash("mix"))
    add("mix", "mix", mix_dig, [mix.master_path(spec, m["name"]) for m in spec.masters], lambda a: mix.run(spec),
        deps=["sfx", "vo", "events"] + (["clip-audio"] if shot_audio.has_lines(spec) else []) + (["music"] if spec.raw.get("music") else []))
    outs = [spec.output_path(m.get("suffix", "")) for m in spec.masters]
    add("assemble", f"assemble_{spec.OW}",
        lambda: digest({s.id: file_sig(spec.seg_path(s.id)) for s in spec.shots}, {m["name"]: file_sig(mix.master_path(spec, m["name"])) for m in spec.masters},
                       spec.raw.get("mix", {}).get("masters"), spec.duration, spec.name, code_hash("assemble")),
        outs, lambda a: assemble.run(spec), deps=[f"shot {s.id}" for s in spec.shots] + ["mix"])
    add("contact", f"contact_{spec.OW}", lambda: digest(file_sig(outs[0]), [s.get("contact_at") for s in spec.shots], spec.title, code_hash("contact")),
        [contact.contact_paths(spec)[0]], lambda a: contact.run(spec), deps=["assemble"])
    return steps


def run_step(spec, args, st):
    stamps = Stamps(spec.build)
    dig = st["dig"]()
    if not args.force and stamps.is_fresh(st["key"], dig, st["outputs"]):
        print(f"skip  {st['name']} (unchanged)")
        return False
    t0 = time.time()
    print(f"run   {st['name']}", flush=True)
    st["run"](args)
    stamps.write(st["key"], dig, at=time.time(), secs=round(time.time() - t0, 1))
    return True


def _step(spec, args, name):
    run_step(spec, args, next(s for s in plan(spec) if s["name"] == name))


def do_build(spec, args):
    A.gate(spec)
    errs = spec.validate()
    if errs:
        raise SpecError("; ".join(errs))
    FT.gate(spec, set(args.shots) if args.shots else None)
    for st in plan(spec):
        if args.shots and st["name"].startswith("shot ") and st["name"][5:] not in args.shots:
            continue
        if args.shots and st["name"] in ("assemble", "contact"):
            print("partial build (--shots): skipping assemble/contact")
            break
        run_step(spec, args, st)


def cmd_status(spec, args):
    """Per-step up-to-date / stale / missing (no work is done)."""
    steps, state = [], {}
    stamps = Stamps(spec.build)
    probs = A.validate(spec)
    steps.append(dict(step="assets", status="missing" if probs else "up-to-date", detail="; ".join(probs) or "manifest complete"))
    try:
        vr = FT.verify(spec)
        bad = [r for r in vr if not r["ok"]]
        status = "up-to-date" if not bad else ("missing" if any(not r["exists"] for r in bad) else "stale")
        steps.append(dict(step="footage", status=status, detail="; ".join(r["error"] for r in bad) or f"{len(vr)} clips verified"))
    except SpecError as e:
        steps.append(dict(step="footage", status="missing", detail=str(e)))
    for st in plan(spec):
        exists = all(os.path.exists(o) for o in st["outputs"])
        try:
            dig = st["dig"]()
            fresh = stamps.is_fresh(st["key"], dig, st["outputs"])
        except Exception as e:  # noqa: BLE001  (inputs not available yet)
            dig, fresh = None, False
        if not exists:
            status, detail = "missing", "output not built"
        elif fresh:
            status, detail = "up-to-date", ""
        else:
            status, detail = "stale", "inputs changed since the last build" if dig else "inputs unavailable"
        up = [d for d in st["deps"] if state.get(d) in ("stale", "missing")]
        if status == "up-to-date" and up:
            status, detail = "stale", f"upstream not current: {', '.join(up)}"
        state[st["name"]] = status
        steps.append(dict(step=st["name"], status=status, detail=detail, outputs=st["outputs"]))
    outputs = {m["name"]: dict(path=spec.output_path(m.get("suffix", "")), exists=os.path.exists(spec.output_path(m.get("suffix", "")))) for m in spec.masters}
    from . import contact
    png = contact.contact_paths(spec)[0]
    outputs["contact"] = dict(path=png, exists=os.path.exists(png))
    outputs["edl"] = dict(path=os.path.join(spec.out, "EDL.md"), exists=os.path.exists(os.path.join(spec.out, "EDL.md")))
    return dict(ok=all(s["status"] == "up-to-date" for s in steps), project=spec.path, scale=spec.scale, resolution=f"{spec.OW}x{spec.OH}",
                steps=steps, outputs=outputs)


def print_status(r):
    w = max(len(s["step"]) for s in r["steps"])
    for s in r["steps"]:
        print(f"{s['status']:<10} {s['step']:<{w}}  {s['detail']}")
    for k, o in r["outputs"].items():
        print(f"{'exists' if o['exists'] else 'absent':<10} {k:<{w}}  {o['path']}")


def cmd_timeline(spec, args):
    shots = [dict(id=s.id, type=s.type, beats=[s.b0, s.b1], start=round(s.t0, 3), end=round(s.t1, 3), duration=round(s.t1 - s.t0, 3), frames=s.n) for s in spec.shots]
    tot = spec.total_frames()
    return dict(ok=not spec.validate() and tot == round(spec.duration * spec.fps), title=spec.title, bpm=spec.timeline.bpm, beats=spec.timeline.beats,
                fps=spec.fps, resolution=f"{spec.OW}x{spec.OH}", shots=shots, total_frames=tot, problems=spec.validate())


def print_timeline(r):
    print(f"{r['title']}: {r['bpm']} BPM, {r['beats']} beats, {r['fps']} fps, {r['resolution']}")
    print(f"{'id':>4} {'type':<12} {'beats':>9} {'start':>7} {'end':>7} {'dur':>6} {'frames':>6}")
    for s in r["shots"]:
        print(f"{s['id']:>4} {s['type']:<12} {s['beats'][0]:>4}-{s['beats'][1]:<4} {s['start']:7.3f} {s['end']:7.3f} {s['duration']:6.2f} {s['frames']:6d}")
    print("total frames", r["total_frames"])


def cmd_assets(spec, args):
    probs = A.validate(spec)
    return dict(ok=not probs, assets=A.rows(spec) if not any("not found" in p for p in probs) else [], problems=probs)


def print_assets(r, spec):
    if r["assets"]:
        print(A.table(spec))
    for p in r["problems"]:
        print("PROBLEM:", p)


def cmd_footage(spec, args):
    if args.fcmd == "verify":
        res = FT.verify(spec)
        return dict(ok=all(r["ok"] for r in res), clips=res)
    if args.fcmd == "list":
        man = FT.load(spec)
        refs = FT.referenced(spec)
        clips = [dict(c, referenced_by=refs.get(cid, []), exists=os.path.exists(c["path"])) for cid, c in man.items()]
        return dict(ok=True, manifest=FT.manifest_path(spec), clips=clips)
    if args.fcmd == "add":
        e = FT.add(spec, args.path, args.id, shots=args.shots, commit=args.commit, capture=args.capture, framing=args.framing, dpr=args.dpr,
                   notes=args.notes, demo=args.demo, captured_at=args.captured_at)
        return dict(ok=True, clip=e, manifest=FT.manifest_path(spec))


def print_footage(args, r):
    if args.fcmd == "verify":
        for c in r["clips"]:
            print(f"{'ok  ' if c['ok'] else 'FAIL'} {c['id']:<22} shots {','.join(c['shots']):<8} {c['error'] or c['path']}")
    elif args.fcmd == "list":
        for c in r["clips"]:
            print(f"{c['id']:<22} {c.get('resolution', '?'):<10} dpr {c.get('dpr', '?')}  {c['app_commit'][:8] if c.get('app_commit') else '?'}  shots {','.join(c['referenced_by']) or '-':<8} {'demo ' if c.get('demo') else ''}{c['path']}")
    else:
        print(f"updated {r['manifest']}: {r['clip']['id']} sha256 {r['clip']['sha256']}")


def cmd_new(args):
    root = os.path.dirname(PKG)
    src = os.path.join(root, "templates", "new-project")
    if not os.path.isdir(src):
        raise SystemExit(f"template not found: {src}")
    name = os.path.basename(os.path.normpath(args.name))
    from . import home as _home
    dest = args.dir or (args.name if os.sep in args.name else os.path.join(_home.projects_dir(), args.name))
    if os.path.exists(dest) and os.listdir(dest):
        raise SystemExit(f"{dest} exists and is not empty")
    shutil.copytree(src, dest, dirs_exist_ok=True)
    style = getattr(args, "style", None) or "hero"
    from . import styles as STY
    if style not in STY.PRESETS:
        raise SystemExit(f"unknown style {style!r}; have {STY.names()}")
    sdir = os.path.join(root, "templates", "styles", style)
    if os.path.isdir(sdir):          # style overlay: promo.yaml (+ assets.yaml, shots docs) for this preset
        shutil.copytree(sdir, dest, dirs_exist_ok=True)
    for f in ("promo.yaml", "assets.yaml", "footage/manifest.yaml", "footage/manifest.md"):
        p = os.path.join(dest, f)
        t = open(p).read().replace("my-promo", name)
        open(p, "w").write(t)
    for d in ("media/music", "media/models"):
        os.makedirs(os.path.join(dest, d), exist_ok=True)
    print(f"created {dest} (style {style}): fill footage/manifest.yaml (+ manifest.md), assets.yaml, promo.yaml, then `promo -p {dest}/promo.yaml timeline`")


def cmd_styles():
    from . import styles as STY
    return dict(ok=True, presets={k: dict(v) for k, v in STY.PRESETS.items()})


def print_styles(r):
    for name, p in r["presets"].items():
        print(f"{name:<14} {p['description']}")
        print(f"{'':<14} pacing: {p['pacing']}")
        print(f"{'':<14} transitions: {p['transitions']['allowed']}  checks: {', '.join(p['checks'])}")
    print("\nscaffold with `promo new <name> --style <preset>`; override any key under style: in promo.yaml")


def cmd_grid(spec, args):
    g = spec.grid
    if not g:
        return dict(ok=False, error="no timeline.grid in this spec")
    return dict(ok=True, bpm=g.bpm, beat_s=g.B, beats_per_bar=g.beats_per_bar, bar_s=g.B * g.beats_per_bar, markers=g.markers,
                bars=g.table(), timeline_beats=spec.timeline.beats)


def print_grid(r):
    if not r["ok"]:
        print(r["error"])
        return
    print(f"{r['bpm']:g} BPM, beat {r['beat_s']:.6f}s, bar {r['bar_s']:.4f}s ({r['beats_per_bar']} beats); timeline {r['timeline_beats']} beats")
    print(f"{'bar':>4} {'beat':>5} {'t (s)':>8}  phrase  markers")
    for b in r["bars"]:
        print(f"{b['bar']:>4} {b['beat']:>5} {b['t']:8.3f}  {'*' if b['phrase'] else ' ':^6}  {', '.join(b['markers'])}")


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    S = argparse.SUPPRESS
    common.add_argument("-p", "--project", default=S, help="path to promo.yaml (default ./promo.yaml)")
    common.add_argument("--scale", type=float, choices=(0.5, 1, 2), default=S, help="0.5 = 540p draft for review rounds, 1 = 1080p, 2 = 2160p (also PROMO_SCALE)")
    common.add_argument("--force", action="store_true", default=S, help="ignore stamps, redo the step")
    common.add_argument("-v", "--verbose", action="store_true", default=S)
    common.add_argument("--debug", action="store_true", default=S, help="debug overlays (e.g. livestream keep-clear boxes); never for delivery")
    ap = argparse.ArgumentParser(prog="promo", description="Declarative product promo-video pipeline", parents=[common])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, help_, json_=False, **kw):
        p = sub.add_parser(name, help=help_, parents=[common], **kw)
        if json_:
            p.add_argument("--json", action="store_true", help="JSON on stdout only (logs on stderr); always has `ok`")
        return p
    n = add("new", "scaffold projects/<name>/ (or --dir)")
    n.add_argument("name")
    n.add_argument("--dir", help="explicit destination directory")
    n.add_argument("--style", default="hero", help="style preset: hero | anime-opening | livestream | cinematic-story | horizon (see `promo styles`)")
    sub.add_parser("styles", help="list style presets (pacing, band, typography, transitions, checks)", parents=[common]).add_argument("--json", action="store_true")
    add("grid", "bar/beat table of the music grid (timeline.grid) with markers and phrase starts", True)
    add("needs", "the handoff: what promo-reel still needs from the calling agent (footage to capture, plates to generate, human review)", False).add_argument("--json", action="store_true")
    add("assets", "validate the assets manifest and print a table", True)
    add("fetch", "download missing assets (sha256 verified)")
    ft = sub.add_parser("footage", help="footage manifest: verify | list | add", parents=[common])
    fs = ft.add_subparsers(dest="fcmd", required=True)
    for nm, h in (("verify", "check every referenced clip exists + sha256 matches"), ("list", "list manifest clips")):
        q = fs.add_parser(nm, help=h, parents=[common])
        q.add_argument("--json", action="store_true")
    q = fs.add_parser("add", help="add/update a clip (sha256 + probe) in footage/manifest.yaml", parents=[common])
    q.add_argument("path")
    q.add_argument("--id", required=True)
    q.add_argument("--shots", nargs="*", default=[])
    q.add_argument("--commit", default="unknown", help="full app commit SHA")
    q.add_argument("--capture", default="unknown", help="URL / params, clock + seed notes")
    q.add_argument("--framing", default="unknown")
    q.add_argument("--dpr", type=int)
    q.add_argument("--notes", default="")
    q.add_argument("--demo", action="store_true", help="demo-mode footage")
    q.add_argument("--captured-at")
    q.add_argument("--json", action="store_true")
    add("sfx", "synthesise SFX wavs")
    add("vo", "render VO lines with Kokoro")
    add("clip-audio", "extract + normalise the soundtrack of clips used by shot `audio:` lines")
    add("music", "edit the music on the beat grid")
    add("shot", "render shots").add_argument("ids", nargs="+")
    add("events", "write build/audio/events.json")
    add("mix", "mix + duck + master")
    add("assemble", "concat + mux the masters")
    add("contact", "contact sheet")
    b = add("build", "full idempotent build")
    b.add_argument("--shots", nargs="+", help="only (re)render these shots; skips assemble/contact")
    add("status", "per-step up-to-date / stale / missing", True)
    add("timeline", "print the shot table", True)
    add("check", "QA gates (exit 1 on FAIL)", True)
    cp = add("compare", "per-shot PSNR + audio diff vs a reference render", True)
    cp.add_argument("ref")
    cp.add_argument("--new", help="render to compare (default: primary output)")
    cp.add_argument("--min-psnr", type=float, default=40.0)
    pk = add("peek", "frame (or crop) of a source clip (clip id) with a grid")
    pk.add_argument("src")
    pk.add_argument("t", type=float)
    pk.add_argument("box", nargs="*", type=float)
    sp = add("segpeek", "tiles from a rendered segment")
    sp.add_argument("id")
    sp.add_argument("times", nargs="*", type=float)
    cpk = add("critique-pack", "self-contained review folder (stills + sidecars, contact, copy, manifests, reviews, check, BRIEF.md) for a reviewer model", True)
    cpk.add_argument("project_dir", nargs="?", help="project dir or promo.yaml (default: -p / ./promo.yaml)")
    cpk.add_argument("--out", help="pack folder (default <project>/out/critique-pack, or critique.out in promo.yaml)")
    cpk.add_argument("--no-check", action="store_true", help="reuse the last saved check report instead of running promo check")
    cpk.add_argument("--video", action="store_true", help="also copy the primary render into the pack")
    mc = add("move-cut", "move one cut on the beat grid (end the shot at <beat>, start the next at <new_beat>); edits promo.yaml", True)
    mc.add_argument("beat", type=float)
    mc.add_argument("new_beat", type=float)
    mp = add("mpeek", "grid of frames: out.png clip-id:t[:x0,y0,x1,y1] ...")
    mp.add_argument("out")
    mp.add_argument("specs", nargs="+")
    sub.add_parser("watch", help="watch a video (file/URL): contact sheets, cut stills, transcript, audio + pacing metrics (see `promo watch -h`)")
    sub.add_parser("gen", help="generated images/video for non-UI plates (backgrounds, transitions): detect | image | video | plan (see `promo gen -h`)")
    sub.add_parser("brief", help="the locked brief (the user's exact words + references): init | show | check | confirm | conflict (see `promo brief -h`)")
    sub.add_parser("screen-quad", help="track the monitor quad of a generated plate (clip id or file): per-second quads + debug PNG (see `promo screen-quad -h`)")
    sub.add_parser("refs", help="study references for real: add (watch WITH transcript + scaffold DOSSIER.md) | check | show (see `promo refs -h`)")
    sub.add_parser("compare-ref", help="draft vs each reference: sheet rows + metrics incl. speech/LUFS/tempo (see `promo compare-ref -h`)")
    sub.add_parser("flow", help="the gated production flow with the person in the loop: init | status | discover | script | council | approve | asset | needs | advance | draft | round | final | revise | board (see `promo flow -h`)")
    sub.add_parser("config", help="user config: `promo config projects-dir [PATH]` (projects may live outside this repo), `promo config heavy-lock [PATH]`")
    sub.add_parser("projects", help="list the projects in the projects dir (PROMO_PROJECTS / config / <repo>/projects)")
    sub.add_parser("rubric", help="PASS/FAIL of a scores file (or a review .md) against evals/rubric.yaml (see `promo rubric -h`)")
    sub.add_parser("live2d", help="Live2D host renderer: fetch | models | render | lag (see `promo live2d -h`)")
    return ap


def dispatch(spec, args):
    """Run a command; returns (payload_or_None, human_printer_or_None, exit_code)."""
    c = args.cmd
    if c == "timeline":
        r = cmd_timeline(spec, args)
        return r, print_timeline, 0 if r["ok"] else 1
    if c == "assets":
        r = cmd_assets(spec, args)
        return r, lambda r_: print_assets(r_, spec), 0 if r["ok"] else 1
    if c == "needs":
        from . import needs
        needs.main(spec, getattr(args, "json", False))
        return None, None, 0
    if c == "footage":
        r = cmd_footage(spec, args)
        return r, lambda r_: print_footage(args, r_), 0 if r["ok"] else 1
    if c == "status":
        r = cmd_status(spec, args)
        return r, print_status, 0 if r["ok"] else 1
    if c == "check":
        from . import check
        from .lock import heavy_lock
        with heavy_lock("promo check"):         # loudness scans + contact sheet run ffmpeg
            r = check.run(spec)
        return r, check.print_report, 1 if r["failed"] else 0
    if c == "compare":
        from . import compare
        r = compare.run(spec, args.ref, args.new, args.min_psnr)
        return r, compare.print_human, 0 if r["ok"] else 1
    if c == "fetch":
        for aid, what in A.fetch(spec, force=args.force):
            print(f"{aid:<18} {what}")
        return None, None, 0
    if c in ("peek", "segpeek", "mpeek"):
        from . import contact
        if c == "peek":
            print(contact.peek(spec, args.src, args.t, args.box or None))
        elif c == "segpeek":
            print(*contact.segpeek(spec, args.id, args.times))
        else:
            print(*contact.mpeek(spec, args.out, args.specs))
        return None, None, 0
    if c == "critique-pack":
        from . import critique
        from .lock import heavy_lock
        with heavy_lock("promo critique-pack"):     # frame extraction, check (loudness, contact), whisper
            r = critique.build(spec, out=args.out, reuse_check=args.no_check, video=args.video,
                               log=lambda *a: print(*a, file=sys.stderr))
        return r, critique.print_summary, 0
    if c == "move-cut":
        from . import retime
        try:
            bpb = spec.grid.beats_per_bar if spec.grid else 4
            r = retime.move_cut(args.project, spec.raw, args.beat, args.new_beat, bar_s=bpb * spec.timeline.B, beats_per_bar=bpb)
        except retime.RetimeError as e:
            r = dict(ok=False, error=str(e))
        return r, (lambda r_: print(r_.get("error") or f"cut {r_['moved'][0]:g} -> {r_['moved'][1]:g}: {r_['shots']} "
                                    f"(starts {r_.get('starts_s')}); run `promo check`")), 0 if r["ok"] else 1
    if c == "grid":
        r = cmd_grid(spec, args)
        return r, print_grid, 0 if r["ok"] else 1
    if c in ("sfx", "vo", "clip-audio", "music", "mix", "build", "events", "shot", "assemble", "contact"):
        from .lock import heavy_lock
        with heavy_lock(f"promo {c}"):          # box-wide lock: never overlap two heavy jobs
            return _dispatch_heavy(spec, args, c)
    return None, None, 0


def _dispatch_heavy(spec, args, c):
    if c in ("sfx", "vo", "clip-audio", "music", "mix", "build", "events", "shot"):
        A.gate(spec)          # licence gate: music/vo_model/sfx must carry licence + source_url
    if c == "shot":
        FT.gate(spec, set(args.ids))      # clips used by these shots exist and match their sha256
        for sid in args.ids:
            spec.shot(sid)
        for sid in args.ids:
            _step(spec, args, f"shot {sid}")
    elif c == "build":
        do_build(spec, args)
    elif c in ("sfx", "vo", "clip-audio", "music", "events", "mix", "assemble", "contact"):
        if c == "clip-audio" and not any(st["name"] == c for st in plan(spec)):
            raise SpecError("no shot has an `audio:` key")
        if c == "mix" and any(st["name"] == "clip-audio" for st in plan(spec)):
            _step(spec, args, "clip-audio")          # the mix places the clip WAVs: make sure they are current
        _step(spec, args, c)
    return None, None, 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["live2d"]:          # `promo live2d ...` does not need a promo.yaml
        from . import live2d
        return live2d.main(argv[1:])
    if argv[:1] == ["watch"]:           # `promo watch <url|file> [--out DIR]`: frames, cuts, transcript, audio metrics of any video
        from . import watch
        import argparse as _ap
        w = _ap.ArgumentParser(prog="promo watch", description=watch.__doc__, formatter_class=_ap.RawDescriptionHelpFormatter)
        w.add_argument("src", help="video file or URL (yt-dlp)")
        w.add_argument("--out", help="output dir (default build/watch/<id>)")
        w.add_argument("--thresh", type=float, default=0.28, help="scene-cut threshold (0-1, lower = more cuts)")
        a = w.parse_args(argv[1:])
        rep = watch.run(a.src, a.out, a.thresh)
        print(f"{rep['out']}/WATCH.md  ({rep['n_cuts']} cuts, {rep['duration']:.1f}s)")
        return 0
    if argv[:1] == ["screen-quad"]:     # `promo screen-quad <plate-clip-id|file> [-p promo.yaml]`: track a plate's monitor quad, print it, draw a debug PNG
        from . import screentrack
        return screentrack.main(argv[1:])
    if argv[:1] == ["gen"]:             # `promo gen detect|image|video|plan`: generated NON-UI plates via the logged-in grok / codex CLIs
        from . import genvideo as G
        return G.main(argv[1:])
    if argv[:1] == ["brief"]:           # `promo brief init|show|check|confirm|conflict --project projects/<name>` (no promo.yaml needed)
        from . import brief
        return brief.main(argv[1:])
    if argv[:1] == ["refs"]:            # `promo refs add|check|show --project projects/<name>`
        from . import refs
        return refs.main(argv[1:])
    if argv[:1] == ["compare-ref"]:     # `promo compare-ref <draft.mp4> --project projects/<name>`
        from . import compare_ref
        from .lock import heavy_lock
        with heavy_lock("promo compare-ref"):       # ffmpeg frame grabs, cut detection, whisper
            return compare_ref.main(argv[1:])
    if argv[:1] == ["flow"]:            # `promo flow ...`: the gated production flow (scripts -> storyboard -> assets -> drafts -> council rounds)
        from . import flow
        return flow.main(argv[1:])
    if argv[:1] == ["config"]:          # `promo config projects-dir|heavy-lock [PATH]`
        from . import home
        return home.main(argv[1:])
    if argv[:1] == ["projects"]:        # `promo projects`: list the projects in the projects dir
        from . import home
        print(f"projects dir: {home.projects_dir()}")
        for p in home.list_projects():
            print(f"  {p['name']:<28} brief={'yes' if p['brief'] else 'no ':<3} rounds={p['rounds']}  {p['path']}")
        return 0
    if argv[:1] == ["rubric"]:          # `promo rubric <scores>`: PASS/FAIL against evals/rubric.yaml (no promo.yaml needed)
        from . import rubric
        return rubric.main(argv[1:])
    args = build_parser().parse_args(argv)
    from . import home as _home
    args.project = getattr(args, "project", "promo.yaml")
    if args.project != "promo.yaml":                 # a bare project name / legacy `projects/<name>` resolves in the projects dir
        _r = _home.resolve(args.project)
        args.project = os.path.join(_r, "promo.yaml") if os.path.isdir(_r) else _r
    if getattr(args, "project_dir", None):
        args.project_dir = _home.resolve(args.project_dir)
    args.scale = getattr(args, "scale", None)
    args.force = getattr(args, "force", False)
    args.verbose = getattr(args, "verbose", False)
    if getattr(args, "debug", False):
        os.environ["PROMO_DEBUG"] = "1"
    as_json = getattr(args, "json", False)
    real_out = sys.stdout
    try:
        # JSON mode: everything the steps print goes to stderr; only the payload reaches stdout
        with (contextlib.redirect_stdout(sys.stderr) if as_json else contextlib.nullcontext()):
            if args.cmd == "new":
                return cmd_new(args) or 0
            if args.cmd == "styles":
                r = cmd_styles()
                if as_json:
                    print(json.dumps(r, indent=1), file=real_out)
                else:
                    print_styles(r)
                return 0
            pd = getattr(args, "project_dir", None)
            if pd:
                args.project = os.path.join(pd, "promo.yaml") if os.path.isdir(pd) else pd
            spec = load_spec(args.project, scale=args.scale)
            payload, human, rc = dispatch(spec, args)
            if not as_json and human and payload is not None:
                human(payload)
        if as_json and payload is not None:
            print(json.dumps(payload, indent=1, default=str), file=real_out)
        return rc
    except (SpecError, FileNotFoundError, RuntimeError, AssertionError, SystemExit) as e:
        if isinstance(e, SystemExit) and not e.code:
            return 0
        msg = str(e) if not isinstance(e, SystemExit) else str(e.code)
        if as_json:
            print(json.dumps(dict(ok=False, error=msg)), file=real_out)
        else:
            print(f"promo: error: {msg}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
