"""Dev server for the mod harness (stdlib only):  .venv/bin/python mod-dev/serve.py [--port 8765] [--keep DIR]  then open the printed URL.

  /mods/<...>          repo files under mods/
  /api/stages          [{id, title, status, badge}] canned states built by fixtures.py through the real `promo flow snapshot`
  /api/state/<id>      {version, summary, state}: `$file` objects already resolved to `$media` like the daemon does
  /media/<upload_id>   the file, with Range support
  --project DIR        serve a REAL project as stage `live`: every request re-reads `promo flow snapshot`, and POST /api/action runs the real
                       `promo flow` command behind the click (approve / pick / generate = `promo flow make`), so the whole flow can be driven by hand.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODS = os.path.join(ROOT, "mods")
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import fixtures  # noqa: E402
from promo import flow  # noqa: E402

MAX_FILE = {"image": 12 << 20, "audio": 100 << 20, "video": 100 << 20}
UPLOADS: dict[str, str] = {}
STAGES: dict[str, dict] = {}
LIVE: dict[str, object] = {"project": None, "jobs": []}
BY = "Sam"


def resolve(x):
    """Replace {"$file": path} with {"$media": {upload_id, name, mime, size}} (or {"$media": null, "$error"}) like the daemon's publish does."""
    if isinstance(x, list):
        return [resolve(v) for v in x]
    if not isinstance(x, dict):
        return x
    if set(x) == {"$file"}:
        p = x["$file"]
        if not os.path.isfile(p):
            return {"$media": None, "$error": "file not found: " + os.path.basename(p)}
        mime = mimetypes.guess_type(p)[0] or "application/octet-stream"
        size = os.path.getsize(p)
        if size > MAX_FILE.get(mime.split("/")[0], 12 << 20):
            return {"$media": None, "$error": f"{os.path.basename(p)} is too large ({size >> 20} MB)"}
        uid = hashlib.sha256((p + str(size)).encode()).hexdigest()[:24]
        UPLOADS[uid] = p
        return {"$media": {"upload_id": uid, "name": os.path.basename(p), "mime": mime, "size": size}}
    return {k: resolve(v) for k, v in x.items()}


def doc(name):
    if name == "live":
        STAGES["live"] = flow.snapshot(LIVE["project"])
    st = STAGES[name]
    if name == "starting":
        return {"summary": {"title": "Promo flow", "status": "Starting", "badge": "working"}, "state": {}}
    r = resolve(st)
    return {"summary": r["summary"], "state": r}


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "mod-dev"

    def log_message(self, fmt, *a):
        if os.environ.get("MOD_DEV_VERBOSE"):
            super().log_message(fmt, *a)

    def send(self, code, body=b"", ctype="text/plain; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj):
        self.send(200, json.dumps(obj).encode(), "application/json")

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/action" or not LIVE["project"]:
            return self.send(404, b"not found")
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        try:
            self.json(run_action(LIVE["project"], body.get("name"), body.get("payload") or {}))
        except flow.FlowError as e:
            self.json({"ok": False, "error": str(e)})

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                return self.send(302, b"", extra={"Location": "/dev/harness.html"})
            if path == "/api/stages":
                out = []
                for k, v in STAGES.items():
                    sm = (v.get("summary") if v else None) or {"title": "Promo flow", "status": "Starting", "badge": "working"}
                    out.append(dict(id=k, title=sm["title"], status=sm["status"], badge=sm["badge"], live=k == "live"))
                return self.json(out)
            m = re.fullmatch(r"/api/state/([\w-]+)", path)
            if m:
                if m.group(1) not in STAGES:
                    return self.send(404, b"no such stage")
                return self.json(doc(m.group(1)))
            m = re.fullmatch(r"/media/(\w+)", path)
            if m:
                return self.media(UPLOADS.get(m.group(1)))
            if path.startswith("/mods/"):
                return self.static(path[len("/mods/"):])
            if path.startswith("/dev/"):
                return self.static(path[len("/dev/"):], HERE)
            return self.send(404, b"not found")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def static(self, rel, base=None):
        base = base or MODS
        full = os.path.realpath(os.path.join(base, rel))
        if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full):
            return self.send(404, b"not found")
        ctype = {".js": "text/javascript", ".css": "text/css", ".html": "text/html", ".json": "application/json", ".svg": "image/svg+xml"}.get(os.path.splitext(full)[1], mimetypes.guess_type(full)[0] or "application/octet-stream")
        extra = {"X-Content-Type-Options": "nosniff"}
        return self.send(200, open(full, "rb").read(), ctype + ("; charset=utf-8" if ctype.startswith("text/") else ""), extra)

    def media(self, p):
        if not p or not os.path.isfile(p):
            return self.send(404, b"no such upload")
        size = os.path.getsize(p)
        ctype = mimetypes.guess_type(p)[0] or "application/octet-stream"
        a, b, code = 0, size - 1, 200
        rg = self.headers.get("Range")
        if rg and (m := re.fullmatch(r"bytes=(\d*)-(\d*)", rg.strip())):
            if m.group(1):
                a = int(m.group(1))
                b = int(m.group(2)) if m.group(2) else size - 1
            elif m.group(2):
                a = max(0, size - int(m.group(2)))
            b = min(b, size - 1)
            if a > b:
                return self.send(416, b"", extra={"Content-Range": f"bytes */{size}"})
            code = 206
        with open(p, "rb") as f:
            f.seek(a)
            body = f.read(b - a + 1)
        extra = {"Accept-Ranges": "bytes"}
        if code == 206:
            extra["Content-Range"] = f"bytes {a}-{b}/{size}"
        return self.send(code, body, ctype, extra)


