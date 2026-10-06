"use strict";
/* Pure derivations for the promo-projects mod (no DOM, no bridge): search, buckets, highlight ranges and relative times.
   Loaded as a classic script (window.PP) and by `node --test` (module.exports). */
(function (root) {
  const arr = (x) => (Array.isArray(x) ? x : []);
  const norm = (s) => String(s == null ? "" : s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const terms = (q) => norm(q).split(/[\s,]+/).filter(Boolean);

  /* Where a project stands, from the person's side: their turn, the agent's, delivered, or unreadable. */
  function bucket(p) {
    if (p.error) return "error";
    if (p.badge === "done") return "done";
    if (p.badge === "waiting" || p.badge === "attention") return "turn";
    return "progress";
  }
  function counts(projects) {
    const c = { all: 0, turn: 0, progress: 0, done: 0 };
    for (const p of arr(projects)) { c.all++; const b = bucket(p); if (b in c) c[b]++; }
    return c;
  }

  /* Field weights: a hit in the name or title is worth more than one in the brief, so "jev" puts the JEV promo above a project that only mentions it. */
  const FIELDS = [["title", 4], ["name", 4], ["picked", 3], ["stage_label", 2], ["style", 1], ["status", 1], ["question", 1], ["intent", 1]];
  function score(p, ts) {
    let total = 0;
    for (const t of ts) {
      let best = 0;
      for (const [k, w] of FIELDS) {
        const v = norm(Array.isArray(p[k]) ? p[k].join(" ") : p[k]);
        const at = v.indexOf(t);
        if (at < 0) continue;
        const word = at === 0 || /[^a-z0-9]/.test(v[at - 1]);
        best = Math.max(best, w * (word ? 2 : 1));
      }
      if (!best) return 0;
      total += best;
    }
    return total;
  }

  /* The list to show: the bucket filter, then every search word must match somewhere; best match first, the given order (most recent first) breaks ties. */
  function search(projects, q, filter) {
    const ts = terms(q);
    const rows = arr(projects).map((p, i) => ({ p, i, s: ts.length ? score(p, ts) : 1 }))
      .filter((r) => r.s > 0 && (!filter || filter === "all" || bucket(r.p) === filter));
    rows.sort((a, b) => b.s - a.s || a.i - b.i);
    return rows.map((r) => r.p);
  }

  /* [[text, isHit], ...] for highlighting the search words in a line. Matching runs on the normalised text, which keeps the length of plain ASCII and precomposed accents. */
  function marks(text, q) {
    text = String(text == null ? "" : text);
    const ts = terms(q);
    const n = norm(text);
    if (!ts.length || n.length !== text.length) return [[text, false]];
    const hit = new Array(text.length).fill(false);
    for (const t of ts) for (let at = n.indexOf(t); at >= 0; at = n.indexOf(t, at + 1)) hit.fill(true, at, at + t.length);
    const out = [];
    for (let i = 0; i < text.length; i++) {
      if (out.length && out[out.length - 1][1] === hit[i]) out[out.length - 1][0] += text[i];
      else out.push([text[i], hit[i]]);
    }
    return out;
  }

  const MONTH = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  /* "just now", "5 min ago", "3 h ago", "yesterday", "4 days ago", else "6 Oct" (with the year when it is not this year). */
  function ago(iso, nowMs) {
    const t = Date.parse(iso);
    if (!iso || Number.isNaN(t)) return "";
    const s = Math.max(0, (nowMs - t) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return Math.floor(s / 60) + " min ago";
    if (s < 86400) return Math.floor(s / 3600) + " h ago";
    const d = new Date(t), now = new Date(nowMs);
    const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(d.getFullYear(), d.getMonth(), d.getDate())) / 86400000);
    if (days <= 1) return "yesterday";
    if (days < 7) return days + " days ago";
    return d.getDate() + " " + MONTH[d.getMonth()] + (d.getFullYear() === now.getFullYear() ? "" : " " + d.getFullYear());
  }
  function day(iso, nowMs) {
    const t = Date.parse(iso);
    if (!iso || Number.isNaN(t)) return "";
    const d = new Date(t);
    return d.getDate() + " " + MONTH[d.getMonth()] + (d.getFullYear() === new Date(nowMs).getFullYear() ? "" : " " + d.getFullYear());
  }

  const api = { bucket, counts, search, marks, ago, day };
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PP = api;
})(typeof window !== "undefined" ? window : globalThis);
