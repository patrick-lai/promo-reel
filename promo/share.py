"""Put a draft or the final on the person's own Atlassian Artifacts or Loom through the `twg` CLI, when it is signed in and the product is there.

Every item has one canonical name, so an upload can be found again and refreshed instead of duplicated:

    draft N  ->  <project>_draft_<N>     edited and shared again it is still draft N: Artifacts replaces the file behind the same link;
                                         Loom has no replace, so the new video takes the title and the older links are kept in `previous`
    final N  ->  <project>_final_v<N>    every `promo flow final add` is the next revision, and a revision is never overwritten

The person starts every upload (`promo flow share ... --by NAME`, an agent name is refused: AGENTS.md rule 5) and access stays private
unless they ask for more. State lives in the flow's `shares` and `share` keys; `promo/flow.py` owns the CLI and the mod snapshot.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import mimetypes
import os
import re
import shutil
import subprocess

DESTS = ("artifacts", "loom")
LABEL = dict(artifacts="Atlassian Artifacts", loom="Loom")
NOTE = dict(artifacts="Private to you until you share the link.", loom="Goes to your Loom library.")
ACCESS = ("private", "open", "shared")
FRESH_S = 3600
PROBE_TIMEOUT_S = 60
UPLOAD_TIMEOUT_S = 3600
DESC_MAX = 400
# One cheap read per product: it succeeds only for a signed-in user whose site has that product.
PROBE = dict(artifacts=["artifacts", "file", "list", "--limit", "1"], loom=["loom", "space", "query"])
LOOM_URL = re.compile(r"https://[\w.-]*loom\.com/share/([A-Za-z0-9]+)")


class ShareError(Exception):
    pass


def twg_bin():
    """The twg executable: `PROMO_TWG` when set (a path that does not exist means "not installed"), else PATH, else ~/.local/bin."""
    env = os.environ.get("PROMO_TWG")
    cands = [env] if env is not None else [shutil.which("twg"), os.path.expanduser("~/.local/bin/twg")]
    return next((c for c in cands if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def _twg(args, timeout):
    exe = twg_bin()
    if not exe:
        raise ShareError("the `twg` CLI is not installed, so there is nowhere to upload to")
    try:
        return subprocess.run([exe, "-o", "json", "--output-summary", "none", *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise ShareError(f"twg gave no answer within {timeout} s")


def _why(r):
    """One plain reason from a failed twg run (its own summary or message), never the raw output."""
    if r.returncode == 77:
        return "not signed in to twg: run `twg login --force`"
    text = f"{r.stdout}\n{r.stderr}"
    for key in ("summary", "message"):
        m = re.search(rf'"?{key}"?:\s*"([^"]+)"', text)
        if m:
            return re.sub(r"^\w*Exception:\s*", "", m.group(1))
    return f"twg exited with code {r.returncode}"


def probe():
    """{dest: {ok, why}} for every destination."""
    out = {}
    for dest, args in PROBE.items():
        try:
            r = _twg(args, PROBE_TIMEOUT_S)
            out[dest] = dict(ok=r.returncode == 0, why="" if r.returncode == 0 else _why(r))
        except ShareError as e:
            out[dest] = dict(ok=False, why=str(e))
    return out


def refresh(st, at, force=False):
    """Probe the destinations unless a probe from the last hour is on file; True when it probed (the caller saves the flow)."""
    have = (st.get("share") or {}).get("detected")
    if have and not force:
        age = datetime.datetime.now().astimezone() - datetime.datetime.fromisoformat(have["at"])
        if age.total_seconds() < FRESH_S:
            return False
    st["share"] = dict(detected=dict(at=at, dests=probe()))
    return True


def detected(st):
    return ((st.get("share") or {}).get("detected") or {}).get("dests") or {}


def available(st):
    return [d for d in DESTS if detected(st).get(d, {}).get("ok")]


def canonical(project, kind, n):
    base = re.sub(r"[^\w.-]+", "-", os.path.basename(os.path.normpath(project))).strip("-") or "promo"
    return f"{base}_draft_{n}" if kind == "draft" else f"{base}_final_v{n}"


def file_sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def view(st, project, kind, n, path):
    """What the mod shows for one draft or final: the name it uploads as, and where it already is (`edited` = the file changed since)."""
    recs = (st.get("shares") or {}).get(f"{kind}-{n}") or {}
    now_sha = file_sha(path) if recs and os.path.isfile(path) else None
    return dict(share_as=canonical(project, kind, n),
                shared={d: dict(url=r.get("url") or None, name=r["name"], at=r["at"], edited=now_sha is not None and now_sha != r["sha"]) for d, r in recs.items()})


def _json_data(r, what):
    if r.returncode != 0:
        raise ShareError(f"{what} failed: {_why(r)}")
    try:
        return json.loads(r.stdout).get("data")
    except (ValueError, AttributeError):
        raise ShareError(f"{what}: twg answered with something unreadable. Check {LABEL['artifacts']} before uploading again")


def _with_id(o):
    """The first object carrying a string `id`, wherever twg nests it (`data` itself or `data.artifact`)."""
    if isinstance(o, dict):
        if isinstance(o.get("id"), str):
            return o
        o = list(o.values())
    if isinstance(o, list):
        for v in o:
            if (found := _with_id(v)):
                return found
    return None


def _artifact(r, what):
    a = _with_id(_json_data(r, what))
    if not a:
        raise ShareError(f"{what}: twg returned no artifact id. Check {LABEL['artifacts']} before uploading again")
    return dict(id=a["id"], url=a.get("artifactUrl") or "")


def _artifacts_put(path, name, description, access, old, with_file):
    ext = os.path.splitext(path)[1]
    if old:
        cmd = ["artifacts", "file", "update", old["id"], *([path] if with_file else [])]
    else:
        cmd = ["artifacts", "file", "create", path]
    cmd += ["--name", name + ext, "--description", description]
    mime = mimetypes.guess_type(path)[0]
    if mime and with_file:
        cmd += ["--type", mime]
    if access or not old:
        cmd += ["--access", access or "private"]
    got = _artifact(_twg(cmd, UPLOAD_TIMEOUT_S), "Artifacts update" if old else "Artifacts upload")
    return dict(id=got["id"], url=got["url"] or (old or {}).get("url", ""), access=access or (old or {}).get("access", "private"))


def _loom_put(path, name):
    r = _twg(["loom", "video", "upload", path, "--title", name], UPLOAD_TIMEOUT_S)
    if r.returncode != 0:
        raise ShareError(f"Loom upload failed: {_why(r)}")
    m = LOOM_URL.search(r.stdout)
    if not m:
        raise ShareError("Loom upload: twg returned no share link. Check your Loom library before uploading again")
    return dict(id=m.group(1), url=m.group(0))


def describe(kind, n, project, intent, note):
    """The search description: what the file is, from the flow's own record (the person's request and the draft's note), not its file name."""
    what = f"Draft {n}" if kind == "draft" else f"Final {n} (revision v{n})"
    first = (intent.split(".")[0] or intent).strip()
    text = f"{what} of the promo video {project}. Asked for: {first}." + (f" {note}" if note else "")
    return text if len(text) <= DESC_MAX else text[:DESC_MAX - 1].rstrip() + "…"


