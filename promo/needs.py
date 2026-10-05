"""`promo needs`: the handoff. promo-reel says what it still needs; the calling agent fulfils it with whatever it is harnessed with
(its own tools, grok, codex/GPT, a human with a screen recorder) and hands the file back. promo-reel never decides HOW.

    promo -p projects/<n>/promo.yaml needs [--json]

Request kinds (each has `then`: the exact command that ingests the answer):
  capture    a clip the spec references that is missing/stale in the footage manifest, or a `placeholder:` slate. REAL app footage only:
             follow capture/README.md (or ask the app owner); register with `promo footage add`.
  generate   a `broll:` entry whose file does not exist: a text-free, UI-free plate (background, transition, texture). Make it with any
             image/video tool, then `promo gen register`. Never for app UI.
  review     (HUMAN) generated plates in use; nothing to produce, someone must look.
"""
from __future__ import annotations

from . import footage as FT
from . import genvideo as G


def collect(spec) -> list[dict]:
    needs: list[dict] = []
    p = spec.path if hasattr(spec, "path") else "<promo.yaml>"
    for r in FT.verify(spec):
        if not r["ok"]:
            needs.append(dict(kind="capture", id=r["id"], for_shots=r["shots"], why=r["error"],
                              spec="real app footage, DPR 2 / 3840x2160 preferred, 60 fps, locked framing, 1 s handles (capture/README.md)",
                              then=f"promo -p {p} footage add <abs path> --id {r['id']} --shots {' '.join(r['shots'])} --commit <app sha> --capture '<params>' --framing '...' --dpr 2"))
    for s in spec.shots:
        ph = s.cfg.get("placeholder")
        if ph:
            needs.append(dict(kind="capture", id=ph.get("id", s.id), for_shots=[s.id], why="placeholder slate",
                              spec=ph.get("expects") or ph.get("label") or "see shot list",
                              then=f"register the take, then replace `placeholder:` on shot {s.id} with `source: <clip id>` + `cam:`"))
    for q in G.requests(spec):
        if not q["exists"]:
            needs.append(dict(kind="generate", id=q["id"], media=q["kind"], out=q["out"], seconds=q["seconds"], aspect=q["aspect"],
                              prompt=q["prompt"], why="broll entry has no file",
                              then=f"promo -p {p} gen register {q['out']} --id {q['id']} --prompt '<raw prompt>' --provider <who made it> --shots <ids>"))
    man = FT.load(spec) if FT.os.path.exists(FT.manifest_path(spec)) else {}
    gen = sorted(cid for cid, c in man.items() if c.get("generated") and FT.referenced(spec).get(cid))
    if gen:
        needs.append(dict(kind="review", id="generated-plates", why="AI-generated plates are in the cut: " + ", ".join(gen),
                          then="HUMAN: watch them; confirm no UI, text, logos or product-like imagery"))
    return needs


def main(spec, as_json=False):
    import json
    n = collect(spec)
    if as_json:
        print(json.dumps(dict(ok=not any(x["kind"] != "review" for x in n), needs=n), indent=1))
    else:
        if not n:
            print("nothing outstanding")
        for x in n:
            print(f"[{x['kind']:<8}] {x['id']}  {x.get('why', '')}")
            for k in ("spec", "prompt", "out"):
                if x.get(k):
                    print(f"           {k}: {x[k]}")
            print(f"           then: {x['then']}")
    return 0
