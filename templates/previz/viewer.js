/* Previz viewer: the scene (window.PREVIZ_SCENE, already with the agent's overrides applied) as wireframes in Three.js.
   World: the frame is 1 unit tall and `aspect` units wide, centre at the origin, y up. A camera is the box (cx, cy, w) of promo's cinema
   `cam` keys: w = visible width as a fraction of the frame. Orthographic shows exactly that box; perspective puts the camera at the distance
   where a plane at z = 0 shows that box, so planes in front / behind scale and drift against each other (parallax).
   Keep the maths in step with promo/previz.py `project()` / `layout()`: the PIL fallback strip draws the same thing flat. */
(function () {
  "use strict";
  var S = window.PREVIZ_SCENE, STILLS = window.PREVIZ_STILLS || {};
  var Q = new URLSearchParams(location.search);
  var STRIP = Q.get("strip") === "1";
  var A = S.frame.aspect[0] / S.frame.aspect[1];
  var FPS = S.frame.fps || 30;
  var TAN = Math.tan((40 / 2) * Math.PI / 180);
  var PLATE_Z = -1.0;
  var OVER = { ortho: 1.15, persp: (1 / (2 * TAN) + 1) / (1 / (2 * TAN)) };
  var COLOR = { plate: 0x56688c, floating: 0x58c8e6, device: 0xb08cf0, fullscreen: 0x6edc8c, type: 0xf0b840 };
  var CSS = { plate: "#56688c", floating: "#58c8e6", device: "#b08cf0", fullscreen: "#6edc8c", type: "#f0b840" };
  var BG = 0x14161b;
  var num = function (v, d) { v = parseFloat(v); return isFinite(v) ? v : d; };
  var $ = function (id) { return document.getElementById(id); };

  var state = { t: num(Q.get("t"), 0), playing: false, proj: null, stills: Q.get("stills") === "1" || Object.keys(STILLS).length > 0, guides: true, last: 0 };
  var total = S.duration_s;

  function shotAt(t) {
    for (var i = 0; i < S.shots.length; i++) { var s = S.shots[i]; if (t >= s.t0 && t < s.t0 + s.dur) return s; }
    return S.shots[S.shots.length - 1];
  }
  function ease(p, kind) { p = Math.min(Math.max(p, 0), 1); return kind === "linear" ? p : p * p * (3 - 2 * p); }
  function camAt(shot, t) {
    var ks = ((shot.camera && shot.camera.keys) || [{ t: 0, cx: 0.5, cy: 0.5, w: 1 }]).slice().sort(function (a, b) { return a.t - b.t; });
    var g = function (k) { return [num(k.cx, 0.5), num(k.cy, 0.5), num(k.w, 1)]; };
    if (t <= ks[0].t) return g(ks[0]);
    for (var i = 1; i < ks.length; i++) {
      if (t <= ks[i].t) {
        var a = g(ks[i - 1]), b = g(ks[i]), p = ease((t - ks[i - 1].t) / Math.max(ks[i].t - ks[i - 1].t, 1e-9), ks[i].ease || "smooth");
        return [a[0] + (b[0] - a[0]) * p, a[1] + (b[1] - a[1]) * p, a[2] + (b[2] - a[2]) * p];
      }
    }
    return g(ks[ks.length - 1]);
  }
  function modeOf(shot) {
    var ks = (shot.camera && shot.camera.keys) || [];
    if (ks.length < 2) return "locked";
    var a = ks[0], b = ks[ks.length - 1], dw = num(b.w, 1) - num(a.w, 1), dc = Math.hypot(num(b.cx, 0.5) - num(a.cx, 0.5), num(b.cy, 0.5) - num(a.cy, 0.5));
    if (Math.abs(dw) < 1e-4 && dc < 1e-4) return "locked";
    if (dc > 0.01 && Math.abs(dw) < 0.02) return "parallax";
    return dw < 0 ? "push" : "pullback";
  }
  function projOf(shot) { return (state.proj || (shot.camera && shot.camera.projection) || S.projection || "ortho"); }

  /* ---- scene building ------------------------------------------------------------------------------------------------ */
  var scene = new THREE.Scene();
  scene.background = new THREE.Color(BG);
  var groups = {};

  function world(cx, cy) { return [(cx - 0.5) * A, 0.5 - cy]; }
  function rectLine(w, h, color, z, op) {
    var g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-w / 2, -h / 2, 0), new THREE.Vector3(w / 2, -h / 2, 0), new THREE.Vector3(w / 2, h / 2, 0), new THREE.Vector3(-w / 2, h / 2, 0)]);
    var l = new THREE.LineLoop(g, new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: op == null ? 1 : op, depthWrite: false }));
    l.position.z = z;
    return l;
  }
  function crossLines(w, h, color, z) {
    var g = new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-w / 2, -h / 2, 0), new THREE.Vector3(w / 2, h / 2, 0), new THREE.Vector3(-w / 2, h / 2, 0), new THREE.Vector3(w / 2, -h / 2, 0)]);
    var l = new THREE.LineSegments(g, new THREE.LineBasicMaterial({ color: color, transparent: true, opacity: 0.22, depthWrite: false }));
    l.position.z = z;
    return l;
  }
  function fill(w, h, color, op, z) {
    var m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ color: color, transparent: true, opacity: op, depthWrite: false }));
    m.position.z = z;
    return m;
  }
  function labelMesh(text, w, h, css, align, z) {
    var c = document.createElement("canvas"), px = 512;
    c.width = px; c.height = Math.max(32, Math.round(px * h / w));
    var x = c.getContext("2d");
    var size = c.height * 0.7;
    x.font = "600 " + size + "px -apple-system,Segoe UI,sans-serif";
    x.fillStyle = css; x.textBaseline = "middle"; x.textAlign = align;
    x.fillText(text, align === "center" ? px / 2 : size * 0.4, c.height / 2, px * 0.96);
    var t = new THREE.CanvasTexture(c);
    var m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false }));
    m.position.z = z;
    return m;
  }
  function stillMesh(uri, w, h, z) {
    var tex = new THREE.TextureLoader().load(uri, function () { if (window.__previzRedraw) window.__previzRedraw(); });
    var m = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.4, depthWrite: false }));
    m.position.z = z; m.userData.still = true;
    return m;
  }
  function typeSize(c) {
    var h = Math.max(num(c.size_pct, 6), 1) / 100 * 1.25, chars = Math.max(String(c.text || "").length, 4);
    return [Math.min(chars * h * 0.5 / A, 0.92), h];
  }
  function panelH(p) { return p.kind === "fullscreen" ? 1 : num(p.w, 0.5) * A / Math.max(num(p.aspect, A), 0.05); }

  function buildShot(shot, proj) {
    var g = new THREE.Group(), z = 0;
    if (shot.plate) {
      var over = OVER[proj], pw = over * A, ph = over, pz = PLATE_Z;
      g.add(fill(pw, ph, COLOR.plate, 0.16, pz), rectLine(pw, ph, COLOR.plate, pz, 0.9), crossLines(pw, ph, COLOR.plate, pz));
      g.add(labelMesh((shot.plate.id || "plate") + "  ui:false", 0.5 * A, 0.05, CSS.plate, "left", pz + 0.001).translateX(-pw / 2 + 0.25 * A).translateY(ph / 2 - 0.03));
    }
    (shot.panels || []).slice().sort(function (a, b) { return num(a.z, 0) - num(b.z, 0); }).forEach(function (p, i) {
      var w = p.kind === "fullscreen" ? A : num(p.w, 0.5) * A, h = panelH(p) * (p.kind === "fullscreen" ? 1 : 1), xy = world(num(p.cx, 0.5), num(p.cy, 0.5)), col = COLOR[p.kind] || COLOR.floating, pz = num(p.z, 0) + i * 0.002;
      var grp = new THREE.Group();
      grp.add(fill(w, h, col, 0.10, 0), rectLine(w, h, col, 0.0005, 1), crossLines(w, h, col, 0.0005));
      var thumb = p.source && STILLS[p.source];
      if (thumb) { var sm = stillMesh(thumb, w, h, 0.0002); sm.visible = state.stills; grp.add(sm); }
      var lab = labelMesh(p.id + "  " + (p.kind || "floating") + (p.source ? "  " + p.source : ""), Math.min(w, 0.7 * A), Math.min(0.06, h * 0.3), CSS[p.kind] || CSS.floating, "left", 0.001);
      lab.position.x = -w / 2 + Math.min(w, 0.7 * A) / 2; lab.position.y = h / 2 - Math.min(0.06, h * 0.3) / 2 - 0.004;
      grp.add(lab);
      if (p.crop && p.crop.length) {          // where the camera looks inside the real still (cinema's `cam` on a panel shot)
        var cr = rectLine(1, 1, 0xffffff, 0.0008, 0.6); cr.userData = { crop: p.crop, pw: w, ph: h }; grp.add(cr);
      }
      grp.position.set(xy[0], xy[1], pz);
      g.add(grp);
    });
    (shot.type || []).forEach(function (c) {
      var sz = typeSize(c), w = sz[0] * A, h = sz[1], xy = world(num(c.cx, 0.5), num(c.cy, 0.5));
      var grp = new THREE.Group();
      grp.add(fill(w, h, COLOR.type, 0.08, 0), rectLine(w, h, COLOR.type, 0.0005, 1));
      grp.add(labelMesh(String(c.text || "(needs copy)"), w, h, CSS.type, "center", 0.001));
      if (c.brackets) {
        var b = h * 0.3, bx = w / 2 + h * 0.15, pts = [];
        [-1, 1].forEach(function (s) {
          pts.push(new THREE.Vector3(s * (bx + b * 0.5), h / 2, 0), new THREE.Vector3(s * bx, h / 2, 0), new THREE.Vector3(s * bx, h / 2, 0), new THREE.Vector3(s * bx, -h / 2, 0),
                   new THREE.Vector3(s * bx, -h / 2, 0), new THREE.Vector3(s * (bx + b * 0.5), -h / 2, 0));
        });
        grp.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: COLOR.type })));
      }
      grp.userData = { at: num(c.at, 0), dur: num(c.dur, 2) };
      grp.position.set(xy[0], xy[1], 0.02);
      g.add(grp);
    });
    return g;
  }

  var ortho = new THREE.OrthographicCamera(-A / 2, A / 2, 0.5, -0.5, 0.01, 50);
  var persp = new THREE.PerspectiveCamera(40, A, 0.01, 50);
  var renderer;
  function makeRenderer() {
    renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
    renderer.setPixelRatio(STRIP ? 1 : Math.min(window.devicePixelRatio || 1, 2));
    return renderer;
  }

  function frame(t) {
    var shot = shotAt(t), lt = Math.min(Math.max(t - shot.t0, 0), shot.dur), proj = projOf(shot), cam = camAt(shot, lt);
    var key = shot.id + "/" + proj;
    Object.keys(groups).forEach(function (k) { groups[k].visible = k === key; });
    if (!groups[key]) { groups[key] = buildShot(shot, proj); scene.add(groups[key]); groups[key].visible = true; }
    groups[key].children.forEach(function (c) {
      if (c.userData && c.userData.dur != null) c.visible = lt >= c.userData.at && lt < c.userData.at + c.userData.dur;
      c.traverse(function (o) { if (o.userData && o.userData.still) o.visible = state.stills; });
    });
    groups[key].traverse(function (o) {
      if (!(o.userData && o.userData.crop)) return;
      var ck = camAt({ camera: { keys: o.userData.crop } }, lt);
      o.visible = ck[2] < 0.995 || Math.abs(ck[0] - 0.5) > 1e-3 || Math.abs(ck[1] - 0.5) > 1e-3;
      o.scale.set(ck[2] * o.userData.pw, ck[2] * o.userData.ph, 1);
      o.position.set((ck[0] - 0.5) * o.userData.pw, (0.5 - ck[1]) * o.userData.ph, 0.0008);
    });
    var cx = (cam[0] - 0.5) * A, cy = 0.5 - cam[1], cw = cam[2], camera;
    if (proj === "persp") {
      camera = persp; camera.position.set(cx, cy, cw / (2 * TAN));
    } else {
      camera = ortho; camera.left = -cw * A / 2; camera.right = cw * A / 2; camera.top = cw / 2; camera.bottom = -cw / 2; camera.position.set(cx, cy, 5);
    }
    camera.updateProjectionMatrix();
    renderer.render(scene, camera);
    return { shot: shot, lt: lt, proj: proj, cam: cam };
  }

  /* ---- strip mode: every requested time on one canvas, one WebGL context ---------------------------------------------- */
  function drawStrip() {
    var geo = (Q.get("geo") || "").split(",").map(Number), times = (Q.get("times") || "0").split(",").map(Number);
    var tw = geo[0], th = geo[1], lh = geo[2], cols = geo[3], gap = geo[4], pad = geo[5], W = geo[6], H = geo[7];
    document.body.classList.add("strip");
    document.body.style.margin = "0";
    var c = $("stripc"); c.width = W; c.height = H;
    var x = c.getContext("2d");
    x.fillStyle = "#14161b"; x.fillRect(0, 0, W, H);
    if (!renderer) { makeRenderer(); renderer.setSize(tw, th, false); }
    window.__previzRedraw = drawStrip;
    state.stills = Object.keys(STILLS).length > 0;
    times.forEach(function (t, i) {
      var r = frame(t), ox = pad + (i % cols) * (tw + gap), oy = pad + Math.floor(i / cols) * (th + lh + gap);
      x.drawImage(renderer.domElement, ox, oy, tw, th);
      x.strokeStyle = "#969caa"; x.lineWidth = 1; x.strokeRect(ox + 0.5, oy + 0.5, tw - 1, th - 1);
      x.fillStyle = "#c8cdd7"; x.font = "11px -apple-system,Segoe UI,sans-serif"; x.textBaseline = "top";
      x.fillText(r.shot.id + "  " + t.toFixed(1) + "s  " + (r.shot.framing || "") + "  " + modeOf(r.shot) + "  " + r.proj, ox, oy + th + 3);
    });
    window.__previzDone = true;
  }
  function fail(e) {
    document.body.style.background = "#7a1f1f";
    document.body.style.margin = "0";
    ["app"].forEach(function (id) { $(id).style.display = "none"; });
    var d = document.createElement("div");
    d.style.cssText = "padding:30px;color:#fff;font:16px sans-serif";
    d.textContent = "previz: WebGL is not available here (" + (e && e.message || e) + "). Use `promo previz strip --engine pil`, or open this file in a browser with WebGL.";
    document.body.appendChild(d);
    window.__previzError = String(e && e.message || e);
  }

  /* ---- interactive viewer ---------------------------------------------------------------------------------------------- */
  function fit() {
    var st = $("stage"), mw = st.clientWidth - 24, mh = st.clientHeight - 24, w = Math.min(mw, mh * A), h = w / A;
    renderer.setSize(Math.max(w, 80), Math.max(h, 45));
  }
  function ui() {
    $("name").textContent = (S.source && (S.source.ref || S.source.kind)) || "";
    $("hash").textContent = "scene " + (S.hash || "");
    var chips = $("chips");
    S.shots.forEach(function (s) {
      var d = document.createElement("div");
      d.className = "chip"; d.style.flex = String(Math.max(s.dur, 0.2)); d.style.background = CSS[s.framing] || CSS.floating; d.textContent = s.id; d.title = s.id + "  " + s.t0.toFixed(1) + "s  " + (s.framing || "");
      d.onclick = function () { state.t = s.t0; draw(); };
      chips.appendChild(d);
    });
    var scrub = $("scrub");
    scrub.max = total; scrub.oninput = function () { state.t = parseFloat(scrub.value); draw(); };
    $("play").onclick = function () { toggle(); };
    if (!Q.get("t")) state.t = 0;
    window.addEventListener("resize", function () { fit(); draw(); });
    window.addEventListener("keydown", function (e) {
      var k = e.key;
      if (k === " ") { toggle(); e.preventDefault(); }
      else if (k === "ArrowLeft") { state.t = Math.max(0, state.t - (e.shiftKey ? 1 : 1 / FPS)); draw(); }
      else if (k === "ArrowRight") { state.t = Math.min(total, state.t + (e.shiftKey ? 1 : 1 / FPS)); draw(); }
      else if (k === "Home") { state.t = 0; draw(); }
      else if (k === "End") { state.t = total; draw(); }
      else if (k === "[" || k === "]") {
        var i = S.shots.indexOf(shotAt(state.t)); i = Math.min(Math.max(i + (k === "]" ? 1 : -1), 0), S.shots.length - 1); state.t = S.shots[i].t0; draw();
      }
      else if (k === "o" || k === "O") { state.proj = projOf(shotAt(state.t)) === "ortho" ? "persp" : "ortho"; draw(); }
      else if (k === "s" || k === "S") { state.stills = !state.stills; draw(); }
      else if (k === "g" || k === "G") { state.guides = !state.guides; $("guides").style.display = state.guides ? "" : "none"; }
    });
    window.__previzRedraw = draw;
  }
  function toggle() {
    state.playing = !state.playing; $("play").textContent = state.playing ? "Pause" : "Play"; state.last = performance.now();
    if (state.playing) requestAnimationFrame(tick);
  }
  function tick(now) {
    if (!state.playing) return;
    state.t += (now - state.last) / 1000; state.last = now;
    if (state.t >= total) state.t = 0;
    draw();
    requestAnimationFrame(tick);
  }
  function draw() {
    var r = frame(state.t);
    $("scrub").value = state.t;
    $("time").textContent = state.t.toFixed(2) + " / " + total.toFixed(2) + " s";
    $("proj").textContent = r.proj + (state.proj ? " (viewing)" : "");
    var chips = $("chips").children;
    for (var i = 0; i < chips.length; i++) chips[i].classList.toggle("on", S.shots[i] === r.shot);
    $("info").textContent = "shot " + r.shot.id + (r.shot.beat ? " (" + r.shot.beat + ")" : "") + "  " + r.shot.t0.toFixed(1) + "-" + (r.shot.t0 + r.shot.dur).toFixed(1) + "s  " + (r.shot.framing || "") +
      "\ncamera " + modeOf(r.shot) + "  cx " + r.cam[0].toFixed(3) + "  cy " + r.cam[1].toFixed(3) + "  w " + r.cam[2].toFixed(3);
  }

  try {
    if (STRIP) {
      drawStrip();
    } else {
      makeRenderer();
      $("view").replaceWith(renderer.domElement);
      renderer.domElement.id = "view";
      ui(); fit(); draw();
    }
  } catch (e) { fail(e); }
})();
