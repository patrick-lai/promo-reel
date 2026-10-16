"""Generated images / video for NON-UI plates: transitions, backgrounds, scenery, textures.

Architecture: the CALLING AGENT generates, promo-reel specifies, ingests and gates.
    promo gen plan [-p promo.yaml] [--json]    the open requests (`broll:` entries whose file is missing): id, kind, target path, seconds,
                                               aspect, min size and the prompt to send. A plain plate gets the guard-prefixed line. A staged
                                               entry (`stage: character|prop|location|shot`) gets that stage's template; a one-line shot is
                                               expanded into the shot skeleton. A later stage is `blocked` until every earlier stage is
                                               registered and approved.
    promo gen prompt "line" --stage shot --ref identity=hero:a woman in a striped sweater
                                               print the terse line and the expanded prompt. Calls nothing.
    promo gen approve ID -p promo.yaml         lock one registered reference. Shots stay blocked until the character, prop and location
                                               stages they depend on are approved.
    promo gen register FILE -p promo.yaml --id ID [--provider P --prompt TEXT --shots 03 04] [--watermark br] [--stage character]
                                               ingest a supplied file: probe, optional corner-watermark crop + 1080p upscale (raw kept),
                                               sidecar `.gen.json`, footage-manifest entry with `generated:`; prints the next steps.
    promo gen detect [--json]                  which built-in runners this box has (grok / codex CLI logins), as a hint to agents.
    promo gen models | spend [--json]          OpenRouter video (Seedance, Grok Imagine): models with prices, and the spend ledger (promo/openrouter.py)
  Optional built-in runner (fallback when the agent has no generation tool of its own; headless one-shot, no auto-approve flags):
    promo gen image|video "prompt" --out F [--provider auto] [--register promo.yaml --id ID]     promo gen plan --run
    promo gen video "prompt" --out F --provider openrouter [--model M --res 480p --seconds 4 --first-frame IMG --dry-run]
                                               Seedance or Grok Imagine through OpenRouter (pay per job): priced first, refused over --max-usd or the daily cap.
                                               Never picked by `auto`; run under `commissionctl secret exec OPENROUTER_API_KEY -- ...`.

Rules (AGENTS.md rule 1, generated-plate carve-out):
- Generated media may fill only text-free, UI-free plates: backgrounds, transitions, scenery, macro textures. Never the product UI, never
  anything that reads as the product, never text/logos. The prompt must say so; `promo check` gate `generated-plates` FAILs when a
  generated clip feeds a shot with `ui: true` (or an unmarked `clip`/`cinema`/`horizon` shot that shows app footage) and WARNs for human review.
- Every generated file gets a sidecar `<file>.gen.json` (provider, model, prompt, seconds, sha256) and is registered in the footage
  manifest with `generated: {provider, prompt, ...}` (`promo gen ... --register` or `promo footage add`).
- Providers are CLIs the user is already logged into (headless one-shot, no blanket auto-approve flags) or API keys; `auto` picks the first
  available that supports the kind, never a paid API (openrouter runs only when named). Nothing runs unless the user asked for generation
  (plan is dry-run unless `--run`).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import openrouter as OR

HOME = Path.home()

NEG = ("No people, no text, no logos, no user-interface, no screens, no software windows. ")
NEG_PEOPLE = "No on-screen text, no logos, no user-interface or software windows readable on any screen. "
GUARDS = {
    "plate": NEG,
    "people": NEG_PEOPLE,
    # anime-mv: original illustrated characters are the point; still no text, logos, UI, real people or existing characters
    "illustrated": ("No text, no letters, no captions, no logos, no signatures, no watermark, no user-interface or screens. Characters are "
                    "ORIGINAL illustrated characters: not real people, not existing anime or game characters. "),
}
REF_ROLES = {
    "identity": "Use the image file {f} as the identity AND set reference: exactly the same person (same face, hair and clothes) in exactly the same place. ",
    "set": "Use the image file {f} as the layout reference for the set and the objects in it. ",
    "character": "Use the image file {f} as the CHARACTER reference: keep this exact character design (face, hair, colours, clothes, proportions). ",
    "style": "Use the image file {f} as the STYLE reference only: match its drawing style, line weight, palette and texture, not its content. ",
    "keyframe": "Animate the image file {f} as the exact first frame (image-to-video); keep its drawing style, linework and palette unchanged. ",
}
STORYBOARD = ("This is a STORYBOARD STILL for planning, not final footage: one clean, believable concept frame. If it shows software, draw a plausible generic "
              "app window; no real brand logos, no watermarks, only short legible labels. ")

# A generated spot that has to hold a person, an object or a place across shots. Order is the pipeline: each stage may tag only
# earlier stages, and nothing in a later stage runs until the earlier ones are registered and approved.
STAGES = ("character", "prop", "location", "shot")
_SCOPE_STAGE = {"identity": "character", "product": "prop", "prop": "prop", "geography": "location"}
SHOT_NEGATIVE = (
    "no cuts, no jump cuts, no fades, no dissolves, no reset between beats, no beats out of order, "
    "no lighting inherited from any reference image, no studio backdrop carried in from a reference, "
    "no extra people, no duplicated characters, no on-screen text, no captions, no subtitles, no watermarks, "
    "no logos, no user-interface, no beauty filter, no plastic or waxy skin, no style drift"
)


def canonical_scope(name) -> str | None:
    n = str(name or "").strip().lower()
    if n == "location":
        return "geography"
    return n if n in _SCOPE_STAGE else None


def parse_scoped(ref) -> list[dict]:
    """Scoped tags only: identity, product, prop, geography (location is an alias). Legacy roles stay in `parse_refs`."""
    items = [ref] if isinstance(ref, str) else list(ref or [])
    out = []
    for r in items:
        if isinstance(r, dict):
            scope = canonical_scope(r.get("scope"))
            if not scope:
                continue
            out.append(dict(id=str(r.get("id") or "ref"), scope=scope, desc=str(r.get("desc") or r.get("prompt") or "").strip(),
                            file=r.get("file")))
            continue
        if isinstance(r, (tuple, list)) and len(r) >= 2 and canonical_scope(r[0]):
            out.append(dict(id=str(r[1]), scope=canonical_scope(r[0]), desc=str(r[2]).strip() if len(r) > 2 else "", file=None))
            continue
        role, sep, rest = str(r).partition("=")
        scope = canonical_scope(role) if sep else None
        if not scope:
            continue
        ident, _, desc = rest.partition(":")
        ident = ident.strip()
        file = ident if ("/" in ident or ident.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))) else None
        out.append(dict(id=Path(ident).stem if file else ident, scope=scope, desc=desc.strip(), file=file))
    return out


def bind_refs(refs, descriptions=None, files=None) -> list[dict]:
    """Fill each tag from the earlier stage's own prompt and, once that file exists, its path."""
    descriptions, files = descriptions or {}, files or {}
    bound = []
    for r in parse_scoped(refs):
        file = r.get("file") or files.get(r["id"])
        if file and not Path(str(file)).expanduser().exists():
            file = None
        bound.append(dict(id=r["id"], scope=r["scope"], desc=r["desc"] or descriptions.get(r["id"], ""),
                          file=str(file) if file else None))
    return bound


