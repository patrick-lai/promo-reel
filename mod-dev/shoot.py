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

    def js(self, expr, mod=False):
        """mod=True runs expr against the mod's shadow root: `document` in it is that root (getElementById and querySelector work the same)."""
        if mod:
            expr = f"(function (document) {{ return ({expr}); }})(window.harness.root)"
        r = self.ws.call("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "js error"))
        return r["result"].get("value")

    def open(self, stage, w, h, dark, extra=""):
        self.ws.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1.5, mobile=False)
        self.ws.events.clear()
        self.js("window.harness = null")  # so the wait below cannot see the previous page's mod
        self.ws.call("Page.navigate", url=f"{self.base}/dev/harness.html?bare=1&stage={stage}&dark={1 if dark else 0}{extra}")
        t0 = time.time()
        mod = False
        while time.time() - t0 < 12:
            self.ws.pump(0.2)
            try:
                if self.js("!!(window.harness && window.harness.root)") and self.js("document.getElementById('app').dataset.boot === 'ready' && !document.querySelector('.content .sk:not(.skbar)') && !document.querySelector('.content [aria-busy]')", True):
                    mod = True
                    break
            except RuntimeError:
                pass
        if not mod:
            raise RuntimeError(f"mod did not settle for {stage} {w}")
        time.sleep(0.45)
        return mod

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
    const cards = [...document.querySelectorAll('.gallery')].reduce((n, g) => n + g.children.length, 0);
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
        mod = sh.open(st, 520, 900, False)
        for r in sh.js(SELFCHECK, mod) or []:
            ok = r["badge"] == r["total"] == r["sum"] == r["cards"]
            bad += not ok
            print(("ok   " if ok else "FAIL ") + st, r)
        for r in sh.js(SCENECHECK, mod) or []:
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


