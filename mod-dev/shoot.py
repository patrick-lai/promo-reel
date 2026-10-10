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
STAGES = ["discover", "scripts", "pick", "storyboard", "assets", "keyframes", "confirm", "drafts", "review", "autopilot", "final", "edit"]
WIDTHS = [(380, 780), (520, 900), (900, 900), (1100, 900)]


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
        # a port of its own: other agents on the box run these checks too, and two runs on one port drive each other's browser
        with socket.socket() as sk:
            sk.bind(("127.0.0.1", 0))
            self.port = sk.getsockname()[1]
        self.proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={self.port}", f"--user-data-dir={self.tmp}", "--hide-scrollbars", "--no-first-run",
                                      "--disable-gpu", "--mute-audio", "--autoplay-policy=no-user-gesture-required", "--window-size=1200,1000", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list"))
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
    ok('tab badge counts what the tab lists', +Q('.tab[data-tab=plan] .n').textContent === cards, Q('.tab[data-tab=plan] .n').textContent);
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
    const want = +toc.options[toc.options.length - 1].value + 1;  /* the option names the section; its value is the page index */
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
  if (step === 'widgets') {
    await click('#tab-widgets');
    ok('the workbench lists the widgets placed there', QA('.wg').length === 4 && +Q('.tab[data-tab=widgets] .n').textContent === 4, QA('.wg').length + ' cards, badge ' + Q('.tab[data-tab=widgets] .n').textContent);
    ok('blocks are drawn by the Stage', QA('.wg[data-kind=blocks] .wb-stats dd').length === 3 && QA('.wg .md-tbl tbody tr').length === 4 && !!Q('.wb-bars') && !!Q('.wb-callout.tone-warn') && QA('.wb-check li.done').length === 2);
    ok('an attached image loads into its block', await until(() => { const i = Q('.wb-image img'); return i && i.naturalWidth > 0; }));
    const frames = QA('.wg-frame');
    ok('html widgets run in frames with no same-origin access', frames.length === 2 && frames.every((f) => f.getAttribute('sandbox') === 'allow-scripts'), frames.map((f) => f.getAttribute('sandbox')).join('|'));
    ok('a narrow pane stacks every widget', (() => { const a = Q('.wg[data-w=model]').getBoundingClientRect(), b = Q('.wg[data-w=settings]').getBoundingClientRect(); return b.top > a.top && Math.abs(b.left - a.left) < 4; })());
    await click('#tab-plan');
    await click('[data-k="q-Custom panel"]');
    ok('asking for a custom panel opens the request box', !Q('#compose').hidden && /custom panel/i.test(Q('#note').value));
    Q('#note').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await click('#tab-widgets');
    const probe = Q('.wg[data-w=probe]');
    ok('a frame sends its message to the person first', await until(() => probe.querySelector('.wg-tell')), 'no tell bar');
    ok('the bar quotes the message and nothing has been sent', /Use this still as the title card background/.test(probe.querySelector('.wg-tell-t').textContent) && !/action widget/.test(log()));
    ok('auto height follows the widget content', probe.querySelector('iframe').getBoundingClientRect().height >= 100 && probe.querySelector('iframe').getBoundingClientRect().height < 400, probe.querySelector('iframe').style.height);
    await click('[data-k=wt-send-probe]');
    await wait(500);
    ok('Send hands the message to the agent', /action widget -> \[mod:promo-flow\] Sam sent you a message from the panel "Attached still" \(probe\): Use this still as the title card background/.test(log()), log().slice(0, 300));
    ok('and the bar is gone', !probe.querySelector('.wg-tell'));
    await click('[data-k=wg-big-model]');
    ok('Larger takes the full row and a taller frame', Q('.wg[data-w=model]').dataset.big === '1' && Q('.wg[data-w=model] iframe').getBoundingClientRect().height > 560, Q('.wg[data-w=model] iframe').style.height);
    const seen = [];
    const on = (e) => seen.push(e.data);
    window.addEventListener('message', on);
    const evil = window.document.createElement('iframe');
    evil.setAttribute('sandbox', 'allow-scripts');
    evil.srcdoc = PF.widgetDoc('<script>const r = []; const t = (f) => { try { f(); r.push("reached"); } catch (e) { r.push("blocked"); } };' +
      't(() => parent.document.title); t(() => localStorage.length); t(() => document.cookie.length);' +
      'fetch("https://example.com/").then(() => r.push("reached"), () => r.push("blocked")).then(() => { const i = new Image(); i.onload = () => r.push("reached"); i.onerror = () => { r.push("blocked"); parent.postMessage({ pf: "tell", text: r.join(" ") }, "*"); }; i.src = "https://example.com/x.png"; });<\/script>', {});
    window.document.body.append(evil);
    await until(() => seen.some((d) => d && d.pf === 'tell'));
    window.removeEventListener('message', on); evil.remove();
    ok('a widget cannot reach the Stage, storage, cookies or the network', (seen.find((d) => d && d.pf === 'tell') || {}).text === 'blocked blocked blocked blocked blocked', JSON.stringify(seen.find((d) => d && d.pf === 'tell')));
    await click('#tab-storyboard');
    ok('a widget placed on a tab sits at the top of it', !!Q('.wg[data-w=grade]') && QA('.wg[data-w=grade] .wb-gal img').length >= 0 && !!Q('.wg[data-w=grade] .md-p'), '');
    ok('and its gallery loads both stills', await until(() => QA('.wg[data-w=grade] .wb-gal img').length === 2 && QA('.wg[data-w=grade] .wb-gal img').every((i) => i.naturalWidth > 0)));
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
  if (step === 'review') {
    ok('the draft says what was checked on this very file', /^Checked on this file: 10 passed, 1 warning\. Not checked: vo-script/.test((Q('.verify') || {}).textContent || ''), (Q('.verify') || {}).textContent);
    ok('the checks list every check with what changed', QA('.ck-list li').length === 6 && /1 fixed · 0 broken · 1 still open/.test(Q('.ck-board .sec-h').textContent), QA('.ck-list li').length + ' ' + Q('.ck-board .sec-h').textContent);
    ok('the hidden control never reaches the person', !QA('.ck-list .ck-what').some((e) => /Klingon|periscope|pizza|dinosaur|opera|audience|Snow falls/.test(e.textContent)));
    ok('the blind comparison is reported', /blind judge preferred draft 3/.test(Q('.judged').textContent));
    ok('the look pairs are shown', QA('.lk-pair').length >= 1);
    ok('the latest draft offers to keep working alone', !!Q('[data-k=ap-60]'));
    await click('[data-k=pk-p1-left]');
    ok('the clicked side spins at once and the other answers are held', Q('[data-k=pk-p1-left]').classList.contains('busy') && !!Q('[data-k=pk-p1-left] .spin') && Q('[data-k=pk-p1-right]').disabled && !Q('[data-k=pk-p1-right] .spin'), Q('[data-k=pk-p1-left]').outerHTML.slice(0, 160));
    await wait(700);
    ok('the spinner stays on the chosen side while the agent picks it up', !!Q('[data-k=pk-p1-left] .spin') && Q('[data-k=pk-p1-left]').getAttribute('aria-busy') === 'true', Q('[data-k=pk-p1-left]').outerHTML.slice(0, 160));
    ok('a blind pick reaches the agent as left or right', /action ab -> \[mod:promo-flow\] Sam answered the blind pick p1 \(Which end card\?\): Left\. Run: promo flow ab pick p1 --side left/.test(log()), log().slice(0, 300));
    window.harness.setStage('autopilot'); await wait(400); window.harness.setStage('review'); await wait(900);
    await click('[data-k=as-a1]');
    ok('changing one of the agent\'s choices opens the note box', !Q('#compose').hidden && Q('#btnPrimary').textContent === 'Send change', Q('#btnPrimary').textContent);
    Q('#note').value = 'Use the upbeat guitar track instead'; Q('#note').dispatchEvent(new Event('input')); await wait(100);
    await click('#btnPrimary'); await wait(400);
    ok('the change reaches the agent with the choice it replaces', /action overturn -> \[mod:promo-flow\] Sam wants something else than your choice "Kept the calm piano track/.test(log()), log().slice(0, 300));
    window.harness.setStage('autopilot'); await wait(400); window.harness.setStage('review'); await wait(900);
    ok('the draft plays in our own player', await until(() => Q('.pfp video') && Q('.pfp video').readyState >= 1, 8000));
    Q('.pfp video').currentTime = 0.5; await wait(200);
    await click('[data-k=pin-3]');
    ok('adding a note opens the editor on the timeline at the video time', !Q('.pfp-edit').hidden && /New note at 0:00\.5/.test(Q('.pfp-edit').textContent), Q('.pfp-edit').textContent.slice(0, 80));
    Q('.pfp-edit textarea').value = 'The cursor hides the merged count'; Q('.pfp-edit textarea').dispatchEvent(new Event('input')); await wait(50);
    Q('.pfp-edit').requestSubmit(); await wait(300);
    ok('the note shows as a mark on the bar before anything is sent', QA('.pfp-mark[data-state=new]').length === 1 && /1 change not sent yet/.test(Q('.notes-send').textContent) && !/action pins/.test(log()));
    Q('.pfp-mark').dispatchEvent(new PointerEvent('pointerenter')); await wait(100);
    ok('hovering the mark reads the note', !Q('.pfp-card').hidden && /The cursor hides the merged count/.test(Q('.pfp-card').textContent));
    Q('.pfp [aria-label="Full screen (F)"]').click(); await wait(400);   // not a user gesture here, so full screen is refused and the player fills the window, as in the app
    const filled = Q('.pfp').getBoundingClientRect();
    ok('full screen falls back to filling the window above every panel', Q('.pfp').matches('.max:popover-open') && filled.width === innerWidth && filled.height === innerHeight, Q('.pfp').className + ' ' + filled.width + 'x' + filled.height);
    Q('.pfp').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })); await wait(200);
    ok('Escape puts the player back in the page', !Q('.pfp').matches('.max, [popover]') && Q('.pfp').getBoundingClientRect().width < innerWidth, Q('.pfp').className);
    await click('[data-k=notes-send]'); await wait(400);
    ok('the notes reach the agent with the draft and time', /action pins -> \[mod:promo-flow\] Sam changed 1 note\(s\) on the timeline of draft 3: \(1\) new note at 0:00\.5 \(--at 0\.5\): \u201cThe cursor hides the merged count\u201d Run one command per change/.test(log()), log().slice(0, 300));
    window.harness.setStage('autopilot'); await wait(400); window.harness.setStage('review'); await wait(900);
    await click('[data-k=dr-d0]');
    ok('an earlier draft shows the person\'s pinned note', /The typed sentence takes too long to appear/.test(Q('.pin-list').textContent));
    await click('[data-k=rs-all]');
    ok('going back to a whole draft asks once more', /Confirm/.test(Q('[data-k=rs-all]').textContent) && !/action restore/.test(log()), Q('[data-k=rs-all]').textContent);
    await click('[data-k=rs-all]'); await wait(400);
    ok('then reaches the agent', /action restore -> \[mod:promo-flow\] Sam wants to go back to Draft 1, all of it\. Run: promo flow restore --draft 1/.test(log()), log().slice(0, 300));
  }
  if (step === 'foryou-many') {
    await click('#tab-assets');
    const H = window.harness.H, doc = () => H.docs[H.stage], push = async () => { H.version++; await window.harness.sendState(); await wait(300); };
    const firstLabel = () => (Q('#content').textContent.match(/ui-ticket-list[^ ]*|\bTICKET_MARK\d*/) || [''])[0];
    ok('the blind pick clips load', await until(() => QA('.pick-card video').length >= 2, 8000), QA('.pick-card video').length);
    const v = Q('.pick-card video'); v.loop = true; await v.play();
    ok('the clip is playing', !v.paused);
    const before = Q('#content').firstElementChild;
    doc().state.assets[0].label = 'TICKET_MARK1'; await push(); await wait(800);
    ok('an update from the agent leaves a playing clip alone', v.isConnected && !v.paused && Q('#content').firstElementChild === before, v.isConnected + ' ' + v.paused);
    ok('and says an update is waiting', /more for you/.test(Q('#banners').textContent), Q('#banners').textContent);
    doc().state.assets[0].label = 'TICKET_MARK2'; await push();
    ok('further updates keep waiting', v.isConnected && !v.paused);
    Q('[data-k="b-held-showNow"]').click(); await wait(500);
    ok('Show now repaints with the newest update', !v.isConnected && /TICKET_MARK2/.test(Q('#content').textContent) && !/more for you/.test(Q('#banners').textContent), v.isConnected);
    await wait(300);
    const b2 = Q('#content').firstElementChild;
    doc().summary.badge = 'working'; doc().state.assets[0].label = 'TICKET_MARK3'; await push(); await wait(500);
    ok('while the agent works the page is not rebuilt on every update', Q('#content').firstElementChild === b2 && !/TICKET_MARK3/.test(Q('#content').textContent));
    await click('#tab-storyboard'); await click('#tab-assets');
    ok('the person\'s own click still repaints at once', /TICKET_MARK3/.test(Q('#content').textContent));
  }
  if (step === 'autopilot') {
    ok('the run shows its clock and goal', /Working until every check passes · 0 of 60 min · 5 of 6 checks pass/.test(Q('#stateLine').textContent) && !!Q('.ap-card .ap-bar'), Q('#stateLine').textContent);  /* the goal is the header's line; the card keeps the clock bar */
    ok('no second start while it runs', !Q('[data-k=ap-60]'));
    await click('[data-k=ap-stop]'); await wait(400);
    ok('stop reaches the agent', /action autopilot -> \[mod:promo-flow\] Sam asked you to stop working on your own/.test(log()), log().slice(0, 300));
  }
  if (step === 'starting') {
    const glow = () => Q('#glow').dataset.mode;
    ok('the pane glows while the plan is prepared', glow() === 'wait', glow());
    window.harness.setStage('pick');
    ok('the glow flashes once when the plan lands', await until(() => glow() === 'arrive', 2000), glow());
    ok('then it goes quiet', await until(() => glow() === 'off', 4000), glow());
    window.harness.setStage('review'); await wait(400);
    ok('a later update does not replay the intro', glow() === 'off', glow());
  }
  if (step === 'storyboard') {
    ok('app scenes with a real screen say so', QA('.scene-h .chip').some((c) => c.textContent === 'Real screen') && QA('.fr .lbl').some((l) => /real/.test(l.textContent)));
    ok('an unreachable screen says why', QA('.scene-h .chip').some((c) => c.textContent === 'Screen not reachable') && /reviewer account/.test(Q('#content').textContent));
    /* an update that lands while the agent is idle repaints softly: pictures stay, new cards ease in, removed ones ease out */
    const H = window.harness.H, doc = () => H.docs[H.stage], push = async () => { H.version++; await window.harness.sendState(); await wait(60); };
    doc().summary = Object.assign({}, doc().summary, { badge: 'waiting' }); await push();       /* the storyboard asks for nothing and the fixture shows the agent busy: make it idle for this check */
    const scenes = doc().state.boards[0].scenes, img = Q('#content [data-ms="img"] img'), sid = (x) => '[id="scene-' + doc().state.boards[0].id + '-' + x + '"]';
    ok('there is a loaded picture to keep', !!img);
    const extra = JSON.parse(JSON.stringify(scenes[1])); extra.id = 'ZZ'; scenes.push(extra); await push();
    const added = Q(sid('ZZ')), top = Q('#content').firstElementChild;
    ok('a soft repaint keeps the picture and the page does not fade', !!img && img.isConnected && top.classList.contains('calm') && getComputedStyle(top).animationName === 'none', [img && img.isConnected, top.className, getComputedStyle(top).animationName, Q('#app').dataset.held].join(' '));
    ok('a new scene card eases in', !!added && added.classList.contains('pf-in'), added && added.className);
    ok('no picture goes back to a skeleton', QA('#content .sk').length === 0, QA('#content .sk').length);
    scenes.pop(); await push();
    ok('a removed scene card eases out instead of vanishing', !Q(sid('ZZ')) && !!Q('#content .pf-out'));
    await wait(450);
    ok('and is gone afterwards', !Q('#content .pf-out'));
  }
  if (step === 'edit') {
    ok('the Edit tab opens by itself at the drafts stage', Q('#tab-edit') && Q('#tab-edit').getAttribute('aria-selected') === 'true', (Q('.tab[aria-selected=true]') || {}).id);
    ok('the editor is there', await until(() => QA('.ed-clip').length === 4), QA('.ed-clip').length);
    ok('the draft is a milestone: the stepper is Draft, Review, Final', QA('#stepper li').length === 3 && /^Production/.test(Q('#stepNo').textContent), QA('#stepper li').length + ' ' + Q('#stepNo').textContent);
    ok('the planning tabs give way to the editor', !Q('#tab-scripts') && !Q('#tab-storyboard') && !Q('#tab-assets') && !!Q('#tab-draft'), QA('.tab').map((t) => t.dataset.tab).join());
    ok('the agent\'s preview clip is in the inspector', !!Q('.ed-pv[data-pv="p1"] video'));
    ok('the bin lists this video\'s footage, music, voice and sounds', QA('.ed-item').length >= 10 && ['footage', 'music', 'voice', 'sfx', 'draft'].every((k) => Q('.ed-item[data-kind="' + k + '"]')), QA('.ed-item').length);
    const lane = (k) => Q('.ed-lane[data-lane="' + k + '"]');
    ok('the timeline has every track', ['v', 'cap', 'vo', 'music', 'sfx'].every((k) => lane(k)) && QA('.ed-vob').length === 3 && QA('.ed-mus').length === 1 && QA('.ed-sfx').length === 2 && QA('.ed-capb').length === 2,
      [QA('.ed-vob').length, QA('.ed-mus').length, QA('.ed-sfx').length, QA('.ed-capb').length].join(' '));
    const w1 = () => Q('.ed-clip[data-shot="01"]').getBoundingClientRect().width, fitW = w1();
    ok('the timeline opens fitted, with a zoom bar and presets', !!Q('[data-k=ed-zoom-fit]') && Q('[data-k=ed-zoom-fit]').getAttribute('aria-pressed') === 'true' && /Fit/.test(Q('.ed-zlab').textContent), Q('.ed-zlab').textContent);
    await click('[data-k=ed-zoom-4]');
    ok('the 4x preset makes every clip four times wider', Math.abs(w1() / fitW - 4) < 0.1 && Q('[data-k=ed-zoom-4]').getAttribute('aria-pressed') === 'true' && /^4×/.test(Q('.ed-zlab').textContent), (w1() / fitW).toFixed(2) + ' ' + Q('.ed-zlab').textContent);
    await click('[data-k=ed-zoom-out]');
    ok('zoom out steps back', w1() < fitW * 4 - 1 && w1() > fitW, (w1() / fitW).toFixed(2));
    Q('.ed-scroll').dispatchEvent(new WheelEvent('wheel', { deltaY: -40, ctrlKey: true, clientX: Q('.ed-scroll').getBoundingClientRect().left + 60, bubbles: true, cancelable: true })); await wait(150);
    ok('ctrl + wheel (a pinch) zooms in smoothly', w1() > fitW * 3, (w1() / fitW).toFixed(2));
    await click('[data-k=ed-zoom-fit]');
    ok('Fit shows the whole film again', Math.abs(w1() - fitW) < 1 && Q('.ed-scroll').scrollLeft === 0, w1() + ' ' + fitW);
    Q('.ed-clip[data-shot="03"]').dispatchEvent(new PointerEvent('pointerdown', { clientX: Q('.ed-clip[data-shot="03"]').getBoundingClientRect().left + 5, button: 0, bubbles: true, pointerId: 6 }));
    Q('.ed-lanes').dispatchEvent(new PointerEvent('pointerup', { bubbles: true, pointerId: 6 })); await wait(100);
    await click('[data-k=ed-zoom-shot]');
    const c3 = Q('.ed-clip[data-shot="03"]').getBoundingClientRect(), sc = Q('.ed-scroll').getBoundingClientRect();
    ok('Shot zooms to the selected shot and brings it into view', c3.width > sc.width * 0.8 && c3.left >= sc.left - 1 && c3.right <= sc.right + 1, c3.left + '..' + c3.right + ' in ' + sc.left + '..' + sc.right);
    await click('[data-k=ed-zoom-fit]');
    ok('the unbuilt shot says so', Q('.ed-clip[data-shot="03"]').classList.contains('stale') && !Q('.ed-clip[data-shot="01"]').classList.contains('stale'));
    const pend = () => +((Q('[data-k=ed-pending]') || {}).textContent || '').replace(/\D/g, '');
    const lanes = Q('.ed-lanes'), c1 = Q('.ed-clip[data-shot="01"]').getBoundingClientRect();
    const pe = (type, x, y) => lanes.dispatchEvent(new PointerEvent(type, { clientX: x, clientY: y, button: 0, buttons: type === 'pointerup' ? 0 : 1, bubbles: true, pointerId: 7, isPrimary: true }));
    const pps = c1.width / 2;                         /* shot 01 is 2 s */
    Q('.ed-clip[data-shot="01"] .ed-edge').dispatchEvent(new PointerEvent('pointerdown', { clientX: c1.right - 2, clientY: c1.top + 10, button: 0, buttons: 1, bubbles: true, pointerId: 7, isPrimary: true })); pe('pointermove', c1.right - 2 + pps * 0.5 + 2, c1.top + 10); pe('pointerup', c1.right - 2 + pps * 0.5 + 2, c1.top + 10); await wait(200);
    ok('dragging a cut trims on the beat grid', pend() === 1 && Math.abs(Q('.ed-clip[data-shot="01"]').getBoundingClientRect().width - pps * 2.5) < 2, pend() + ' ' + Q('.ed-clip[data-shot="01"]').getBoundingClientRect().width + ' want ' + pps * 2.5);
    Q('.ed-clip[data-shot="02"]').dispatchEvent(new PointerEvent('pointerdown', { clientX: Q('.ed-clip[data-shot="02"]').getBoundingClientRect().left + 10, button: 0, bubbles: true, pointerId: 8 })); pe('pointerup', 0, 0); await wait(150);
    const src = Q('[data-k=ins-source]');
    ok('the inspector shows the selected shot', !!src && /Shot 02/.test(Q('.ed-ih').textContent), (Q('.ed-ih') || {}).textContent);
    src.value = 'rec-board'; src.dispatchEvent(new Event('change')); await wait(150);
    ok('swapping its footage is an edit, and the shot reads not rendered', pend() === 2 && Q('.ed-clip[data-shot="02"]').classList.contains('stale') && Q('[data-k=ins-source]').value === 'rec-board' && /not rendered/i.test(Q('.ed-insp').textContent), pend());
    Q('.ed-vob[data-vo="v2"]').dispatchEvent(new PointerEvent('pointerdown', { clientX: Q('.ed-vob[data-vo="v2"]').getBoundingClientRect().left + 3, button: 0, bubbles: true, pointerId: 9 })); pe('pointerup', 0, 0); await wait(150);
    await click('[data-k=ins-vo-mute]');
    ok('muting a voice line is an edit and the line greys out', pend() === 3 && Q('.ed-vob[data-vo="v2"]').classList.contains('muted'), pend());
    await click('[data-k=ed-undo]');
    ok('undo takes the last edit back', pend() === 2 && !Q('.ed-vob[data-vo="v2"]').classList.contains('muted'), pend());
    await click('[data-k=ed-redo]'); await click('[data-k=ed-undo]');
    ok('redo puts it back (and undo again)', pend() === 2);
    await click('[data-k="sug-try:s1"]');
    ok('trying the agent\'s suggestion previews its music', /brighter|Music bright|music-bright/i.test(Q('.ed-mus').textContent) && /Trying/.test(Q('.ed-note').textContent), Q('.ed-mus').textContent);
    await click('[data-k="sug-try:s1"]');
    ok('the Render line says what re-renders', /2 shots \+ mix/.test(Q('.ed-sum').textContent), Q('.ed-sum').textContent);
    ok('Quick preview is offered for the changed shots', Q('[data-k=ed-preview]') && !Q('[data-k=ed-preview]').disabled && /shot|–/.test(Q('[data-k=ed-preview]').title), (Q('[data-k=ed-preview]') || {}).title);
    await click('[data-k=ed-render]');
    ok('Render sends the edits to the agent as one action', await until(() => /action edit -> .*trim 01 end=5 ; swap 02 rec-board/.test(log())), log().split('\n').find((l) => /action edit/.test(l)) || 'no edit action');
    ok('the editor does not overflow the pane', Q('.ed').scrollWidth <= Q('.ed').clientWidth + 1 && Q('#scroller').scrollWidth <= Q('#scroller').clientWidth + 1, Q('.ed').scrollWidth + ' > ' + Q('.ed').clientWidth);
    ok('on a narrow pane the bin is a drawer', getComputedStyle(Q('.ed-bin')).display === 'none' && !!Q('[data-k=ed-bin-toggle]'), getComputedStyle(Q('.ed-bin')).display);
    await click('[data-k=ed-bin-toggle]');
    ok('the drawer opens', getComputedStyle(Q('.ed-bin')).display !== 'none');
  }
  if (step === 'pick') {
    const badge = () => Q('#badgeText').textContent;
    const read = Q('[data-k="open-script:A"]');
    read.focus(); read.click(); await wait(400);
    ok('Read full script opens a dialog over the pane', !Q('#modal').hidden && !!Q('#modal .doc-page') && /Wake up/.test(Q('#modal .rd-title').textContent), Q('#modal').hidden);
    ok('the cards and the footer stay where they were', QA('.choice').length === 3 && Q('#btnPrimary').textContent.length > 0);
    ok('focus moves into the dialog', Q('#modal').contains(root.activeElement), (root.activeElement || {}).tagName);
    root.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, composed: true })); await wait(300);
    ok('Escape closes it and returns focus to the link', Q('#modal').hidden && root.activeElement === read, (root.activeElement || {}).tagName);
    read.click(); await wait(300);
    Q('[data-k=rd-close]').click(); await wait(300);
    ok('Close closes it', Q('#modal').hidden);
    ok('before sending, the pick gate is the person\'s turn', badge() === 'Your turn', badge());
    Q('.choice input').click(); await wait(200);
    await click('#btnPrimary');
    await until(() => /Sent/.test(Q('#gateNote').textContent));
    ok('after sending the picks the badge is not Your turn', badge() === 'With the agent', badge());
    ok('and the header line says it was sent', /Sent/.test(Q('#stateLine').textContent), Q('#stateLine').textContent);
  }
  return out;
})()"""


WIDE = r"""(async () => {
  const root = window.harness.root, wait = (ms) => new Promise((r) => setTimeout(r, ms));
  root.querySelector('#tab-widgets').click(); await wait(500);
  const a = root.querySelector('.wg[data-w=model]').getBoundingClientRect(), b = root.querySelector('.wg[data-w=settings]').getBoundingClientRect(), full = root.querySelector('.wg[data-w=render-queue]').getBoundingClientRect();
  return [{ name: 'span puts widgets side by side on a wide pane, 8 and 4 of 12 columns', pass: Math.abs(a.top - b.top) < 4 && b.left > a.left && a.width > 1.8 * b.width && a.width < 2.2 * b.width, info: [a.left, a.width, b.left, b.width].join(' ') },
    { name: 'a 12 column widget takes the whole row', pass: full.width > a.width + b.width, info: full.width }];
})()"""


def uicheck(sh, only=()):
    bad = 0
    for r in ([] if only else sh.js(WIDE, sh.open("widgets", 900, 1000, False)) or []):
        bad += not r["pass"]
        print(("ok   " if r["pass"] else "FAIL ") + f"widgets-wide: {r['name']}" + (f"  [{r['info']}]" if r["info"] and not r["pass"] else ""))
    for st in ["starting", "plan", "widgets", "dense", "pick", "review", "autopilot", "storyboard", "foryou-many", "edit"]:
        if only and st not in only:
            continue
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
            bad = uicheck(sh, only)
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
    ("intro-wait-520", "starting", 520, 900, True, "", ["TOP:0", "TOP:0"]),
    ("intro-wait-1100", "starting", 1100, 800, True, "", ["TOP:0", "TOP:0"]),
    ("intro-arrive-520", "starting", 520, 900, True, "", ["TOP:window.harness.setStage('pick')"]),
    ("picker-520", "picker", 520, 900, True, "&mod=promo-projects", None),
    ("picker-900-light", "picker", 900, 900, False, "&mod=promo-projects", None),
    ("picker-end-520", "picker", 520, 900, True, "&mod=promo-projects", ["(() => { const find = (r) => r.querySelector('.list') || [...r.querySelectorAll('*')].map((e) => e.shadowRoot).filter(Boolean).map(find).find(Boolean); const l = find(document); if (!l) throw new Error('no .list'); l.scrollTop = 1e6; })()"]),
    ("files-520", "assets", 520, 900, True, "", [click("#tab-files")]),
    ("files-staged-520", "assets", 520, 900, True, "", [click("#tab-files"), '(() => { const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array(3 << 20)], "board-run.mov", { type: "video/quicktime" })); dt.items.add(new File([new Uint8Array(40000)], "login.png", { type: "image/png" })); const t = document.querySelector(".files"); t.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); })()']),
    ("files-staged-380-light", "assets", 380, 780, False, "", [click("#tab-files"), '(() => { const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array(3 << 20)], "board-run.mov", { type: "video/quicktime" })); dt.items.add(new File([new Uint8Array(40000)], "login.png", { type: "image/png" })); const t = document.querySelector(".files"); t.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); })()']),
    ("files-sent-520", "assets", 520, 900, True, "", [click("#tab-files"), '(() => { const dt = new DataTransfer(); dt.items.add(new File([new Uint8Array(3 << 20)], "board-run.mov", { type: "video/quicktime" })); dt.items.add(new File([new Uint8Array(40000)], "login.png", { type: "image/png" })); const t = document.querySelector(".files"); t.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true })); })()', typein("#fnote", "the real board run"), click("[data-k=files-send]"), "new Promise((r) => setTimeout(r, 900))"]),
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
    ("blind-pick-sent-520", "review", 520, 900, False, "", [click("[data-k=pk-p1-left]"), "document.querySelector('.pick-card').scrollIntoView()"]),
    ("scene-comments-900", "storyboard-notes", 900, 1100, False, "", ["document.getElementById('scene-A-02').scrollIntoView()", click("[data-k='note-A-03']"),
     typein("#note", "Slow the push-in a little.")]),
    ("scene-count-520", "storyboard-notes", 520, 900, False, "", []),
    ("scene-count-sent-520", "storyboard-notes", 520, 900, False, "", [click("[data-k='note-A-03']"), typein("#note", "Slow the push-in a little."), click("#btnPrimary")]),
    ("recommended-tip-520", "pick", 520, 900, False, "", ["document.querySelector('.rec-pill').focus()"]),
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
    ("foryou-many-1100", "foryou-many", 1100, 1700, True, "", [click("#tab-assets")]),
    ("foryou-many-760", "foryou-many", 760, 1000, True, "", [click("#tab-assets")]),
    ("foryou-many-520", "foryou-many", 520, 1000, True, "", [click("#tab-assets")]),
    ("foryou-many-readonly-760", "foryou-many", 760, 1000, True, "&readonly=1", [click("#tab-assets")]),
    ("foryou-many-380", "foryou-many", 380, 900, True, "", [click("#tab-assets")]),
    ("long-assets-380", "long-content", 380, 780, True, "", [click("#tab-assets")]),
    ("long-scripts-520", "long-content", 520, 900, True, "", [click("#tab-scripts")]),
    ("starting-520", "starting", 520, 900, False, "", ["TOP:0", "TOP:0"]),
    ("starting-380-dark", "starting", 380, 780, True, "", ["TOP:0", "TOP:0"]),
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
    ("widgets-520", "widgets", 520, 1100, False, "", [click("#tab-widgets")]),
    ("widgets-scrolled-520", "widgets", 520, 1100, False, "", [click("#tab-widgets"), scroll(1400)]),
    ("widgets-380-dark", "widgets", 380, 900, True, "", [click("#tab-widgets")]),
    ("widgets-900", "widgets", 900, 1000, False, "", [click("#tab-widgets")]),
    ("widgets-pinned-520", "widgets", 520, 900, True, "", [click("#tab-storyboard")]),
    ("plan-empty-520", "scripts", 520, 900, True, "", [click("#tab-plan")]),
    ("plan-scrolled-520", "plan", 520, 900, True, "", [click("#tab-plan"), scroll(900)]),
    ("reader-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="open-doc:full-script-a"]')]),
    ("reader-380-dark", "plan", 380, 780, True, "", [click("#tab-plan"), click('[data-k="open-doc:full-script-a"]'), click('[data-k="pg-next-top"]')]),
    ("reader-table-520", "plan", 520, 900, True, "", [click("#tab-plan"), click('[data-k="open-doc:shotlist-a"]')]),
    ("reader-find-900", "plan", 900, 900, False, "", [click("#tab-plan"), click('[data-k="open-doc:full-script-a"]'), typein('[data-k="rd-find"]', "blinds")]),
    ("reader-checklist-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="open-doc:capture-a"]')]),
    ("request-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="q-Shot list"]')]),
    ("request-380-dark", "plan", 380, 780, True, "", [click("#tab-plan"), click('[data-k="q-Everything for production"]')]),
    ("request-empty-520", "plan", 520, 900, False, "", [click("#tab-plan"), click('[data-k="q-other"]')]),
    ("plan-search-empty-520", "plan", 520, 900, False, "", [click("#tab-plan"), typein('[data-k="doc-q"]', "zzz")]),
    ("style-own-520", "discover", 520, 900, True, "", [typein("#own", "slow, warm")]),
    ("style-ref-bad-520", "discover", 520, 900, False, "", [typein("#ref", "my reference"), "document.getElementById('ref').scrollIntoView({block: 'center'})"]),
    ("style-focus-520", "discover", 520, 900, True, "", ["document.querySelector('.choice input').focus()"]),
    ("picks-two-520", "pick", 520, 900, False, "", ["document.querySelectorAll('.choice input')[0].click()", "document.querySelectorAll('.choice input')[1].click()"]),
    ("script-read-520", "pick", 520, 900, False, "", []),
    ("script-reader-520", "scripts", 520, 900, True, "", [click('[data-k="open-script:A"]')]),
    ("script-modal-1100", "pick", 1100, 900, True, "", [click('[data-k="open-script:A"]')]),
    ("script-modal-380", "pick", 380, 780, True, "", [click('[data-k="open-script:A"]')]),
    ("dense-520", "dense", 520, 1100, False, "", []),
    ("dense-time-520", "dense", 520, 1100, False, "", [click('[data-k="sbv-time"]')]),
    ("dense-time-900", "dense", 900, 1000, True, "", [click('[data-k="sbv-time"]')]),
    ("dense-scene-380", "dense", 380, 900, True, "", [scroll(780)]),
    ("scripts-after-pick-520", "storyboard", 520, 900, False, "", [click("#tab-scripts")]),
]

if __name__ == "__main__":
    sys.exit(main() or 0)
