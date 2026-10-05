"""Generated images / video for NON-UI plates: transitions, backgrounds, scenery, textures.

Architecture: the CALLING AGENT generates, promo-reel specifies, ingests and gates.
    promo gen plan [-p promo.yaml] [--json]    the open requests (`broll:` entries whose file is missing): id, kind, target path, seconds,
                                               aspect, min size and the full guard-prefixed prompt. Fulfil each with ANY tool you have
                                               (your own image/video tool, `grok -p`, `codex exec`, a human) and write the file to `out`.
    promo gen register FILE -p promo.yaml --id ID [--provider P --prompt TEXT --shots 03 04] [--watermark br]
                                               ingest a supplied file: probe, optional corner-watermark crop + 1080p upscale (raw kept),
                                               sidecar `.gen.json`, footage-manifest entry with `generated:`; prints the next steps.
    promo gen detect [--json]                  which built-in runners this box has (grok / codex CLI logins, API keys), as a hint to agents.
  Optional built-in runner (fallback when the agent has no generation tool of its own; headless one-shot, no auto-approve flags):
    promo gen image|video "prompt" --out F [--provider auto] [--register promo.yaml --id ID]     promo gen plan --run

Rules (AGENTS.md rule 1, generated-plate carve-out):
- Generated media may fill only text-free, UI-free plates: backgrounds, transitions, scenery, macro textures. Never the product UI, never
  anything that reads as the product, never text/logos. The prompt must say so; `promo check` gate `generated-plates` FAILs when a
  generated clip feeds a shot with `ui: true` (or an unmarked `clip`/`cinema`/`horizon` shot that shows app footage) and WARNs for human review.
- Every generated file gets a sidecar `<file>.gen.json` (provider, model, prompt, seconds, sha256) and is registered in the footage
  manifest with `generated: {provider, prompt, ...}` (`promo gen ... --register` or `promo footage add`).
- Providers are CLIs the user is already logged into (headless one-shot, no blanket auto-approve flags) or API keys; `auto` picks the first
  available that supports the kind. Nothing runs unless the user asked for generation (plan is dry-run unless `--run`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

HOME = Path.home()

NEG = ("No people, no text, no logos, no user-interface, no screens, no software windows. ")
NEG_PEOPLE = "No on-screen text, no logos, no user-interface or software windows readable on any screen. "
STORYBOARD = ("This is a STORYBOARD STILL for planning, not final footage: one clean, believable concept frame. If it shows software, draw a plausible generic "
              "app window; no real brand logos, no watermarks, only short legible labels. ")


def _file(p):
    return Path(p).expanduser().exists()


def detect() -> list[dict]:
    """Providers visible on this machine. Availability = tool present AND a login/key present. Capability is what we believe the
    provider's headless one-shot can produce; `verified` flips true after a successful `promo gen` run (recorded in ~/.promo-tools/gen-state.json)."""
    state = _state()
    out = []
    out.append(dict(id="grok", kind=["image", "video"], tool=shutil.which("grok"),
                    login=_file("~/.grok/auth.json"), how="grok CLI (grok.com login), headless: grok -p <prompt>"))
    out.append(dict(id="codex", kind=["image"], tool=shutil.which("codex"),
                    login=_file("~/.codex/auth.json"), how="codex CLI (ChatGPT login), headless: codex exec <prompt>; image tool, files land in ~/.codex/generated_images"))
    out.append(dict(id="openai-api", kind=["image", "video"], tool="api" if os.environ.get("OPENAI_API_KEY") else None,
                    login=bool(os.environ.get("OPENAI_API_KEY")), how="OPENAI_API_KEY (images/videos endpoints); key validity not probed"))
    out.append(dict(id="xai-api", kind=["image", "video"], tool="api" if os.environ.get("XAI_API_KEY") else None,
                    login=bool(os.environ.get("XAI_API_KEY")), how="XAI_API_KEY"))
    for p in out:
        p["available"] = bool(p["tool"] and p["login"]) and p["tool"] != "api"      # API adapters are not wired yet (key seen, not usable)
        p["verified"] = sorted(state.get(p["id"], {}).get("ok", []))
    return out


def _state_path():
    return HOME / ".promo-tools" / "gen-state.json"


def _state():
    try:
        return json.loads(_state_path().read_text())
    except Exception:
        return {}


def _mark_ok(provider, kind):
    st = _state()
    ok = set(st.get(provider, {}).get("ok", []))
    ok.add(kind)
    st[provider] = {"ok": sorted(ok), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    _state_path().parent.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(st, indent=1))