UICHECK = r"""(async () => {
  const root = window.harness.root, wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const Q = (x) => root.querySelector(x), QA = (x) => [...root.querySelectorAll(x)];
  const click = async (x) => { const e = Q(x); if (!e) throw new Error('no ' + x); e.click(); await wait(350); };
  const until = async (f, ms = 6000) => { const t = Date.now(); while (Date.now() - t < ms) { if (f()) return true; await wait(80); } return false; };
  const out = [], ok = (name, pass, info) => out.push({ name, pass: !!pass, info: info === undefined ? '' : String(info) });
  const log = () => window.document.getElementById('log').innerText;
  const step = window.harness.H.stage;
  if (step === 'plan') {
    await click('#tab-plan');
    const cards = QA('.doc-card').length, chip = +Q('[data-k=g-all] .n').textContent;
    ok('plan lists every script and document', cards === chip && cards === 20, cards + ' cards, chip ' + chip);
    ok('tab badge counts the documents', +Q('.tab[data-tab=plan] .n').textContent === 17);
    await click('[data-k=g-Script]');
    ok('group filter narrows the list', QA('.doc-card').length === 6, QA('.doc-card').length);
    await click('[data-k=g-all]');
    await click('[data-k="open-doc:full-script-a"]');
    ok('reader loads a 12 000 word script', await until(() => Q('.doc-page .md-h')));
    const n = +(Q('.pg-l').textContent.match(/of (\d+)/) || [0, 0])[1];
    ok('it is paginated', n >= 12, n + ' pages');
    ok('page 1 shows its first heading', /Full script/.test(Q('.doc-page').textContent));
    await click('[data-k=pg-next-bot]');
    ok('next page', /Page 2 of/.test(Q('.pg-l').textContent), Q('.pg-l').textContent);
    ok('focus moves to the page', root.activeElement === Q('.doc-page'));
    const toc = Q('[data-k=rd-toc]');
    toc.selectedIndex = toc.options.length - 1; toc.dispatchEvent(new Event('change')); await wait(300);
    const want = +toc.options[toc.options.length - 1].textContent.match(/p\.(\d+)$/)[1];
    ok('contents jumps to the chosen heading', new RegExp('Page ' + want + ' of ' + n).test(Q('.pg-l').textContent) && Q('[data-k=pg-prev-top]').disabled === false, Q('.pg-l').textContent + ' want p.' + want);
    await click('[data-k=pg-next-bot]'); await click('[data-k=pg-next-bot]'); await click('[data-k=pg-next-bot]');
    ok('the last page has no Next', Q('[data-k=pg-next-top]').disabled && Q('[data-k=pg-next-bot]').disabled && new RegExp('Page ' + n + ' of ' + n).test(Q('.pg-l').textContent), Q('.pg-l').textContent);
    const f = Q('[data-k=rd-find]'); f.value = 'blinds'; f.dispatchEvent(new Event('input')); await wait(500);
    ok('find counts matches over every page', /\d+ matches on \d+ pages/.test(Q('.rd-found').textContent), Q('.rd-found').textContent);
    ok('the match is highlighted', QA('.doc-page mark').length >= 1);
    await click('[aria-label="Next match"]');
    ok('next match moves between pages', QA('.doc-page mark').length >= 1);
    f.value = 'Picture'; f.dispatchEvent(new Event('input')); await wait(500);
    const marks = () => QA('.doc-page mark'), curIdx = () => marks().findIndex((m) => m.classList.contains('cur'));
    const pg0 = Q('.pg-l').textContent, i0 = curIdx();
    ok('find marks the current match', marks().length > 2 && i0 >= 0, marks().length + ' marks, cur ' + i0);
    await click('[aria-label="Next match"]');
    ok('next steps to the next match on the same page', Q('.pg-l').textContent === pg0 && curIdx() === i0 + 1, pg0 + ' -> ' + Q('.pg-l').textContent + ' cur ' + curIdx());
    await click('[aria-label="Previous match"]');
    ok('previous steps back', curIdx() === i0, curIdx());
    f.value = 'blinds'; f.dispatchEvent(new Event('input')); await wait(400);
    f.value = 'zzzzqq'; f.dispatchEvent(new Event('input')); await wait(400);
    ok('no match is said plainly', /No match/.test(Q('.rd-found').textContent));
    await click('[data-k=pg-next-bot]'); await click('[data-k=pg-next-bot]');
    const here = Q('.pg-l').textContent, y0 = document.getElementById('scroller').scrollTop = 5000;
    await wait(100);
    const y1 = document.getElementById('scroller').scrollTop;
    window.harness.setStage('dense'); await wait(900);
    ok('a step change keeps the reader on its page and place', Q('.reader') && Q('.pg-l').textContent === here && document.getElementById('scroller').scrollTop > 0.5 * y1, Q('.pg-l') && Q('.pg-l').textContent + ' vs ' + here + ' y ' + document.getElementById('scroller').scrollTop + ' vs ' + y1);
    window.harness.setStage('plan'); await wait(900);
    await click('[data-k=rd-back]');
    ok('back returns to the list with focus on the document', !!Q('.doc-card') && (root.activeElement || {}).dataset && root.activeElement.dataset.k === 'open-doc:full-script-a', (root.activeElement || {}).tagName);
    await click('[data-k="open-doc:research-notes"]');
    await until(() => Q('.doc-page'));
    ok('markup is text, never HTML', !Q('.doc-page img') && /onerror/.test(Q('.doc-page').textContent) && !QA('.doc-page a').length);
    ok('https links go through the host', QA('.doc-page .lnk').length >= 2 && !QA('.doc-page .lnk').some((b) => /^javascript/i.test(b.title)));
    QA('.doc-page .lnk')[0].click(); await wait(200);
    ok('link opens through open-url', /open-url https:\/\/www\.apple\.com/.test(log()));
    await click('[data-k=rd-back]');
    await click('[data-k="open-doc:capture-a"]'); await until(() => Q('.doc-page'));
    ok('checklists render as checkboxes', QA('.doc-page .md-box').length >= 2);
    await click('[data-k=rd-back]');
    await click('[data-k="open-doc:shotlist-a"]'); await until(() => Q('.doc-page'));
    ok('tables render with a scroll region', !!Q('.doc-page .md-tbl table') && QA('.doc-page th').length >= 8);
    await click('[data-k=rd-back]');
    await click('[data-k="q-Shot list"]');
    ok('a request opens the note box prefilled', !Q('#compose').hidden && /shot list/i.test(Q('#note').value) && Q('#btnPrimary').textContent === 'Send request', Q('#btnPrimary').textContent);
    Q('#note').value = 'Add a shot list for story B too, every shot numbered.'; Q('#note').dispatchEvent(new Event('input')); await wait(100);
    await click('#btnPrimary');
    await wait(500);
    ok('the request reaches the agent', /action request -> \[mod:promo-flow\] Sam asked you to add to the plan \(looking at the Plan tab\): Add a shot list for story B/.test(log()), log().slice(0, 400));
  }
  if (step === 'dense') {
    await click('[data-k=sbv-time]');
    const figs = QA('.tl-fig').length, badge = +Q('[data-k=sbv-time] .n').textContent;
    ok('frames in time shows every frame', figs === badge && figs === 28, figs + ' vs ' + badge);
    const times = QA('.tl-fig .lbl').map((e) => e.textContent);
    ok('they are in time order', times[0] === '0:00' && times.indexOf('0:05') > 0, times.slice(0, 6).join(' '));
    await click('[data-k=sbv-scenes]');
    ok('scenes view still there', QA('.scene').length === 8);
    ok('dense scene shows a film strip', !!Q('.frames.film') && QA('.frames.film .fr').length >= 3);
    ok('current cadence is pressed', Q('[data-k=dens-5]').getAttribute('aria-pressed') === 'true');
    await click('[data-k=dens-2]');
    await wait(500);
    ok('a new cadence is a message to the agent', /action density -> \[mod:promo-flow\] Sam wants storyboard frames every 2 seconds for story A\. Run: promo flow density --story A --every 2/.test(log()), log().slice(0, 300));
  }
  if (step === 'pick') {
    const badge = () => Q('#badgeText').textContent;
    ok('before sending, the pick gate is the person\'s turn', badge() === 'Your turn', badge());
    Q('.choice input').click(); await wait(200);
    await click('#btnPrimary');
    await until(() => /Sent/.test(Q('#gateNote').textContent));
    ok('after sending the picks the badge is not Your turn', badge() === 'With the agent', badge());
    ok('and the header line says it was sent', /Sent/.test(Q('#stateLine').textContent), Q('#stateLine').textContent);
  }
  return out;
})()"""