def _scope_line(scope: str, desc: str, file: str | None) -> str:
    desc = (desc or "as shown in the reference").strip().rstrip(".")
    lock = "100% matches the reference."
    where = f" Reference file: {file}." if file else ""
    if scope == "identity":
        return (f"IDENTITY ONLY: {desc}. {lock} Take only the person and the clothes, never the studio lighting. "
                f"Ignore its backdrop and layout.{where}")
    if scope == "product":
        return f"PRODUCT ONLY: {desc}. {lock} Take its shape, finish and colour 100%. Ignore its background.{where}"
    if scope == "prop":
        return f"PROP ONLY: {desc}. {lock} Take the object and its materials 100%. Ignore its background and its lighting.{where}"
    return (f"LOCATION ONLY: {desc}. Geography and materials only. {lock} "
            f"Do NOT take framing, do NOT take lighting, do NOT take any people from it.{where}")


def reference_block(refs: list[dict]) -> str:
    lines = [f"@{r['id']} — {_scope_line(r['scope'], r.get('desc') or '', r.get('file'))}" for r in refs]
    tail = ""
    if any(r["scope"] == "identity" for r in refs):
        tail = ("\n\nTake from every character reference ONLY the person or the animal and their clothes — "
                "never the studio lighting and never the backdrop.")
    return "\n\n".join(lines) + tail


def _as_list(v) -> list[str]:
    if not v:
        return []
    if isinstance(v, str):
        return [v.strip()] if v.strip() else []
    return [str(x).strip() for x in v if str(x).strip()]


def _beat_lines(prompt: str, beats, seconds: float) -> list[str]:
    if not beats:
        return [f"0.0–{seconds:g}s — {prompt.strip()}"]
    out = []
    for b in beats:
        if isinstance(b, dict):
            out.append(f"{b.get('t') or b.get('at')} — {b.get('text') or b.get('do') or ''}".strip())
        else:
            out.append(str(b).strip())
    return [x for x in out if x]


def _guard_for(stage, refs, people: bool, guard) -> str:
    if guard is not None:
        return GUARDS.get(guard, guard) or ""
    if stage == "character" or (stage == "shot" and (people or any(r["scope"] == "identity" for r in refs))):
        return NEG_PEOPLE
    return NEG


def _with_lock(text: str) -> str:
    if "100% matches the reference" in text:
        return text
    return text.rstrip() + "\n\n100% matches the reference."


def character_sheet(prompt: str) -> str:
    """Four-panel identity sheet. The wardrobe is only what `prompt` already says."""
    return (
        "A professional photoreal character reference sheet on one image, a collage of EXACTLY FOUR PANELS on a clean seamless "
        "light grey studio backdrop, soft even editorial lighting, consistent across every panel. THE SAME PERSON IN EVERY PANEL: "
        "identity locked, identical build, identical clothing, identical proportions. 100% matches the reference.\n\n"
        f"THE CHARACTER: {prompt.strip()}\n\n"
        "PANEL 1 — FULL LENGTH, FRONT: framed from the base of the neck down to the feet. The head and face are completely outside the frame.\n"
        "PANEL 2 — FULL LENGTH, FROM BEHIND: the same crop, head outside the frame.\n"
        "PANEL 3 — FACE, CLOSE-UP: head and shoulders, straight into the lens.\n"
        "PANEL 4 — FACE, IN STRICT SIDE PROFILE: head and shoulders.\n\n"
        "STYLE: photorealistic editorial photography, full-frame camera with a fast prime lens, soft even light, true colour, fine film grain. Neutral, unstylised.\n\n"
        "NEGATIVE: no fifth panel, no extra panels, no head or face in the two full-length panels, no text, no logos, no captions, "
        "no watermarks, no beauty filter, no airbrushing, no changing identity between panels, no changing clothing between panels, "
        "no props beyond what the character description names, no style drift."
    )


def _sentence(prompt: str) -> str:
    text = (prompt or "").strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


def prop_still(prompt: str) -> str:
    return (
        "A reference still of one prop or product, square-on, on a seamless light grey backdrop, soft even studio light, sharp. "
        f"{_sentence(prompt)} 100% matches the reference. Nothing else in the frame.\n\n"
        "NEGATIVE: no people, no hands unless the description names them, no extra objects, no background scene, no text, no logos, "
        "no watermarks, no style drift."
    )


def location_still(prompt: str) -> str:
    return (
        "A location reference photograph. Geography and materials only. "
        f"{_sentence(prompt)} 100% matches the reference. Empty of people. Neutral documentary daylight so a later shot can relight it. "
        "No readable signage.\n\n"
        "NEGATIVE: no people, no figures, no text, no logos, no watermarks, no stylised grade, no props that are not part of the place, no style drift."
    )