def upload(st, project, kind, n, path, dest, access, description, at):
    """Upload (or refresh) one item to one destination and record it in st["shares"]. Returns (record, what): created | updated | unchanged."""
    if dest not in DESTS:
        raise ShareError(f"destination must be one of {', '.join(DESTS)}")
    if access is not None and (access not in ACCESS or dest != "artifacts"):
        raise ShareError("--access applies to Artifacts only, and is one of " + ", ".join(ACCESS))
    if not os.path.isfile(path):
        raise ShareError(f"the file of this {kind} is missing: {os.path.basename(path)}")
    name = canonical(project, kind, n)
    sha = file_sha(path)
    slot = st.setdefault("shares", {}).setdefault(f"{kind}-{n}", {})
    old = slot.get(dest)
    same = bool(old) and old["sha"] == sha
    if same and not (access and access != old.get("access")):
        return old, "unchanged"
    if old and not same and kind == "final":
        raise ShareError(f"Final {n} changed after it went to {LABEL[dest]} as {old['name']}. Register the new file with `promo flow final add` and it goes up as the next version.")
    if dest == "artifacts":
        rec = _artifacts_put(path, name, description, access, old, with_file=not same)
    else:
        rec = _loom_put(path, name)
        if old:
            rec["previous"] = [*old.get("previous", []), old["url"]]
    rec.update(name=name, sha=sha, at=at)
    slot[dest] = rec
    return rec, "updated" if old else "created"