def providers(kind: str, provider: str = "auto") -> list[dict]:
    ps = [p for p in detect() if p["available"] and kind in p["kind"]]
    if provider != "auto":
        ps = [p for p in ps if p["id"] == provider]
    if not ps:
        raise SystemExit(f"no available provider for {kind} (provider={provider}); run `promo gen detect`")
    ps.sort(key=lambda p: (kind not in p["verified"], p["id"] not in ("grok", "codex")))
    return ps


def pick(kind: str, provider: str = "auto") -> dict:
    return providers(kind, provider)[0]


def prompt_for(kind: str, prompt: str, out: Path, seconds: float, aspect: str, people: bool = False, ref=None, guard: str | None = None) -> str:
    base = (f"{guard if guard is not None else NEG_PEOPLE if people else NEG}{prompt.strip()} ")
    refs = [ref] if isinstance(ref, str) else list(ref or [])
    if refs:
        lead = f"Use the image file {refs[0]} as the identity AND set reference: the person must be exactly the same woman (same face, same hair, same oatmeal hoodie) in exactly the same room (same wood panelling, same brass desk lamp, same desk). "
        if len(refs) > 1:
            lead += f"Use the image file {refs[1]} as the layout reference for the desk and the single unbranded monitor standing on it. "
        base = lead + base
    if kind == "video":
        return (f"Generate a {seconds:g} second {aspect} VIDEO using your video generation tool. {base}"
                f"Save the video file to {out} (mp4) and print only that path.")
    return (f"Generate one {aspect} IMAGE using your image generation tool. {base}"
            f"Save the image to {out} (png) and print only that path.")


def argv_for(provider: dict, text: str) -> list[str]:
    if provider["id"] == "grok":
        return ["grok", "-p", text]
    if provider["id"] == "codex":
        return ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", text]
    raise SystemExit(f"{provider['id']}: API adapters are not wired yet; use the grok or codex CLI")


def sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def probe_media(path) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,duration,r_frame_rate", "-of", "json", str(path)],
                       capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
        return {"width": s.get("width"), "height": s.get("height"), "duration": float(s.get("duration") or 0)}
    except Exception:
        return {}


def strip_watermark(path: Path, kind: str, keep: float = 0.9) -> str | None:
    """Grok stamps a corner logo on its output. Framing fix, not a UI edit (these are non-UI plates): keep the top-left `keep`
    fraction of the frame (the logo sits in the bottom-right ~8%), scale back to 1080p (lanczos). The untouched file is kept as <name>.raw<ext>."""
    raw = path.with_name(path.stem + ".raw" + path.suffix)
    shutil.copyfile(path, raw)
    vf = f"crop=iw*{keep}:ih*{keep}:0:0,scale=1920:1080:flags=lanczos,unsharp=5:5:0.4"
    if kind == "video":
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf", vf, "-map", "0:v", "-map", "0:a?", "-c:v", "libx264", "-crf", "14",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(path)]      # keep the generator's audio (voices, ambience)
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf", vf, str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        shutil.copyfile(raw, path)
        return None
    return f"cropped to top-left {keep:.0%}, scaled to 1920x1080"