def shot_skeleton(prompt: str, *, seconds: float, aspect: str, refs: list[dict], beats, camera, optics, rules, positive, negative, audio) -> str:
    """One shot prompt: active references, a timed beat list, optics, camera, hard rules, positive constraints, negative, audio."""
    beat_lines = _beat_lines(prompt, beats, seconds)
    order = " ".join(f"{i}. {b}" for i, b in enumerate(beat_lines, 1))
    hard = _as_list(rules) or [
        "Only the people named in the active references appear.",
        "Do not take lighting, backdrop or layout from any reference still.",
        "Never reset the action, the wardrobe or the geography between beats.",
    ]
    pos = [
        "The order of beats is fixed and must not be swapped.",
        "Continuity across cuts: never reset. Same people, same clothes, same geography, same lighting direction, continuous action from the first frame to the last.",
        *_as_list(positive),
    ]
    neg = SHOT_NEGATIVE if not _as_list(negative) else SHOT_NEGATIVE + ", " + ", ".join(_as_list(negative))
    aud = (audio or "").strip() or "NO MUSIC. Real recorded sound only, matched to what is on screen. No dialogue unless the scene context names a line."
    opt = (optics or "").strip() or "Standard normal lens, zero distortion. The lens never changes during the take."
    cam = (camera or "").strip() or "One continuous camera. It never cuts and never resets."
    refs_txt = reference_block(refs) if refs else "None. Describe only what the scene context names."
    return (
        f"SCENE CONTEXT\n\n{prompt.strip()}\n\n"
        f"ACTIVE REFERENCES\n\n{refs_txt}\n\n"
        f"FORMAT: one continuous take, {seconds:g} seconds, aspect ratio {aspect}. No cuts. Continuity across cuts: never reset. "
        f"The order of beats is fixed.\n\n"
        f"THE ACTION — {seconds:g} SECONDS, EVERY BEAT MANDATORY\n\n" + "\n\n".join(beat_lines) + "\n\n"
        f"OPTICS\n\n{opt}\n\n"
        f"CAMERA\n\n{cam}\n\n"
        f"HARD RULES\n\n" + "\n".join(f"- {r}" for r in hard) + "\n\n"
        f"POSITIVE CONSTRAINTS\n\n" + "\n".join(f"- {p}" for p in pos) + f"\n\nBeat order: {order}\n\n"
        f"NEGATIVE\n\n{neg}.\n\n"
        f"AUDIO\n\n{aud}"
    )


def _already_rich(prompt: str) -> bool:
    folded = prompt.upper()
    return "ACTIVE REFERENCES" in folded and "NEGATIVE" in folded


def compose(prompt: str, *, stage: str | None = None, kind: str = "image", seconds: float = 8, aspect: str = "16:9",
            people: bool = False, refs=None, beats=None, camera=None, optics=None, rules=None, positive=None,
            negative=None, audio=None, guard: str | None = None, descriptions: dict | None = None, files: dict | None = None) -> str:
    """The text a generator should see for one stage. A terse line is expanded; a prompt that already has the skeleton is kept.
    No stage: the caller's words, unchanged (the plate guard is `prompt_for`'s job)."""
    if stage not in STAGES:
        return (prompt or "").strip()
    scoped = bind_refs(refs, descriptions, files)
    text = (prompt or "").strip()
    g = _guard_for(stage, scoped, people, guard)
    if stage == "shot" and _already_rich(text):
        body = text if "100% matches the reference" in text or not scoped else text.rstrip() + "\n\n" + reference_block(scoped)
    elif stage == "character":
        body = text if "PANEL 1" in text.upper() else character_sheet(text)
        body = _with_lock(body)
    elif stage == "prop":
        body = text if "100% matches the reference" in text else prop_still(text)
        if scoped:
            body = "ACTIVE REFERENCES\n\n" + reference_block(scoped) + "\n\n" + body
    elif stage == "location":
        body = text if "geography and materials only" in text.lower() else location_still(text)
        body = _with_lock(body)
        if scoped:
            body = "ACTIVE REFERENCES\n\n" + reference_block(scoped) + "\n\n" + body
    else:
        body = shot_skeleton(text, seconds=seconds, aspect=aspect, refs=scoped, beats=beats, camera=camera, optics=optics,
                             rules=rules, positive=positive, negative=negative, audio=audio)
    if g and g.strip() not in body:
        return f"{g.rstrip()}\n\n{body}"
    return body


def _manifest(spec) -> dict:
    from . import footage as FT
    try:
        return FT.load(spec)
    except Exception:
        return {}


def is_approved(man, cid: str) -> bool:
    c = (man or {}).get(cid) or {}
    path = c.get("path")
    if not path or not Path(path).exists():
        return False
    g = c.get("generated") or {}
    return bool(g.get("approved") or c.get("approved"))


def _wait(stage: str, entry: dict, man: dict) -> str:
    cid, got = entry["id"], entry.get("stage")
    clip = man.get(cid) or {}
    if clip.get("generated") and not (clip.get("generated") or {}).get("approved"):
        return f"stage {stage} waits on {got} {cid}: `promo gen approve {cid}`"
    if clip and not clip.get("generated") and not clip.get("approved"):
        return f"stage {stage} waits on {got} {cid}: `promo gen approve {cid}`"
    return f"stage {stage} waits on {got} {cid}: generate it, `promo gen register` it, then `promo gen approve {cid}`"


def block_reason(spec, entry, man=None) -> str | None:
    """Why this staged entry must not be generated yet. Plain plates (no `stage`) are never blocked."""
    stage = entry.get("stage")
    if stage not in STAGES:
        return None
    if man is None:
        man = _manifest(spec)
    idx = STAGES.index(stage)
    earlier = set(STAGES[:idx])
    entries = broll_entries(spec)
    by_id = {b["id"]: b for b in entries}
    for r in parse_scoped(entry.get("refs")):
        target = by_id.get(r["id"])
        if target is None:
            return f"{entry.get('id')} tags @{r['id']}, which is not a broll id"
        got = target.get("stage")
        if got not in earlier:
            return f"{entry.get('id')} tags @{r['id']} ({got}); a {stage} may only tag earlier stages"
        if got != _SCOPE_STAGE[r["scope"]]:
            return f"{entry.get('id')} tags @{r['id']} as {r['scope']}; that id is a {got}"
    for b in entries:
        if b.get("stage") in earlier and b["id"] != entry.get("id") and not is_approved(man, b["id"]):
            return _wait(stage, b, man)
    return None


