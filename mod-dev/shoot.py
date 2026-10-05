"""Screenshots of the mod through the harness with headless Chrome driven over the DevTools protocol (stdlib only).

    .venv/bin/python mod-dev/shoot.py [--out /tmp/promo-flow-shots/v1] [--only storyboard,review] [--no-extras]
    .venv/bin/python mod-dev/shoot.py --base http://127.0.0.1:PORT --tabs storyboard,assets [--w 520] [--scroll 0,600] [--out DIR]   # a running `serve.py --project` (stage live)

Every stage x {dark, light} at pane width 520 and 900, plus 380, then a few interaction shots (lightbox, note box, picks, offline, readonly, ...).
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import serve  # noqa: E402

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
STAGES = ["discover", "scripts", "pick", "storyboard", "assets", "keyframes", "confirm", "drafts", "review", "final"]
WIDTHS = [(380, 780), (520, 900), (900, 900)]


class WS:
    def __init__(self, url):
        host, port, path = url[5:].split("/", 1)[0].rsplit(":", 1)[0], int(url[5:].split("/", 1)[0].rsplit(":", 1)[1]), "/" + url[5:].split("/", 1)[1]
        self.s = socket.create_connection((host, port))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall(f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.s.recv(1)
        self.n = 0
        self.events = []

    def _send(self, data: bytes):
        hdr = bytearray([0x81])
        ln = len(data)
        if ln < 126:
            hdr.append(0x80 | ln)
        elif ln < 65536:
            hdr += bytes([0x80 | 126]) + struct.pack(">H", ln)
        else:
            hdr += bytes([0x80 | 127]) + struct.pack(">Q", ln)
        mask = os.urandom(4)
        self.s.sendall(bytes(hdr) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv_n(self, n):
        out = b""
        while len(out) < n:
            c = self.s.recv(n - len(out))
            if not c:
                raise EOFError
            out += c
        return out

    def _recv(self):
        msg = b""
        while True:
            b1, b2 = self._recv_n(2)
            ln = b2 & 0x7F
            if ln == 126:
                ln = struct.unpack(">H", self._recv_n(2))[0]
            elif ln == 127:
                ln = struct.unpack(">Q", self._recv_n(8))[0]
            msg += self._recv_n(ln)
            if b1 & 0x80:
                return json.loads(msg)

    def call(self, method, session=None, **params):
        self.n += 1
        i = self.n
        msg = dict(id=i, method=method, params=params)
        if session:
            msg["sessionId"] = session
        self._send(json.dumps(msg).encode())
        while True:
            m = self._recv()
            if m.get("id") == i:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m["result"]
            self.events.append(m)

    def pump(self, secs=0.0):
        self.s.settimeout(max(secs, 0.01))
        try:
            while True:
                self.events.append(self._recv())
        except (socket.timeout, TimeoutError):
            pass
        finally:
            self.s.settimeout(None)


class Shooter:
    def __init__(self, base):
        self.base = base
        self.tmp = tempfile.mkdtemp(prefix="chrome-shoot-")
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9339", f"--user-data-dir={self.tmp}", "--hide-scrollbars", "--no-first-run",
                                      "--disable-gpu", "--mute-audio", "--autoplay-policy=no-user-gesture-required", "--window-size=1200,1000", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9339/json/list"))
                break
            except Exception:  # noqa: BLE001
                time.sleep(0.25)
        page = [t for t in tabs if t["type"] == "page"][0]
        self.ws = WS(page["webSocketDebuggerUrl"])
        self.ws.call("Page.enable")
        self.ws.call("Target.setAutoAttach", autoAttach=True, waitForDebuggerOnStart=False, flatten=True)

    def iframe_session(self):
        """The sandboxed mod frame lives in its own process (opaque origin), so it arrives as an auto-attached iframe target."""
        sess = None
        for e in self.ws.events:
            m = e.get("method")
            if m == "Target.attachedToTarget" and e["params"]["targetInfo"]["type"] == "iframe":
                sess = e["params"]["sessionId"]
            elif m == "Target.detachedFromTarget" and e["params"]["sessionId"] == sess:
                sess = None
        return sess

    def js(self, expr, sess=None):
        r = self.ws.call("Runtime.evaluate", session=sess, expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r["result"].get("value")

    def open(self, stage, w, h, dark, extra=""):
        self.ws.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1.5, mobile=False)
        self.ws.events.clear()
        self.ws.call("Page.navigate", url=f"{self.base}/dev/harness.html?bare=1&stage={stage}&dark={1 if dark else 0}{extra}")
        t0 = time.time()
        cid = None
        while time.time() - t0 < 12:
            self.ws.pump(0.2)
            cid = self.iframe_session()
            if cid:
                try:
                    if self.js("document.getElementById('app').dataset.boot === 'ready' && !document.querySelector('.content .sk:not(.skbar)') && !document.querySelector('.content [aria-busy]')", cid):
                        break
                except RuntimeError:
                    pass
            cid = None
        if not cid:
            raise RuntimeError(f"mod did not settle for {stage} {w}")
        time.sleep(0.45)
        return cid

    def shot(self, path):
        r = self.ws.call("Page.captureScreenshot", format="png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))

    def close(self):
        try:
            self.ws.call("Browser.close")
        except Exception:  # noqa: BLE001
            pass
        self.proc.terminate()
        shutil.rmtree(self.tmp, ignore_errors=True)


SELFCHECK = """(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = [];
  const tab = document.getElementById('tab-assets');
  if (!tab) return out;
  tab.click(); await wait(300);
  const stories = [...document.querySelectorAll('button[data-k^="story-"]')];
  for (let i = 0; i < Math.max(1, stories.length); i++) {
    if (stories[i]) { document.querySelector('[data-k="' + stories[i].dataset.k + '"]').click(); await wait(300); }
    const badge = +document.querySelector('.tab[data-tab=assets] .n').textContent;
    const c = document.querySelector('.counter');
    const sum = [...c.querySelectorAll('button b')].reduce((a, b) => a + +b.textContent, 0);
    const cards = document.querySelector('.gallery').children.length;
    const sb = document.querySelector('.tab[data-tab=storyboard] .n');
    out.push({ story: stories[i] ? stories[i].dataset.k : '-', badge, total: +c.dataset.total, sum, cards, sbBadge: sb ? +sb.textContent : null });
  }
  return out;
})()"""


SCENECHECK = """(async () => {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const tab = document.getElementById('tab-storyboard');
  if (!tab) return [];
  tab.click(); await wait(300);
  const map = { 'Captured': 'k-real', 'Captured stills': 'k-stills', 'Mock in plan': 'k-mock', 'To capture': 'k-todo', 'Generated plate': 'k-gen', 'Plate to generate': 'k-todo' };
  const out = [];
  for (const b of document.querySelectorAll('.tl button')) {
    const sc = document.querySelector('[data-sid="' + b.dataset.sid + '"].scene, details[data-sid="' + b.dataset.sid + '"]');
    const chip = sc && sc.querySelector('.chip');
    const text = chip ? chip.textContent : '';
    const cls = [...b.classList].find((c) => c.startsWith('k-'));
    const want = map[text];
    const ok = !want || cls === want || cls === 'k-todo';
    const green = cls === 'k-real' && text !== 'Captured';
    out.push({ sid: b.dataset.sid, text, cls, ok: ok && !green });
  }
  return out;
})()"""


def selfcheck(sh, base):
    bad = 0
    for st in ["assets", "keyframes", "confirm", "drafts", "review", "final", "assets-error", "stale-approval", "long-content", "storyboard-partial"]:
        cid = sh.open(st, 520, 900, False)
        for r in sh.js(SELFCHECK, cid) or []:
            ok = r["badge"] == r["total"] == r["sum"] == r["cards"]
            bad += not ok
            print(("ok   " if ok else "FAIL ") + st, r)
        for r in sh.js(SCENECHECK, cid) or []:
            bad += not r["ok"]
            if not r["ok"]:
                print("FAIL scene-status", st, r)
            if st == "assets":
                if r["sid"] == "03" and r["cls"] == "k-real":
                    bad += 1
                    print("FAIL scene 03 is covered by a mock asset but reads k-real", r)
                if r["sid"] in ("04", "08") and r["cls"] == "k-gen":
                    bad += 1
                    print("FAIL scene", r["sid"], "has an unmade or mock plate but reads k-gen", r)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/promo-flow-shots/v1")
    ap.add_argument("--only", default="")
    ap.add_argument("--no-extras", action="store_true")
    ap.add_argument("--files", default="", help="comma list of output names (without .png) to shoot, e.g. 07-confirm-520-dark,x-no-host-520")
    ap.add_argument("--base", help="URL of a running serve.py --project: shoot its live stage instead of the canned ones")
    ap.add_argument("--tabs", default="storyboard,assets")
    ap.add_argument("--scroll", default="0")
    ap.add_argument("--click", default="", help="with --base: CSS selectors to click (| separated) after the tab opens, e.g. '.warnline .load'")
    ap.add_argument("--w", type=int, default=520)
    ap.add_argument("--h", type=int, default=1100)
    ap.add_argument("--dark", action="store_true")
    a = ap.parse_args()
    if a.base:
        return live(a)
    only = [x for x in a.only.split(",") if x]
    files = [x for x in a.files.split(",") if x]
    if not files:
        shutil.rmtree(a.out, ignore_errors=True)
    os.makedirs(a.out, exist_ok=True)
    srv, _, base = serve.start(0)
    sh = Shooter(base)
    made = []
    try:
        if os.environ.get("SELFCHECK", "1") == "1":
            print("count self-check failures:", selfcheck(sh, base))
        for st in STAGES:
            if only and st not in only:
                continue
            for w, h in WIDTHS:
                for dark in (True, False):
                    nm = f"{STAGES.index(st) + 1:02d}-{st}-{w}-{'dark' if dark else 'light'}"
                    if files and nm not in files:
                        continue
                    sh.open(st, w, h, dark)
                    p = os.path.join(a.out, nm + ".png")
                    sh.shot(p)
                    made.append(p)
        if not a.no_extras:
            for name, stage, w, h, dark, extra, script in EXTRAS:
                if only and name not in only:
                    continue
                if files and "x-" + name not in files:
                    continue
                cid = sh.open(stage, w, h, dark, extra)
                if script:
                    for s in script if isinstance(script, list) else [script]:
                        if s.startswith("TOP:"):
                            sh.js(s[4:])
                        else:
                            sh.js(s, cid)
                        time.sleep(0.5)
                p = os.path.join(a.out, f"x-{name}.png")
                sh.shot(p)
                made.append(p)
    finally:
        sh.close()
        srv.shutdown()
    print("\n".join(sorted(os.path.basename(p) for p in made)))
    print(f"{len(made)} screenshots in {a.out}")


SETTLED = "!document.querySelector('.content .sk:not(.skbar)') && !document.querySelector('.content [aria-busy]')"


def live(a):
    """Screenshots of a running `serve.py --project` server: each tab at one pane width, optionally scrolled (each scroll offset is its own shot)."""
    os.makedirs(a.out, exist_ok=True)
    sh = Shooter(a.base)
    made = []
    try:
        for tab in a.tabs.split(","):
            for sc in [int(x) for x in a.scroll.split(",")]:
                cid = sh.open("live", a.w, a.h, a.dark)
                sh.js(click("#tab-" + tab), cid)
                for sel in [x for x in a.click.split("|") if x]:
                    time.sleep(0.5)
                    sh.js(click(sel), cid)
                sh.js(scroll(sc), cid)
                for _ in range(40):
                    time.sleep(0.5)
                    if sh.js(SETTLED, cid):
                        break
                time.sleep(0.5)
                p = os.path.join(a.out, f"live-{tab}-{a.w}{'-s' + str(sc) if sc else ''}.png")
                sh.shot(p)
                made.append(p)
    finally:
        sh.close()
    print("\n".join(made))


CLICK = "(sel) => { const e = document.querySelector(sel); if (!e) throw new Error('no ' + sel); e.click(); }"


def click(sel):
    return f"({CLICK})({json.dumps(sel)})"


def scroll(px):
    return f"document.getElementById('scroller').scrollTop = {px}"


EXTRAS = [
    ("lightbox-520", "storyboard", 520, 900, True, "", [click(".scene .fr"), click(".lb .nav.next")]),
    ("lightbox-900-light", "storyboard", 900, 900, False, "", [click(".scene:nth-child(2) .fr:last-of-type")]),
    ("lightbox-380", "storyboard", 380, 780, True, "", [click(".scene .fr")]),
    ("compose-draft-520", "review", 520, 900, False, "", [click("#btnSecondary")]),
    ("compose-storyboard-380", "storyboard", 380, 780, True, "", [click("#btnSecondary"), "(() => { const t = document.getElementById('note'); t.value = 'Scene 04 needs a slower fade, and make the end frame of 06 brighter.'; t.dispatchEvent(new Event('input')); })()"]),
    ("picks-520", "pick", 520, 900, False, "", ["document.querySelector('.choice input').click()"]),
    ("style-pick-520", "discover", 520, 900, True, "", ["document.querySelector('.choice input').click()"]),
    ("storyboard-scrolled-520", "storyboard", 520, 900, False, "", [scroll(900)]),
    ("storyboard-scrolled-900", "storyboard", 900, 900, True, "", [scroll(700)]),
    ("storyboard-b-520", "storyboard", 520, 900, True, "", ["document.querySelectorAll('.seg-ctl button')[1].click()"]),
    ("storyboard-partial-520", "storyboard-partial", 520, 900, False, "", []),
    ("assets-scrolled-520", "assets", 520, 900, True, "", [scroll(520)]),
    ("assets-scrolled-900", "assets", 900, 900, False, "", [scroll(420)]),
    ("assets-error-520", "assets-error", 520, 900, True, "", []),
    ("draft-scrolled-520", "review", 520, 900, True, "", [scroll(700)]),
    ("draft-scrolled-900", "review", 900, 900, False, "", [scroll(500)]),
    ("review-maxed-520", "review-maxed", 520, 900, False, "", []),
    ("long-content-520", "long-content", 520, 900, False, "", [scroll(420)]),
    ("long-assets-380", "long-content", 380, 780, True, "", [click("#tab-assets")]),
    ("long-scripts-520", "long-content", 520, 900, True, "", [click("#tab-scripts")]),
    ("starting-520", "starting", 520, 900, False, "", []),
    ("starting-380-dark", "starting", 380, 780, True, "", []),
    ("review-viewing-older-520", "review", 520, 900, True, "", [click("[data-k=dr-d0]")]),
    ("gate-on-other-tab-520", "assets", 520, 900, True, "", [click("#tab-storyboard")]),
    ("keyframes-380", "keyframes", 380, 780, False, "", []),
    ("gate-story-b-380", "assets", 380, 780, True, "", []),
    ("no-host-520", "pick", 520, 900, False, "&hold=1", []),
    ("offline-520", "storyboard", 520, 900, False, "&offline=1", []),
    ("readonly-520", "review", 520, 900, True, "&readonly=1", []),
    ("stale-approval-520", "stale-approval", 520, 900, False, "", []),
    ("stale-approval-380", "stale-approval", 380, 780, True, "", []),
    ("confirm-scene-open-520", "confirm", 520, 900, True, "", [click(".scene-d summary")]),
    ("assets-filter-todo-520", "keyframes", 520, 900, False, "", [click("#tab-assets"), click(".counter button:nth-of-type(3)")]),
    ("picks-cleared-380", "pick", 380, 780, True, "", ["document.querySelector('.choice input').click()", "TOP:window.harness.setStage('storyboard')"]),
    ("steps-open-380", "storyboard", 380, 780, False, "", [click("#stepsBtn")]),
    ("scripts-after-pick-520", "storyboard", 520, 900, False, "", [click("#tab-scripts")]),
]

if __name__ == "__main__":
    main()