def register(spec, file: str, cid: str, provider: str = "agent", prompt: str = "", shots=(), kind: str | None = None,
             watermark: str | None = None, aspect: str = "16:9") -> dict:
    """Ingest an asset the calling agent produced: optional watermark crop, sidecar, footage-manifest entry (`generated:`)."""
    from . import footage as FT
    f = Path(file).expanduser().resolve()
    if not f.exists():
        raise SystemExit(f"file not found: {f}")
    kind = kind or ("video" if f.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv") else "image")
    wm = strip_watermark(f, kind) if watermark else None
    info = probe_media(f)
    meta = dict(generated=True, kind=kind, provider=provider, prompt=prompt, aspect=aspect, watermark_cropped=wm, sha256=sha256(f),
                at=time.strftime("%Y-%m-%dT%H:%M:%S"), **info)
    Path(str(f) + ".gen.json").write_text(json.dumps(meta, indent=1))
    e = FT.add(spec, str(f), cid, shots=list(shots), capture=f"generated by {provider}", framing="generated plate, text-free, UI-free",
               dpr=1, notes=f"AI-generated plate: {prompt[:200]}",
               generated={k: meta[k] for k in ("provider", "kind", "prompt", "at", "sha256")})
    meta["registered"] = e["id"]
    meta["next"] = (f"reference it as `source: {cid}` (or `still: {cid}`) on a shot with `ui: false`; `promo check` gates generated-plates; "
                    "a human reviews generated plates before publishing")
    return meta


def requests(spec) -> list[dict]:
    """Open generation requests from `broll:` with everything an agent needs to fulfil them with any tool."""
    rows = []
    from . import footage as FT
    try:
        man = FT.load(spec)
    except Exception:
        man = {}
    for b in broll_entries(spec):
        kind = b["kind"]
        if b["id"] in man and Path(man[b["id"]]["path"]).exists():       # already registered (possibly generated for another project)
            b["out"] = man[b["id"]]["path"]
        sec = float(b.get("seconds", 4.0))
        asp = b.get("aspect", "16:9")
        rows.append(dict(id=b["id"], kind=kind, out=b["out"], exists=Path(b["out"]).exists(), seconds=sec if kind == "video" else None,
                         aspect=asp, min_size="1920x1080 preferred (720p is cropped/upscaled on register)",
                         prompt=prompt_for(kind, b["prompt"], Path(b["out"]), sec, asp), raw_prompt=b["prompt"],
                         then=f"promo gen register {b['out']} -p <promo.yaml> --id {b['id']} --prompt \"...\" --shots <ids>"))
    return rows


def _run_provider(p: dict, text: str, out_p: Path, timeout: int) -> str:
    """Run one provider; returns '' when it wrote `out_p`, else why it did not."""
    t0 = time.time()
    r = subprocess.run(argv_for(p, text), cwd=str(out_p.parent), capture_output=True, text=True, timeout=timeout)
    if not out_p.exists() and p["id"] == "codex":
        # codex keeps images under ~/.codex/generated_images/<session>/: take the newest file made since we started
        gi = HOME / ".codex" / "generated_images"
        newest = None
        for f in gi.rglob("*") if gi.exists() else []:
            if f.is_file() and f.stat().st_mtime >= t0 and (newest is None or f.stat().st_mtime > newest.stat().st_mtime):
                newest = f
        if newest:
            shutil.copyfile(newest, out_p)
    if out_p.exists():
        return ""
    return f"{p['id']} produced no file at {out_p} (exit {r.returncode}): {(r.stdout or r.stderr)[-400:]}"


def generate(kind: str, prompt: str, out: str, seconds: float = 4.0, aspect: str = "16:9", provider: str = "auto",
             timeout: int = 900, people: bool = False, ref=None, guard: str | None = None) -> dict:
    """`guard` replaces the plate guard (no UI, no text) for callers that need another look, e.g. STORYBOARD stills; their corner logo is the caller's to crop."""
    out_p = Path(out).expanduser().resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    text = prompt_for(kind, prompt, out_p, seconds, aspect, people, ref, guard)
    why = []
    for p in providers(kind, provider):
        err = _run_provider(p, text, out_p, timeout)
        if not err:
            break
        why.append(err)
    else:
        raise RuntimeError("; ".join(why))
    wm = strip_watermark(out_p, kind) if p["id"] == "grok" and guard is None else None
    meta = dict(generated=True, kind=kind, watermark_cropped=wm, provider=p["id"], prompt=prompt, seconds=seconds if kind == "video" else None, aspect=aspect,
                sha256=sha256(out_p), at=time.strftime("%Y-%m-%dT%H:%M:%S"), **probe_media(out_p))
    Path(str(out_p) + ".gen.json").write_text(json.dumps(meta, indent=1))
    _mark_ok(p["id"], kind)
    return meta


# ---------------------------------------------------------------- spec side: `broll:` plan + the plate gate
def broll_entries(spec) -> list[dict]:
    """promo.yaml `broll: [{id, kind: video|image, prompt, seconds, aspect, provider, out}]` (out defaults to media/gen/<id>.mp4|png)."""
    res = []
    for b in spec.raw.get("broll") or []:
        b = dict(b)
        b.setdefault("kind", "video")
        ext = "mp4" if b["kind"] == "video" else "png"
        b["out"] = str(spec.resolve(b.get("out") or f"media/gen/{b['id']}.{ext}"))
        res.append(b)
    return res


def plan(spec, run=False):
    rows = []
    for b in broll_entries(spec):
        have = Path(b["out"]).exists()
        row = dict(id=b["id"], kind=b["kind"], out=b["out"], exists=have, ran=False)
        if not have and run:
            row["meta"] = generate(b["kind"], b["prompt"], b["out"], b.get("seconds", 4.0), b.get("aspect", "16:9"), b.get("provider", "auto"))
            row["ran"] = True
        rows.append(row)
    return rows


def plate_gate(spec) -> list[tuple[str, str, str]]:
    """promo check: generated clips may only feed UI-free shots."""
    from . import footage as FT
    try:
        man = FT.load(spec)
    except Exception:
        return []
    gen = {cid: c for cid, c in man.items() if c.get("generated")}
    if not gen:
        return []
    refs = FT.referenced(spec)
    bad, used = [], []
    shots = {s.id: s for s in spec.shots}
    for cid in gen:
        for sid in refs.get(cid, []):
            used.append(f"{cid}->{sid}")
            s = shots.get(sid)
            # a generated clip used only as the blurred BACKDROP plate behind a UI panel is scenery, not the picture: allowed
            shows = s is not None and cid in {s.get(k) for k in ("source", "still", "board", "node")}
            if s is not None and not shows:
                continue
            if s is not None and (s.get("ui") is True or s.get("ui") is None and s.type in ("clip",)):
                bad.append(f"generated clip {cid} used by UI shot {sid} (set ui: false only if the plate shows no app UI)")
            elif s is None:
                bad.append(f"generated clip {cid} used by {sid} (plates must be declared ui: false shots)")
    out = [("generated-plates", "FAIL" if bad else "PASS", "; ".join(bad) or "generated clips only on UI-free shots")]
    if used:
        out.append(("generated-review", "WARN", "HUMAN: review generated plates before publishing: " + ", ".join(sorted(used))))
    return out


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="promo gen", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--json", action="store_true")
    for k in ("image", "video"):
        q = sub.add_parser(k)
        q.add_argument("prompt")
        q.add_argument("--out", required=True)
        q.add_argument("--provider", default="auto")
        q.add_argument("--aspect", default="16:9")
        q.add_argument("--ref", action="append", help="reference image(s) for people scenes: first = identity + set, second = desk/monitor layout (repeat the flag)")
        q.add_argument("--people", action="store_true", help="the scene may contain people (live-action film); text/logo/UI-on-screen guard stays on")
        q.add_argument("--register", metavar="PROJECT_YAML", help="add the file to that project's footage manifest (generated: ...)")
        q.add_argument("--id", help="clip id for --register (default: file stem)")
        q.add_argument("--shots", nargs="*", default=[], help="shot ids that will use it")
        if k == "video":
            q.add_argument("--seconds", type=float, default=4.0)
    pl = sub.add_parser("plan")
    pl.add_argument("-p", "--project", default="promo.yaml")
    pl.add_argument("--run", action="store_true", help="built-in runner: generate the missing ones with the grok/codex CLI (default: only list the requests)")
    pl.add_argument("--json", action="store_true")
    rg = sub.add_parser("register")
    rg.add_argument("file")
    rg.add_argument("-p", "--project", default="promo.yaml")
    rg.add_argument("--id", required=True)
    rg.add_argument("--provider", default="agent")
    rg.add_argument("--prompt", default="")
    rg.add_argument("--shots", nargs="*", default=[])
    rg.add_argument("--kind", choices=["image", "video"])
    rg.add_argument("--watermark", choices=["br"], help="crop a bottom-right corner logo (Grok) and upscale to 1080p")
    a = ap.parse_args(argv)
    if a.cmd == "detect":
        ps = detect()
        if a.json:
            print(json.dumps(ps, indent=1))
        else:
            for p in ps:
                print(f"{p['id']:<11} {'READY' if p['available'] else 'no   '}  kinds={','.join(p['kind']):<12} verified={','.join(p['verified']) or '-':<12} {p['how']}")
        return 0
    if a.cmd in ("image", "video"):
        meta = generate(a.cmd, a.prompt, a.out, getattr(a, "seconds", 4.0), a.aspect, a.provider, people=getattr(a, "people", False), ref=getattr(a, "ref", None))
        if a.register:
            from . import footage as FT
            from .spec import load_spec as _ls
            e = FT.add(_ls(a.register), a.out, a.id or Path(a.out).stem, shots=a.shots, capture=f"promo gen {a.cmd} ({meta['provider']})",
                       framing="generated plate, text-free, UI-free", dpr=1, notes=f"AI-generated: {a.prompt[:200]}",
                       generated={k: meta[k] for k in ("provider", "kind", "prompt", "at", "sha256") if k in meta})
            meta["registered"] = e["id"]
        print(json.dumps(meta, indent=1))
        return 0
    from .spec import load_spec
    if a.cmd == "register":
        print(json.dumps(register(load_spec(a.project), a.file, a.id, a.provider, a.prompt, a.shots, a.kind, a.watermark), indent=1))
        return 0
    if a.cmd == "plan" and not a.run:
        rq = requests(load_spec(a.project))
        if a.json:
            print(json.dumps(rq, indent=1))
        else:
            for r in rq:
                print(f"{r['id']:<20} {r['kind']:<6} {'exists' if r['exists'] else 'OPEN  '}  {r['out']}\n    prompt: {r['prompt']}")
        return 0
    for r in plan(load_spec(a.project), a.run):
        print(f"{r['id']:<20} {r['kind']:<6} {'exists' if r['exists'] else ('generated' if r['ran'] else 'MISSING')}  {r['out']}")
    return 0