def approve(spec, cid: str) -> dict:
    """Lock one registered clip so later stages may consume it. Idempotent."""
    from . import footage as FT
    man = FT.load(spec)
    if cid not in man:
        raise SystemExit(f"{cid} is not in the footage manifest")
    clips = FT.load_raw(FT.manifest_path(spec))
    for c in clips:
        if c.get("id") != cid:
            continue
        if c.get("generated"):
            c["generated"] = dict(c["generated"], approved=True, approved_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        else:
            c["approved"] = True
        break
    FT.save(spec, clips)
    side = Path(str(man[cid]["path"]) + ".gen.json")
    if side.is_file():
        meta = json.loads(side.read_text())
        meta["approved"] = True
        side.write_text(json.dumps(meta, indent=1))
    return dict(id=cid, approved=True)


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
    out.append(dict(id="openrouter", kind=["video"], tool="openrouter" if OR.has_key() else None, login=OR.has_key(),
                    how=f"OPENROUTER_API_KEY: Seedance / Grok Imagine, pay per job (default {OR.DEFAULT_MODEL} {OR.DEFAULT_RES} {OR.DEFAULT_SECONDS} s); `promo gen models` for prices"))
    if os.environ.get("PROMO_GEN_STUB") == "1":
        out.append(dict(id="stub", kind=["image", "video"], tool="stub", login=True, how="PROMO_GEN_STUB=1: a labelled placeholder in a second, no model (UI work, tests)"))
    for p in out:
        p["available"] = bool(p["tool"] and p["login"])
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
    if os.environ.get("PROMO_GEN_STUB") == "1":
        ps = [p for p in ps if p["id"] == "stub"]                       # a stubbed run never reaches a real generator
    ps = [p for p in ps if p["id"] == provider] if provider != "auto" else [p for p in ps if p["id"] != "openrouter"]     # auto never spends money
    if not ps:
        raise SystemExit(f"no available provider for {kind} (provider={provider}); run `promo gen detect`")
    ps.sort(key=lambda p: (kind not in p["verified"], p["id"] not in ("grok", "codex")))
    return ps


def pick(kind: str, provider: str = "auto") -> dict:
    return providers(kind, provider)[0]


def parse_refs(ref) -> list[tuple[str, str]]:
    """[(role, file)] from `--ref` values: `ROLE=FILE` (roles in REF_ROLES) or a bare file (first = identity, second = set)."""
    refs = [ref] if isinstance(ref, str) else list(ref or [])
    out = []
    for i, r in enumerate(refs):
        if isinstance(r, (tuple, list)):
            out.append((str(r[0]), str(r[1])))
            continue
        role, _, f = str(r).partition("=")
        if f and role in REF_ROLES:
            out.append((role, f))
        else:
            out.append(("identity" if i == 0 else "set", str(r)))
    return out


def _tool_wrap(kind: str, body: str, out: Path, seconds: float, aspect: str, first_frame, resolution) -> str:
    if kind == "video":
        tool = (f"Use your image_to_video tool on {first_frame}" + (f" with resolution_name {resolution}" if resolution else "")
                + f" and duration {6 if seconds <= 6 else 10}. ") if first_frame else (
            f"Generate a {seconds:g} second {aspect} VIDEO{' at ' + resolution if resolution else ''} using your video generation tool. ")
        return f"{tool}{body} Copy the resulting video file unmodified (no trimming, no re-encoding) to {out} (mp4) and print only that path."
    return f"Generate one {aspect} IMAGE using your image generation tool. {body} Save the image to {out} (png) and print only that path."


def prompt_for(kind: str, prompt: str, out: Path, seconds: float, aspect: str, people: bool = False, ref=None, guard: str | None = None,
               first_frame=None, resolution: str | None = None, stage: str | None = None, beats=None, camera=None, optics=None,
               rules=None, positive=None, negative=None, audio=None, descriptions=None, files=None) -> str:
    """`guard`: free text, or a GUARDS name (plate / people / illustrated). `first_frame` is the `keyframe` reference role.
    `stage` expands a terse line into that stage's template; the plate path (no stage) is unchanged."""
    if stage in STAGES:
        body = compose(prompt, stage=stage, kind=kind, seconds=seconds, aspect=aspect, people=people, refs=ref, beats=beats,
                       camera=camera, optics=optics, rules=rules, positive=positive, negative=negative, audio=audio, guard=guard,
                       descriptions=descriptions, files=files)
        return _tool_wrap(kind, body, out, seconds, aspect, first_frame, resolution)
    g = GUARDS.get(guard, guard) if guard is not None else (NEG_PEOPLE if people else NEG)
    base = f"{g}{prompt.strip()} "
    refs = parse_refs(ref)
    if first_frame and not any(r == "keyframe" for r, _ in refs):
        refs.append(("keyframe", str(first_frame)))
    if refs:
        base = "".join(REF_ROLES[r].format(f=f) for r, f in refs) + base
    keyframe = next((f for r, f in refs if r == "keyframe"), None)
    if kind == "video":
        tool = (f"Use your image_to_video tool on {keyframe}" + (f" with resolution_name {resolution}" if resolution else "")
                + f" and duration {6 if seconds <= 6 else 10}. ") if keyframe else (
            f"Generate a {seconds:g} second {aspect} VIDEO{' at ' + resolution if resolution else ''} using your video generation tool. ")
        return (f"{tool}{base}Copy the resulting video file unmodified (no trimming, no re-encoding) to {out} (mp4) and print only that path.")
    tool = (f"Use your image_edit tool with the reference images {', '.join(f for _, f in refs)} to make one NEW {aspect} IMAGE. "
            if refs else f"Generate one {aspect} IMAGE using your image generation tool. ")
    return f"{tool}{base}Save the image to {out} (png) and print only that path."


def argv_for(provider: dict, text: str) -> list[str]:
    if provider["id"] == "grok":
        return ["grok", "-p", text]
    if provider["id"] == "codex":
        return ["codex", "exec", "--skip-git-repo-check", "-s", "workspace-write", text]
    raise SystemExit(f"{provider['id']}: no headless command; use the grok or codex CLI")


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
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf", vf, "-map", "0:v", "-map", "0:a?", "-c:v", "libx264", "-crf", "18",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", str(path)]      # keep the generator's audio (voices, ambience)
    else:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw), "-vf", vf, str(path)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        shutil.copyfile(raw, path)
        return None
    return f"cropped to top-left {keep:.0%}, scaled to 1920x1080"