def run_action(pd, name, payload):
    """What the agent does when the person clicks, so the harness drives the real flow instead of a canned one."""
    if name == "approve":
        flow.approve(pd, payload["gate"], BY)
        flow.advance(pd)
    elif name == "pick":
        flow.approve(pd, "scripts-picked", BY, payload["picks"].split())
        flow.advance(pd)
    elif name == "generate":
        job = subprocess.Popen([sys.executable, "-m", "promo", "flow", "--project", pd, "make"], cwd=ROOT, env={**os.environ, "PYTHONPATH": ROOT},
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        LIVE["jobs"].append(job)
        return {"ok": True, "message": "making frames and samples (promo flow make)", "pending": False}
    elif name == "share":
        return {"ok": True, "message": f"upload {payload['item']} to {payload['dest_label']}: `promo flow share {payload['kind']} {payload['n']} --to {payload['dest']} --by NAME` is the agent's to run", "pending": True}
    elif name == "density":
        args = ["--clear"] if not payload.get("every") else ["--every", str(payload["every"])]
        rc = flow.main(["--project", pd, "density", "--story", payload["story"], *args])
        return {"ok": rc == 0, "error": "density failed (see the harness console)", "message": f"promo flow density {' '.join(args)} (the agent then draws the frames)", "pending": True}
    else:
        return {"ok": True, "message": f"{name} is a message to the agent; nothing to run here", "pending": True}
    return {"ok": True, "pending": False}


def start(port=0, keep=None, project=None):
    """Build the fixtures and serve; returns (server, thread, url). With `project`, a real flow project is served as stage `live`."""
    states, tmp = fixtures.build(keep)
    STAGES.clear()
    STAGES.update(states)
    if project:
        LIVE["project"] = os.path.abspath(project)
        STAGES["live"] = flow.snapshot(LIVE["project"])
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv, t, f"http://127.0.0.1:{srv.server_address[1]}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--keep", help="build the fixture project in this dir and keep it")
    ap.add_argument("--project", help="a real `promo flow` project dir, served as stage `live` (default stage then)")
    a = ap.parse_args()
    srv, t, url = start(a.port, a.keep, a.project)
    print(f"mod harness: {url}/dev/harness.html{'?stage=live' if a.project else ''}   (Ctrl-C to stop)")
    try:
        t.join()
    except KeyboardInterrupt:
        srv.shutdown()


if __name__ == "__main__":
    main()
