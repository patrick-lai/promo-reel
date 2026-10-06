"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const L = require("../logic.js");

const P = [
  { id: "1", name: "acme-night", title: "Tell it at night", intent: "A promo that mentions JEV once", badge: "working", stage_label: "Storyboard" },
  { id: "2", name: "commission-ai-jev", title: "One decision at a time", intent: "CommissionAI JEV promo", badge: "done", stage_label: "Final" },
  { id: "3", name: "café-launch", title: "Morning launch", intent: "Launch film", badge: "waiting", stage_label: "Pick stories", picked: ["Wake up to merged PRs"] },
  { id: "4", name: "broken", error: "This project's flow could not be read." },
];
const ids = (xs) => xs.map((p) => p.id);

test("a name or title hit outranks a brief that only mentions the word, and every word must match", () => {
  assert.deepEqual(ids(L.search(P, "jev")), ["2", "1"]);
  assert.deepEqual(ids(L.search(P, "jev night")), ["1"]);
  assert.deepEqual(ids(L.search(P, "merged")), ["3"]);
  assert.deepEqual(ids(L.search(P, "cafe")), ["3"]);
  assert.deepEqual(ids(L.search(P, "")), ["1", "2", "3", "4"]);
});

test("filters split the list by whose turn it is, and the counts match the filters", () => {
  assert.deepEqual(ids(L.search(P, "", "turn")), ["3"]);
  assert.deepEqual(ids(L.search(P, "", "done")), ["2"]);
  assert.deepEqual(ids(L.search(P, "", "progress")), ["1"]);
  assert.deepEqual(L.counts(P), { all: 4, turn: 1, progress: 1, done: 1 });
});

test("marks highlight every search word, accents included", () => {
  assert.deepEqual(L.marks("One decision at a time", "time one"), [["One", true], [" decision at a ", false], ["time", true]]);
  assert.deepEqual(L.marks("café-launch", "cafe"), [["café", true], ["-launch", false]]);
  assert.deepEqual(L.marks("abc", ""), [["abc", false]]);
});

test("relative times (midday UTC, so the calendar days are the same in every time zone)", () => {
  const now = Date.parse("2026-10-06T12:00:00Z");
  assert.equal(L.ago("2026-10-06T11:59:30Z", now), "just now");
  assert.equal(L.ago("2026-10-06T11:15:00Z", now), "45 min ago");
  assert.equal(L.ago("2026-10-06T06:00:00Z", now), "6 h ago");
  assert.equal(L.ago("2026-10-02T12:00:00Z", now), "4 days ago");
  assert.equal(L.ago("2025-12-24T12:00:00Z", now), "24 Dec 2025");
  assert.equal(L.ago(null, now), "");
});
