"""Assets manifest (assets.yaml): validation (licence gate) + fetch.

Each asset: id, kind (music|vo_model|vo|sfx|footage|font|still|live2d_model|live2d_runtime), path (relative to the spec dir, env expansion ok), licence,
source_url, optional fetch_url / sha256 / redistributable / attribution / notes / status (`draft` = licence terms
still being confirmed: `promo check` WARNs on it, `promo publish` must not go out until it is cleared).
Hard gate: every manifest entry needs a non-empty licence; music/vo_model/sfx also need source_url; every asset id
referenced by the spec must exist in the manifest.
"""
from __future__ import annotations

import hashlib
import os
import urllib.request

import yaml

from .spec import SpecError, expand_env

KINDS = {"music", "vo_model", "vo", "sfx", "footage", "font", "still", "live2d_model", "live2d_runtime"}
GATED = {"music", "vo_model", "vo", "sfx", "live2d_model", "live2d_runtime"}            # vo = pre-rendered voice-over files (a directory)          # these also need source_url
GENERATED = {"sfx"}                           # produced by `promo sfx`, never fetched


class AssetError(SpecError):
    pass


def manifest_file(spec):
    return spec.resolve(spec.raw.get("assets", "assets.yaml"))


def load_manifest(spec):
    """Return {id: asset dict with absolute `abs_path`}. Raises AssetError if the file is missing/malformed."""
    p = manifest_file(spec)
    if not os.path.exists(p):
        raise AssetError(f"assets manifest not found: {p}")
    with open(p) as f:
        raw = expand_env(yaml.safe_load(f) or {})
    items = raw.get("assets", raw) if isinstance(raw, dict) else raw
    out = {}
    for a in items or []:
        if "id" not in a:
            raise AssetError(f"asset without id in {p}: {a}")
        if a["id"] in out:
            raise AssetError(f"duplicate asset id {a['id']}")
        a = dict(a)
        a["abs_path"] = spec.resolve(a["path"]) if a.get("path") else None
        out[a["id"]] = a
    return out


def referenced_ids(spec):
    """Asset ids the spec uses (music, vo models, sfx library)."""
    ids = []
    m = spec.raw.get("music", {})
    if m.get("asset"):
        ids.append(m["asset"])
    vo = spec.raw.get("vo", {})
    for k in ("model_asset", "voices_asset", "asset"):
        if vo.get(k):
            ids.append(vo[k])
    for name, e in (spec.raw.get("sfx", {}).get("library") or {}).items():
        if e.get("asset"):
            ids.append(e["asset"])
    return ids


def validate(spec, manifest=None):
    """Return a list of problem strings (empty = OK)."""
    problems = []
    try:
        manifest = manifest or load_manifest(spec)
    except AssetError as e:
        return [str(e)]
    for aid, a in manifest.items():
        kind = a.get("kind")
        if kind not in KINDS:
            problems.append(f"{aid}: kind must be one of {sorted(KINDS)} (got {kind!r})")
        if not a.get("path"):
            problems.append(f"{aid}: missing path")
        if not str(a.get("licence") or "").strip():
            problems.append(f"{aid}: missing licence")
        if kind in GATED and not str(a.get("source_url") or "").strip():
            problems.append(f"{aid}: missing source_url (required for {kind})")
    for rid in referenced_ids(spec):
        if rid not in manifest:
            problems.append(f"{rid}: referenced by the spec but not in the assets manifest")
    return problems


def drafts(manifest):
    """Ids whose licence entry is still `status: draft` (terms pending confirmation)."""
    return [aid for aid, a in manifest.items() if str(a.get("status") or "").lower() == "draft"]


def asset_path(spec, aid, manifest=None):
    manifest = manifest or load_manifest(spec)
    if aid not in manifest:
        raise AssetError(f"asset {aid!r} not in manifest")
    return manifest[aid]["abs_path"]


def gate(spec):
    """Raise AssetError listing every problem (used by build/mix/check)."""
    problems = validate(spec)
    if problems:
        raise AssetError("assets gate failed:\n  - " + "\n  - ".join(problems))
    return load_manifest(spec)


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def rows(spec):
    """Per-asset records for `promo assets` (status: ok | generated | missing)."""
    out = []
    for aid, a in load_manifest(spec).items():
        p = a["abs_path"]
        status = "ok" if p and os.path.exists(p) else ("generated" if a.get("kind") in GENERATED else "missing")
        out.append(dict(id=aid, kind=a.get("kind"), status=status, licence=a.get("licence"), source_url=a.get("source_url"),
                        path=os.path.relpath(p, spec.root) if p else None, redistributable=a.get("redistributable"), sha256=a.get("sha256")))
    return out


def table(spec):
    rows_ = [("id", "kind", "status", "licence", "path")]
    for r in rows(spec):
        rows_.append((r["id"], r["kind"] or "?", r["status"], str(r["licence"] or "")[:38], r["path"] or ""))
    w = [max(len(r[i]) for r in rows_) for i in range(5)]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(r)) for r in rows_)


def fetch(spec, force=False):
    """Download assets with fetch_url that are missing locally; verify sha256 when given. Returns list of (id, action)."""
    manifest = load_manifest(spec)
    res = []
    for aid, a in manifest.items():
        p, url = a["abs_path"], a.get("fetch_url")
        if a.get("kind") in GENERATED:
            res.append((aid, "generated (run `promo sfx`)"))
            continue
        if p and os.path.exists(p) and not force:
            res.append((aid, "present"))
            continue
        if not url:
            res.append((aid, "missing, no fetch_url"))
            continue
        os.makedirs(os.path.dirname(p), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "promo-reel/0.1 (+https://github.com/patrick-lai/promo-reel)"})
        tmp = p + ".part"
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:   # urllib follows redirects
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
        want = a.get("sha256")
        if want and sha256_file(tmp) != want:
            os.remove(tmp)
            raise AssetError(f"{aid}: sha256 mismatch for {url}")
        os.replace(tmp, p)
        res.append((aid, "downloaded"))
    return res