def register(spec, file: str, cid: str, provider: str = "agent", prompt: str = "", shots=(), kind: str | None = None,
             watermark: str | None = None, aspect: str = "16:9", stage: str | None = None) -> dict:
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
    generated = {k: meta[k] for k in ("provider", "kind", "prompt", "at", "sha256")}
    if stage in STAGES:
        generated["stage"] = stage
        generated["approved"] = False
        meta["stage"] = stage
        meta["approved"] = False
    Path(str(f) + ".gen.json").write_text(json.dumps(meta, indent=1))
    e = FT.add(spec, str(f), cid, shots=list(shots), capture=f"generated by {provider}", framing="generated plate, text-free, UI-free",
               dpr=1, notes=f"AI-generated plate: {prompt[:200]}", generated=generated)
    meta["registered"] = e["id"]
    meta["next"] = (f"reference it as `source: {cid}` (or `still: {cid}`) on a shot with `ui: false`; `promo check` gates generated-plates; "
                    "a human reviews generated plates before publishing")
    return meta


def register_existing(spec, file: str, cid: str, shots=()) -> dict:
    """Footage-manifest entry for a file `generate` already made (its sidecar `.gen.json` is kept as written)."""
    from . import footage as FT
    f = Path(file).resolve()
    meta = json.loads(Path(str(f) + ".gen.json").read_text())
    generated = {k: meta.get(k) for k in ("provider", "kind", "prompt", "at", "sha256", "bible")}
    if meta.get("stage") in STAGES:
        generated["stage"] = meta["stage"]
        generated["approved"] = bool(meta.get("approved"))
    return FT.add(spec, str(f), cid, shots=list(shots), capture=f"generated by {meta.get('provider')}", framing="generated plate, text-free, UI-free",
                  dpr=1, notes=f"AI-generated plate: {meta.get('prompt', '')[:200]}", generated=generated)


def _shot_fields(b) -> dict:
    return {k: b.get(k) for k in ("refs", "beats", "camera", "optics", "rules", "positive", "negative", "audio") if b.get(k) is not None}


def requests(spec) -> list[dict]:
    """Open generation requests from `broll:` with everything an agent needs to fulfil them with any tool.
    Staged entries carry the expanded prompt and `blocked` until earlier stages are approved."""
    man = _manifest(spec)
    entries = broll_entries(spec)
    descriptions = {b["id"]: (b.get("prompt") or "").strip() for b in entries}
    files = {cid: c["path"] for cid, c in man.items() if c.get("path") and Path(c["path"]).exists()}
    rows = []
    for b in entries:
        kind = b["kind"]
        if b["id"] in man and Path(man[b["id"]]["path"]).exists():       # already registered (possibly generated for another project)
            b["out"] = man[b["id"]]["path"]
        stage = b.get("stage") if b.get("stage") in STAGES else None
        sec = float(b.get("seconds", 8.0 if stage == "shot" else 4.0))
        asp = b.get("aspect", "16:9")
        fields = _shot_fields(b)
        if stage:
            prompt = compose(b["prompt"], stage=stage, kind=kind, seconds=sec, aspect=asp, refs=b.get("refs"), beats=b.get("beats"),
                             camera=b.get("camera"), optics=b.get("optics"), rules=b.get("rules"), positive=b.get("positive"),
                             negative=b.get("negative"), audio=b.get("audio"), descriptions=descriptions, files=files)
        else:
            prompt = prompt_for(kind, b["prompt"], Path(b["out"]), sec, asp)
        blocked = block_reason(spec, b, man)
        rows.append(dict(id=b["id"], kind=kind, out=b["out"], exists=Path(b["out"]).exists(), seconds=sec if kind == "video" else None,
                         aspect=asp, min_size="1920x1080 preferred (720p is cropped/upscaled on register)",
                         prompt=prompt, raw_prompt=b["prompt"], stage=stage, blocked=blocked, provider=b.get("provider", "auto"),
                         model=b.get("model"), resolution=b.get("resolution"), **fields,
                         then=f"promo gen register {b['out']} -p <promo.yaml> --id {b['id']} --prompt \"...\" --shots <ids>"))
    return rows


def _run_provider(p: dict, text: str, out_p: Path, timeout: int) -> str:
    """Run one provider; returns '' when it wrote `out_p`, else why it did not."""
    if p["id"] == "stub":
        _stub(text, out_p)
        return ""
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


def _stub(text: str, out_p: Path):
    """A placeholder the size of a real frame, its hue from the prompt so different prompts look different on the board."""
    from PIL import Image, ImageDraw
    h = hashlib.sha256(text.encode()).digest()
    im = Image.new("RGB", (1280, 720), (h[0] // 2, h[1] // 2, 60 + h[2] // 3))
    ImageDraw.Draw(im).text((40, 640), "STUB " + out_p.stem.lstrip("."), fill=(235, 235, 235))
    if out_p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        im.save(out_p)
        return
    png = out_p.with_suffix(".stub.png")
    im.save(png)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(png), "-t", "2", "-r", "24", "-pix_fmt", "yuv420p", str(out_p)], check=True)
    png.unlink()


def generate_openrouter(prompt: str, out: str, seconds: float = OR.DEFAULT_SECONDS, aspect: str = "16:9", people: bool = False,
                        model: str = OR.DEFAULT_MODEL, resolution: str = OR.DEFAULT_RES, first_frame=None, audio: bool = False,
                        max_usd: float = OR.DEFAULT_MAX_USD, on_status=None, seed: int | None = None, last_frame=None,
                        guarded: bool = True) -> dict:
    """A video plate through OpenRouter (Seedance, Grok Imagine). The plate guard leads a raw prompt; a prompt `compose` already
    guarded (`guarded=False`) is sent as-is. The sidecar keeps the model, the job id and the real cost."""
    m = OR.model(model)
    if OR.is_edit(m):
        raise OR.OpenRouterError(f"{m['name']} edits a clip; restyle a take instead (promo flow studio restyle)")
    OR.check_params(m, int(seconds), resolution, aspect)
    text = ((NEG_PEOPLE if people else NEG) + prompt.strip()) if guarded else prompt
    body = OR.body_for(m, text, int(seconds), resolution, aspect, first_frame, audio, seed, last_frame)
    return openrouter_send(body, out, max_usd, on_status, prompt=prompt)


