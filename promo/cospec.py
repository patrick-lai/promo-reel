"""Co-spec: at most five questions, asked only where an answer saves a full re-render.

A thin prompt can be drafted without asking anything (draft, then iterate). These are the few decisions that are expensive to
change after the first draft because they invalidate generated plates, the type cards, the panel framing or the end card:

    world       the backdrop plates' palette / time of day / mood    (re-generates every plate and re-grades the cut)
    features    the 2-3 features the demo proves, in the person's words   (the demo cards, which still goes where, the capture list)
    cta         the end card: product name, one verb + one real place, or name only   (the end card and the last VO line)
    must_keep   claims that must stay on screen, each with what proves it, and anything never to say   (every card and VO line)
    still_roles which supplied still is a phone / terminal / desktop   (floating vs device framing of those shots)

A question is skipped when the prompt already answers it (a `features:` line, a night -> dawn word for the plates, a `cta:` line)
or when it does not apply (no stills = no still_roles). Answers are stored under `plan.cospec.answers` and are the only text, besides
the prompt, the plan may put on screen. `promo cospec --answer key=value` writes them and re-plans.
"""
from __future__ import annotations

import re

MAX_QUESTIONS = 5

QUESTIONS = (
    dict(key="world",
         question="What world should the backdrop plates live in (time of day, palette, mood)? No product imagery, no text, no people.",
         saves="regenerating every plate and re-grading the whole cut",
         default="the prompt's own mood words if it has any, else a neutral cool-to-warm gradient",
         example="night sky turning to dawn, deep blue to amber"),
    dict(key="features",
         question="Which 2-3 features should the demo prove, one short line each (your words, separated by ;)?",
         saves="re-cutting the demo, its cards and which still sits on which shot",
         default="no feature cards: the demo shows the supplied stills in order, with a placeholder card waiting for your words",
         example="<feature one>; <feature two>; <feature three>"),
    dict(key="cta",
         question="End card: the exact words (product name, one verb, one real destination), or 'name only' if there is no place to send people yet?",
         saves="re-rendering the end card and the last voice line",
         default="the end card shows a placeholder card; nothing, including any URL, is invented",
         example="<Product name>. <verb> <real place>"),
    dict(key="must_keep",
         question="Any claims that must stay on screen (each with what in the footage proves it), and anything we must never say? Use 'claim | proof' lines.",
         saves="rewriting cards and voice lines after a review catches a missing or false claim",
         default="no claims beyond the words of the prompt; a claim without proof never becomes a card",
         example="<claim> | <which still shows it>"),
    dict(key="still_roles",
         question="For each supplied still: is it the desktop app, a phone, or a terminal / other context? (id=role, separated by ;)",
         saves="re-framing those shots from floating panel to device (or back)",
         default="read from each still's shape: portrait or square = device, landscape = floating panel",
         example="<still-id>=phone; <still-id>=desktop"),
)


def _has_label(prompt, *keys):
    return any(re.search(rf"(?im)^[ \t]*{k}\s*:\s*\S", prompt or "") for k in keys)


def _world_in_prompt(prompt):
    from . import designed as D
    return D.world(prompt, {})[2] == "prompt"


def _stills_ambiguous(stills):
    return any(s.get("orientation") in ("square", "portrait", "unknown") for s in stills)


def open_questions(prompt, stills=None, answers=None, limit=MAX_QUESTIONS):
    """The questions still worth asking, most expensive-to-redo first, at most `limit` (never more than five)."""
    answers = answers or {}
    stills = stills or []
    skip = set(k for k, v in answers.items() if v not in (None, "", []))
    if _has_label(prompt, "features?"):
        skip.add("features")
    if _has_label(prompt, "cta", "ask", "call to action"):
        skip.add("cta")
    if _world_in_prompt(prompt):
        skip.add("world")
    if not stills or not _stills_ambiguous(stills):
        skip.add("still_roles")
    res = [dict(q) for q in QUESTIONS if q["key"] not in skip]
    return res[:min(limit, MAX_QUESTIONS)]


def parse_pairs(pairs):
    """['key=value', ...] -> {key: value}. A key that is not a question is refused (it would never reach the plan)."""
    known = {q["key"] for q in QUESTIONS} | {"must_not"}
    out = {}
    for p in pairs or []:
        k, sep, v = str(p).partition("=")
        k = k.strip()
        if not sep or k not in known:
            raise ValueError(f"unknown answer {p!r}; keys: {', '.join(sorted(known))}")
        out[k] = v.strip()
    return out


def apply_roles(stills, answers):
    """still_roles answers override the shape-based orientation (phone -> portrait, desktop -> landscape, terminal -> landscape)."""
    roles = {}
    for item in re.split(r"[;\n]", str((answers or {}).get("still_roles") or "")):
        k, sep, v = item.partition("=")
        if sep:
            roles[k.strip()] = v.strip().lower()
    for s in stills:
        r = roles.get(s["id"])
        if r in ("phone", "mobile"):
            s["orientation"], s["role"] = "portrait", "phone"
        elif r in ("desktop", "app", "terminal", "other", "context"):
            s["orientation"] = "landscape" if s["orientation"] != "landscape" else s["orientation"]
            s["role"] = r
    return stills


def block(prompt, stills, answers):
    """`plan.cospec`: what was asked, what is answered, what is still open, and what happens if it stays open."""
    open_q = open_questions(prompt, stills, answers)
    return dict(
        max_questions=MAX_QUESTIONS,
        answers={k: v for k, v in (answers or {}).items() if v not in (None, "")},
        open=[dict(key=q["key"], question=q["question"], saves=q["saves"], if_unanswered=q["default"]) for q in open_q],
        note="Optional. Draft first, iterate on feedback; answer these only when a wrong guess would cost a full re-render.",
    )