def uicheck(sh):
    bad = 0
    for st in ["plan", "dense", "pick"]:
        mod = sh.open(st, 520, 1000, False)
        for r in sh.js(UICHECK, mod) or []:
            bad += not r["pass"]
            print(("ok   " if r["pass"] else "FAIL ") + f"{st}: {r['name']}" + (f"  [{r['info']}]" if r["info"] and not r["pass"] else ""))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="run the interaction checks (plan reader, requests, density) and exit non-zero on a failure")
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
    if a.check:
        try:
            bad = uicheck(sh)
        finally:
            sh.close()
            srv.shutdown()
        print("interaction check failures:", bad)
        return 1 if bad else 0
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
                mod = sh.open(stage, w, h, dark, extra)
                if script:
                    for s in script if isinstance(script, list) else [script]:
                        if s.startswith("TOP:"):
                            sh.js(s[4:])
                        else:
                            sh.js(s, mod)
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
                mod = sh.open("live", a.w, a.h, a.dark)
                sh.js(click("#tab-" + tab), mod)
                for sel in [x for x in a.click.split("|") if x]:
                    time.sleep(0.5)
                    sh.js(click(sel), mod)
                sh.js(scroll(sc), mod)
                for _ in range(40):
                    time.sleep(0.5)
                    if sh.js(SETTLED, mod):
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


def typein(sel, text):
    return f"(() => {{ const e = document.querySelector({json.dumps(sel)}); if (!e) throw new Error('no {sel}'); e.value = {json.dumps(text)}; e.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()"


def scroll(px):
    return f"document.getElementById('scroller').scrollTop = {px}"


EXTRAS = [
    ("picker-520", "picker", 520, 900, True, "&mod=promo-projects", None),
    ("picker-900-light", "picker", 900, 900, False, "&mod=promo-projects", None),
    ("generating-520", "generating", 520, 900, True, "", None),
    ("generating-380-light", "generating", 380, 900, False, "", None),
    ("generating-stopped-520", "generating-stopped", 520, 900, True, "", None),
    ("building-520", "building", 520, 900, True, "", None),
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
    ("plan-520", "plan", 520, 900, False, "", [click("#tab-plan")]),
    ("plan-380-dark", "plan", 380, 780, True, "", [click("#tab-plan")]),
    ("plan-900", "plan", 900, 900, False, "", [click("#tab-plan")]),
    ("plan-empty-520", "scripts", 520, 900, True, "", [click("#tab-plan")]),
    ("plan-scrolled-520", "plan", 520, 900, True, "", [click("#tab-plan"), scroll(900)]),
    ("reader-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="open-doc:full-script-a"]')]),
    ("reader-380-dark", "plan", 380, 780, True, "", [click("#tab-plan"), click('[data-k="open-doc:full-script-a"]'), click('[data-k="pg-next-top"]')]),
    ("reader-table-520", "plan", 520, 900, True, "", [click("#tab-plan"), click('[data-k="open-doc:shotlist-a"]')]),
    ("reader-find-900", "plan", 900, 900, False, "", [click("#tab-plan"), click('[data-k="open-doc:full-script-a"]'), typein('[data-k="rd-find"]', "blinds")]),
    ("reader-checklist-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="open-doc:capture-a"]')]),
    ("request-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="q-Shot list"]')]),
    ("request-380-dark", "plan", 380, 780, True, "", [click("#tab-plan"), click('[data-k="q-Everything for production"]')]),
    ("script-read-520", "pick", 520, 900, False, "", []),
    ("script-reader-520", "scripts", 520, 900, True, "", [click('[data-k="open-script:A"]')]),
    ("dense-520", "dense", 520, 1100, False, "", []),
    ("dense-time-520", "dense", 520, 1100, False, "", [click('[data-k="sbv-time"]')]),
    ("dense-time-900", "dense", 900, 1000, True, "", [click('[data-k="sbv-time"]')]),
    ("dense-scene-380", "dense", 380, 900, True, "", [scroll(780)]),
    ("scripts-after-pick-520", "storyboard", 520, 900, False, "", [click("#tab-scripts")]),
]

if __name__ == "__main__":
    sys.exit(main() or 0)