def openrouter_send(body: dict, out: str, max_usd: float = OR.DEFAULT_MAX_USD, on_status=None, prompt: str | None = None, seconds: float | None = None,
                    source: str | None = None) -> dict:
    """Send one stored OpenRouter request (a new one, or an earlier take's `request` again) and write the plate's sidecar.
    `seconds` and `source` are an edit job's source clip: its length prices the job, and the sidecar names it."""
    out_p = Path(out).expanduser().resolve()
    job = OR.send(body, out_p, max_usd, on_status, seconds=seconds)
    frames = {f["frame_type"]: f["image_url"]["url"][len(OR.FILE):] for f in body.get("frame_images") or []}
    meta = dict(generated=True, kind="video", watermark_cropped=None, provider=f"openrouter:{body['model']}", prompt=prompt or body["prompt"],
                seconds=body.get("duration", seconds), aspect=body.get("aspect_ratio"), resolution=body.get("resolution"), first_frame=frames.get("first_frame"),
                last_frame=frames.get("last_frame"), source=source, audio=bool(body.get("generate_audio")), seed=body.get("seed"), job_id=job["job_id"],
                cost_usd=job["cost"], estimate_usd=job["estimate"], request=body, sha256=sha256(out_p), at=time.strftime("%Y-%m-%dT%H:%M:%S"), **probe_media(out_p))
    Path(str(out_p) + ".gen.json").write_text(json.dumps(meta, indent=1))
    _mark_ok("openrouter", "video")
    return meta


def generate(kind: str, prompt: str, out: str, seconds: float = 4.0, aspect: str = "16:9", provider: str = "auto",
             timeout: int = 900, people: bool = False, ref=None, guard: str | None = None, first_frame=None, resolution: str | None = None, extra=None,
             stage: str | None = None, beats=None, camera=None, optics=None, rules=None, positive=None, negative=None, audio=None,
             descriptions=None, files=None) -> dict:
    """`guard` replaces the plate guard (no UI, no text) for callers that need another look, e.g. STORYBOARD stills; their corner logo is the caller's to crop.
    `stage` sends the expanded template instead of the one-line plate prompt."""
    out_p = Path(out).expanduser().resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    text = prompt_for(kind, prompt, out_p, seconds, aspect, people, ref, guard, first_frame=first_frame, resolution=resolution,
                      stage=stage, beats=beats, camera=camera, optics=optics, rules=rules, positive=positive, negative=negative, audio=audio,
                      descriptions=descriptions, files=files)
    why = []
    for p in providers(kind, provider):
        err = _run_provider(p, text, out_p, timeout)
        if not err:
            break
        why.append(err)
    else:
        raise RuntimeError("; ".join(why))
    wm = strip_watermark(out_p, kind) if p["id"] == "grok" and guard in (None, "plate", "people", "illustrated") else None
    sent = compose(prompt, stage=stage, kind=kind, seconds=seconds, aspect=aspect, people=people, refs=ref, beats=beats, camera=camera,
                   optics=optics, rules=rules, positive=positive, negative=negative, audio=audio, guard=guard, descriptions=descriptions,
                   files=files) if stage in STAGES else prompt
    scoped = bind_refs(ref, descriptions, files) if stage in STAGES else []
    recorded = [dict(id=r["id"], scope=r["scope"], file=r["file"]) for r in scoped] or [dict(role=r, file=f) for r, f in parse_refs(ref)]
    meta = dict(generated=True, kind=kind, watermark_cropped=wm, provider=p["id"], prompt=sent, seconds=seconds if kind == "video" else None, aspect=aspect,
                refs=recorded, guard=guard, sha256=sha256(out_p), at=time.strftime("%Y-%m-%dT%H:%M:%S"), **probe_media(out_p), **(extra or {}))
    if stage in STAGES:
        meta["stage"] = stage
        meta["approved"] = False
        meta["raw_prompt"] = prompt
    Path(str(out_p) + ".gen.json").write_text(json.dumps(meta, indent=1))
    _mark_ok(p["id"], kind)
    return meta


# ---------------------------------------------------------------- spec side: `broll:` plan + the plate gate
def broll_entries(spec) -> list[dict]:
    """promo.yaml `broll:` entries (out defaults to media/gen/<id>.mp4|png). A plain plate is `{id, kind, prompt, seconds, aspect}`.
    A staged spot adds `stage: character|prop|location|shot` and, on a shot, `refs`, `beats`, `camera`, `optics` and the other skeleton fields.
    `provider: openrouter` entries may add `model` and `resolution`."""
    res = []
    for b in spec.raw.get("broll") or []:
        b = dict(b)
        b.setdefault("kind", "video")
        ext = "mp4" if b["kind"] == "video" else "png"
        b["out"] = str(spec.resolve(b.get("out") or f"media/gen/{b['id']}.{ext}"))
        res.append(b)
    return res


def plan(spec, run=False):
    """Same rows as `requests`. `--run` generates only entries that are missing and not blocked.
    A staged run sends the same prompt `requests` shows: earlier stages' own words and files, not a second paraphrase."""
    queued = requests(spec)
    descriptions = {q["id"]: q["raw_prompt"] for q in queued}
    files = {cid: c["path"] for cid, c in _manifest(spec).items() if c.get("path") and Path(c["path"]).exists()}
    rows = []
    for q in queued:
        row = dict(id=q["id"], kind=q["kind"], out=q["out"], exists=q["exists"], ran=False, blocked=q.get("blocked"), stage=q.get("stage"))
        if run and not q["exists"]:
            if q.get("blocked"):
                row["error"] = q["blocked"]
            elif q.get("provider") == "openrouter":
                row["meta"] = generate_openrouter(q["prompt"] if q.get("stage") else q["raw_prompt"], q["out"],
                                                  q.get("seconds") or OR.DEFAULT_SECONDS, q.get("aspect") or "16:9",
                                                  model=q.get("model") or OR.DEFAULT_MODEL, resolution=q.get("resolution") or OR.DEFAULT_RES,
                                                  guarded=not q.get("stage"))
                row["ran"] = True
                row["exists"] = True
            else:
                row["meta"] = generate(q["kind"], q["raw_prompt"], q["out"], q.get("seconds") or 4.0, q.get("aspect") or "16:9",
                                       q.get("provider") or "auto", stage=q.get("stage"), ref=q.get("refs"), beats=q.get("beats"),
                                       camera=q.get("camera"), optics=q.get("optics"), rules=q.get("rules"), positive=q.get("positive"),
                                       negative=q.get("negative"), audio=q.get("audio"), descriptions=descriptions, files=files)
                row["ran"] = True
                row["exists"] = True
        rows.append(row)
    return rows


def plate_gate(spec) -> list[tuple[str, str, str]]:
    """promo check: generated clips may only feed UI-free shots, except the person's own likeness (generated.likeness: own,
    with a consent note), which may only appear in an `avatar` overlay (team rule 1 carve-out)."""
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
    avatars = {(s.id, o.get("source")) for s in spec.shots for o in (s.get("overlays") or []) if o.get("type") == "avatar"}
    for cid in gen:
        own = gen[cid]["generated"].get("likeness") == "own"
        if own and not str(gen[cid]["generated"].get("consent") or "").strip():
            bad.append(f"generated likeness {cid} has no consent note (who agreed, when)")
        for sid in refs.get(cid, []):
            used.append(f"{cid}->{sid}")
            s = shots.get(sid)
            # a generated clip used only as the blurred BACKDROP plate behind a UI panel is scenery, not the picture: allowed
            shows = s is not None and cid in {s.get(k) for k in ("source", "still", "board", "node")}
            if (sid, cid) in avatars and not own:
                bad.append(f"generated clip {cid} in an avatar overlay of shot {sid} (only a clip with generated.likeness: own)")
            if own and (shows or (sid, cid) not in avatars):
                bad.append(f"generated likeness {cid} used by {sid} outside an avatar overlay")
            if own or s is not None and not shows:
                continue
            if s is not None and (s.get("ui") is True or s.get("ui") is None and s.type in ("clip",)):
                bad.append(f"generated clip {cid} used by UI shot {sid} (set ui: false only if the plate shows no app UI)")
            elif s is None:
                bad.append(f"generated clip {cid} used by {sid} (plates must be declared ui: false shots)")
    out = [("generated-plates", "FAIL" if bad else "PASS", "; ".join(bad) or "generated clips only on UI-free shots")]
    if used:
        out.append(("generated-review", "WARN", "HUMAN: review generated plates before publishing: " + ", ".join(sorted(used))))
    return out


def _stage_args(q, default_stage=None):
    q.add_argument("--stage", choices=STAGES, default=default_stage, help="character, then prop, then location, then shot")
    q.add_argument("--ref", action="append", help="SCOPE=ID[:description] (identity|product|prop|geography) or ROLE=FILE (character|style|keyframe|identity|set)")
    q.add_argument("--beat", action="append", dest="beats", help="one timed beat, repeatable; the order is fixed")
    q.add_argument("--camera")
    q.add_argument("--optics")
    q.add_argument("--rule", action="append", dest="rules")
    q.add_argument("--positive", action="append")
    q.add_argument("--negative", action="append", dest="negatives")
    q.add_argument("--sound", dest="line_audio", help="AUDIO section: real recorded sound")


def _stage_kwargs(a) -> dict:
    return dict(stage=a.stage, refs=a.ref, beats=a.beats, camera=a.camera, optics=a.optics, rules=a.rules,
                positive=a.positive, negative=a.negatives, audio=a.line_audio)


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="promo gen", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--json", action="store_true")
    for k in ("models", "spend"):
        sub.add_parser(k).add_argument("--json", action="store_true")
    for k in ("image", "video"):
        q = sub.add_parser(k)
        q.add_argument("prompt")
        q.add_argument("--out", required=True)
        q.add_argument("--provider", default="auto")
        q.add_argument("--aspect", default="16:9")
        q.add_argument("--guard", choices=sorted(GUARDS), help="content guard (default plate; people with --people; illustrated for anime-mv characters)")
        q.add_argument("--people", action="store_true", help="the scene may contain people (live-action film); text/logo/UI-on-screen guard stays on")
        q.add_argument("--register", metavar="PROJECT_YAML", help="add the file to that project's footage manifest (generated: ...)")
        q.add_argument("--id", help="clip id for --register (default: file stem)")
        q.add_argument("--shots", nargs="*", default=[], help="shot ids that will use it")
        _stage_args(q)
        if k == "video":
            q.add_argument("--seconds", type=float, default=4.0)
            q.add_argument("--model", default=OR.DEFAULT_MODEL, help="openrouter: model id (`promo gen models`)")
            q.add_argument("--res", default=OR.DEFAULT_RES, help="480p | 720p | 1080p | 4K, as the model allows (openrouter; grok takes 480p or 720p)")
            q.add_argument("--first-frame", help="image the clip starts from (animate a still; openrouter and grok)")
            q.add_argument("--last-frame", help="image the clip ends on (openrouter models that list last_frame, e.g. Seedance 2.5)")
            q.add_argument("--audio", action="store_true", help="openrouter: let the model make sound too (Seedance only; dearer on some models)")
            q.add_argument("--max-usd", type=float, default=OR.DEFAULT_MAX_USD, help="openrouter: refuse a job priced above this")
            q.add_argument("--dry-run", action="store_true", help="print the prompt and, for openrouter, its price; submit nothing")
    pr = sub.add_parser("prompt", help="print a terse line and the expanded prompt; calls nothing")
    pr.add_argument("prompt")
    pr.add_argument("--seconds", type=float, default=8)
    pr.add_argument("--aspect", default="16:9")
    pr.add_argument("--people", action="store_true")
    pr.add_argument("--json", action="store_true")
    _stage_args(pr, default_stage="shot")
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
    rg.add_argument("--stage", choices=STAGES)
    rg.add_argument("--watermark", choices=["br"], help="crop a bottom-right corner logo (Grok) and upscale to 1080p")
    ok = sub.add_parser("approve", help="lock a registered reference so later stages may use it")
    ok.add_argument("id")
    ok.add_argument("-p", "--project", default="promo.yaml")
    a = ap.parse_args(argv)
    if a.cmd == "detect":
        ps = detect()
        if a.json:
            print(json.dumps(ps, indent=1))
        else:
            for p in ps:
                print(f"{p['id']:<11} {'READY' if p['available'] else 'no   '}  kinds={','.join(p['kind']):<12} verified={','.join(p['verified']) or '-':<12} {p['how']}")
        return 0
    if a.cmd == "models":
        rows = OR.price_table(OR.models())
        if a.json:
            print(json.dumps(rows, indent=1))
            return 0
        for r in rows:
            print(f"{r['id']:<30} {r['seconds'][0]}-{r['seconds'][1]} s  {'  '.join(f'{k} ${v:.2f}' for k, v in r['price_4s'].items()):<44} per 4 s 16:9, no audio")
        return 0
    if a.cmd == "spend":
        sp = OR.spend()
        print(json.dumps(sp, indent=1) if a.json else f"OpenRouter today ${sp['today']:.2f} of ${OR.daily_cap():.2f} cap, all time ${sp['total']:.2f}, {len(sp['jobs'])} jobs")
        return 0
    if a.cmd == "prompt":
        after = compose(a.prompt, kind="video", seconds=a.seconds, aspect=a.aspect, people=a.people, **_stage_kwargs(a))
        if a.json:
            print(json.dumps(dict(before=a.prompt, after=after), indent=1))
        else:
            print("BEFORE\n" + a.prompt + "\n\nAFTER\n" + after)
        return 0
    if a.cmd == "video" and getattr(a, "dry_run", False) and a.provider != "openrouter":
        after = compose(a.prompt, kind="video", seconds=a.seconds, aspect=a.aspect, people=a.people, guard=a.guard, **_stage_kwargs(a)) if a.stage else prompt_for(
            "video", a.prompt, Path(a.out), a.seconds, a.aspect, a.people, a.ref, a.guard, first_frame=a.first_frame)
        print("BEFORE\n" + a.prompt + "\n\nAFTER\n" + after)
        return 0
    if a.cmd == "video" and a.provider == "openrouter":
        try:
            fields = _stage_kwargs(a)
            composed = compose(a.prompt, kind="video", seconds=a.seconds, aspect=a.aspect, people=a.people, guard=a.guard, **fields) if a.stage else None
            if a.dry_run:
                m = OR.model(a.model)
                OR.check_params(m, int(a.seconds), a.res, a.aspect)
                text = composed if composed is not None else NEG + a.prompt
                body = OR.body_for(m, text, a.seconds, a.res, a.aspect, a.first_frame, a.audio, last_frame=a.last_frame)
                print(json.dumps(dict(before=a.prompt, after=text, request=body, estimate_usd=OR.price_of(m, body)), indent=1))
                return 0
            meta = generate_openrouter(composed or a.prompt, a.out, int(a.seconds), a.aspect, a.people, a.model, a.res, a.first_frame, a.audio, a.max_usd,
                                       on_status=lambda s, j: print(f"  {s} ({j})", file=sys.stderr), last_frame=a.last_frame, guarded=composed is None)
        except OR.OpenRouterError as e:
            raise SystemExit(f"promo gen: {e}") from None
    elif a.cmd == "video":
        meta = generate(a.cmd, a.prompt, a.out, a.seconds, a.aspect, a.provider, people=a.people, ref=a.ref, first_frame=a.first_frame,
                        resolution=a.res if a.res != OR.DEFAULT_RES else None, guard=a.guard, beats=a.beats, camera=a.camera, optics=a.optics,
                        rules=a.rules, positive=a.positive, negative=a.negatives, audio=a.line_audio, stage=a.stage)
    elif a.cmd == "image":
        meta = generate(a.cmd, a.prompt, a.out, 4.0, a.aspect, a.provider, people=a.people, ref=a.ref, guard=a.guard, beats=a.beats,
                        camera=a.camera, optics=a.optics, rules=a.rules, positive=a.positive, negative=a.negatives, audio=a.line_audio, stage=a.stage)
    if a.cmd in ("image", "video"):
        if a.register:
            from . import footage as FT
            from .spec import load_spec as _ls
            generated = {k: meta[k] for k in ("provider", "kind", "prompt", "at", "sha256", "stage", "approved") if k in meta}
            e = FT.add(_ls(a.register), a.out, a.id or Path(a.out).stem, shots=a.shots, capture=f"promo gen {a.cmd} ({meta['provider']})",
                       framing="generated plate, text-free, UI-free", dpr=1, notes=f"AI-generated: {a.prompt[:200]}", generated=generated)
            meta["registered"] = e["id"]
        print(json.dumps(meta, indent=1))
        return 0
    from .spec import load_spec
    if a.cmd == "approve":
        print(json.dumps(approve(load_spec(a.project), a.id), indent=1))
        return 0
    if a.cmd == "register":
        print(json.dumps(register(load_spec(a.project), a.file, a.id, a.provider, a.prompt, a.shots, a.kind, a.watermark, stage=a.stage), indent=1))
        return 0
    if a.cmd == "plan" and not a.run:
        rq = requests(load_spec(a.project))
        if a.json:
            print(json.dumps(rq, indent=1))
        else:
            for r in rq:
                state = "exists" if r["exists"] else ("BLOCKED" if r.get("blocked") else "OPEN")
                print(f"{r['id']:<20} {r['kind']:<6} {state:<8} {r['out']}")
                if r.get("blocked"):
                    print(f"    {r['blocked']}")
                if r.get("stage"):
                    print(f"    before: {r['raw_prompt']}")
                print(f"    prompt: {r['prompt']}")
        return 0
    for r in plan(load_spec(a.project), a.run):
        state = "exists" if r["exists"] and not r["ran"] else ("generated" if r["ran"] else ("BLOCKED" if r.get("blocked") else "MISSING"))
        print(f"{r['id']:<20} {r['kind']:<6} {state:<10} {r['out']}")
        if r.get("error"):
            print(f"    {r['error']}")
    return 0
