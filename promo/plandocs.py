"""Planning documents: everything a production needs besides the storyboard, as markdown the agent adds on request and the person reads in the Stage.

    flow/docs/<id>.md          the document (any length; `<!-- page -->` or `<!-- page: Title -->` starts a new page, else the reader paginates by headings/length)
    flow.json  docs: [{id, title, kind, story, summary, file, created, updated, source}]

A document is not a gate: nothing blocks on it. It is the agent's way to answer "give me the full script", "a shot list", "an edit plan", "everything I need to
direct this" with real content in the UI. `kind` picks the icon and the group in the Plan tab. `new_from_template` writes a starter built from the REAL board and
asset plan (so a shot list or an audio plan is never invented), which the agent then refines with `promo flow doc add --force` / `doc append`.

    script        the full script (voice-over, on-screen text, action)           shotlist     one row per shot: time, picture, camera, caption, voice, proof
    treatment     the pitch: audience, idea, tone, structure                     direction    director's notes: look, pace, performance, do/don't
    edit          edit plan: cut list on the timeline, transitions, grade        audio        music cues, voice lines, sound effects, mix targets
    capture       capture checklist: what to record, how, in what state          schedule     who does what, by when
    deliverables  formats, loudness, files, who approves                         risks        claims and the evidence behind each, open risks
    research      references and what was learned from them                      review       review notes: what changed since the last draft
    notes         anything else
"""
from __future__ import annotations

import re

MAX_BYTES = 5 * 1024 * 1024
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
PAGE_RE = re.compile(r"^\s*<!--\s*page(?:\s*:\s*(.*?))?\s*-->\s*$", re.M)

# kind -> (label, group); the order here is the order of the Plan tab's groups
KINDS = {
    "script": ("Script", "Script"), "treatment": ("Treatment", "Script"),
    "shotlist": ("Shot list", "Direction"), "direction": ("Director's notes", "Direction"),
    "edit": ("Edit plan", "Edit"),
    "audio": ("Audio plan", "Audio"),
    "capture": ("Capture checklist", "Capture"), "schedule": ("Schedule", "Capture"),
    "deliverables": ("Deliverables", "Delivery"), "risks": ("Claims & risks", "Delivery"),
    "research": ("Research", "Notes"), "review": ("Review notes", "Notes"), "notes": ("Notes", "Notes"),
}
GROUPS = ["Script", "Direction", "Edit", "Audio", "Capture", "Delivery", "Notes"]


class DocError(Exception):
    pass


def valid_id(x):
    return bool(ID_RE.match(x or ""))


def slug(x):
    return re.sub(r"[^a-z0-9]+", "-", (x or "").lower()).strip("-")[:48] or "doc"


def check_text(text):
    if not text or not text.strip():
        raise DocError("the document is empty")
    if len(text.encode()) > MAX_BYTES:
        raise DocError(f"document is over {MAX_BYTES // 1024 // 1024} MB: split it into several documents (`doc add` once per part)")
    return text


def words(text):
    return len(re.findall(r"\S*\w\S*", text or ""))


def headings(text, limit=80):
    """[{level, title}] of the markdown headings outside code fences."""
    out, fence = [], False
    for line in (text or "").splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            continue
        m = None if fence else re.match(r"^(#{1,4})\s+(.*?)(?:\s+#+)?\s*$", line)
        if m:
            out.append(dict(level=len(m.group(1)), title=re.sub(r"[*_`]", "", m.group(2))[:90]))
            if len(out) >= limit:
                break
    return out


def preview(text, n=240):
    """The first prose of the document, markdown stripped, for the library card."""
    keep = []
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "|", "```", "<!--", "---", "- [")):
            continue
        keep.append(re.sub(r"[*_`>]|^\s*[-*]\s+|^\d+[.)]\s+", "", s))
        if sum(len(k) for k in keep) > n:
            break
    out = " ".join(keep)
    return out if len(out) <= n else out[:n - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


# ---- templates built from the real flow ----------------------------------------------------------------------------------------------------
def _t(s):
    return f"{int(s // 60)}:{int(s % 60):02d}" if s >= 60 else f"{s:g} s"


def _cell(x):
    return str(x or "").replace("|", "/").replace("\n", " ").strip() or "-"


def _scenes(boards, story=None):
    for sid, b, _ in boards:
        if story and sid != story:
            continue
        for s in b.get("scenes") or []:
            yield sid, b, s


def _title(boards, story):
    for sid, b, _ in boards:
        if not story or sid == story:
            return b.get("title") or sid
    return "the video"


def _shotlist(ctx):
    rows = ["| # | Time | Beat | What the viewer sees | Source | Camera | Caption | Voice | Proof |", "|---|---|---|---|---|---|---|---|---|"]
    for sid, b, s in _scenes(ctx["boards"], ctx["story"]):
        t = s.get("t") or [0, 0]
        rows.append(f"| {_cell(s.get('id'))} | {t[0]:g}–{t[1]:g} s | {_cell(s.get('beat'))} | {_cell(s.get('action'))} | {_cell(s.get('source') or 'other')} | "
                    f"{_cell(s.get('camera'))} | {_cell(s.get('caption'))} | {_cell(s.get('vo'))} | {_cell(s.get('proof'))} |")
    return f"# Shot list: {_title(ctx['boards'], ctx['story'])}\n\nOne row per scene of the storyboard. Source `real` is a recording of the product; `generated` is a plate with no UI.\n\n" + "\n".join(rows) + "\n"


def _edit(ctx):
    L = [f"# Edit plan: {_title(ctx['boards'], ctx['story'])}", "", "The cut list in timeline order. Every cut lands on a beat of the music; hold each caption for at least 2 s.", "",
         "| In | Out | Length | Scene | Cut in from | Move | Caption on screen |", "|---|---|---|---|---|---|---|"]
    prev = None
    for sid, b, s in _scenes(ctx["boards"], ctx["story"]):
        t = s.get("t") or [0, 0]
        L.append(f"| {t[0]:g} | {t[1]:g} | {t[1] - t[0]:g} s | {_cell(s.get('id'))} {_cell(s.get('beat'))} | {_cell(prev) if prev else 'start'} | {_cell(s.get('camera'))} | {_cell(s.get('caption'))} |")
        prev = f"scene {s.get('id')}"
    L += ["", "## Rhythm", "", "- Cut on the beat grid: *(BPM, beats per bar, which bars carry a cut)*", "- Where the picture holds still, and why", "", "## Transitions", "",
          "- *(list each non-hard cut: where, what, how long)*", "", "## Colour and finish", "", "- Real UI pixels are never graded or retouched; any grade sits on backdrops only.", "- Text: font, size, safe zone", "",
          "## Open edit questions", "", "- [ ] *(anything the person should decide)*"]
    return "\n".join(L) + "\n"


def _audio(ctx):
    L = [f"# Audio plan: {_title(ctx['boards'], ctx['story'])}", "", "## Voice-over lines", "", "| Scene | At | Line | Proof |", "|---|---|---|---|"]
    n = 0
    for sid, b, s in _scenes(ctx["boards"], ctx["story"]):
        if s.get("vo"):
            n += 1
            L.append(f"| {_cell(s.get('id'))} | {(s.get('t') or [0])[0]:g} s | {_cell(s.get('vo'))} | {_cell(s.get('proof'))} |")
    if not n:
        L.append("| - | - | no voice-over in the storyboard yet | - |")
    L += ["", "## Sound design", "", "| Scene | At | Sound |", "|---|---|---|"]
    for sid, b, s in _scenes(ctx["boards"], ctx["story"]):
        if s.get("sound"):
            L.append(f"| {_cell(s.get('id'))} | {(s.get('t') or [0])[0]:g} s | {_cell(s.get('sound'))} |")
    L += ["", "## Planned audio assets", ""]
    music = [a for a in ctx["assets"] if a.get("kind") in ("music", "voice", "sfx")]
    for a in music:
        L.append(f"- **{a.get('label') or a['id']}** ({a['kind']}, {a.get('source', '')}): {a.get('how', '')}" + (f" Licence: {a['licence']}." if a.get("licence") else ""))
    if not music:
        L.append("- *(no audio assets planned yet)*")
    L += ["", "## Mix targets", "", "- Web master: -14 LUFS, true peak below -1 dB. Social master: about -9 LUFS.", "- Voice sits clear of the music: duck the music under every line.",
          "- Every music track, voice and effect has a licence and a source URL in the asset list."]
    return "\n".join(L) + "\n"


def _capture(ctx):
    L = [f"# Capture checklist: {_title(ctx['boards'], ctx['story'])}", "", "Real footage only. Record at 2x pixel density (a 3840x2160 capture), 60 fps, notifications off, clean data, cursor hidden unless the shot is about a click. "
         "Start each take 1 s before the action and hold 2 s after it.", ""]
    rec = [a for a in ctx["assets"] if a.get("kind") in ("recording", "screenshot", "video", "image")]
    for a in rec:
        L.append(f"- [{'x' if a.get('state') == 'ready' else ' '}] **{a.get('label') or a['id']}** ({a['kind']}, {a.get('source', '')}), scenes {', '.join(a.get('scenes') or []) or '-'}: {a.get('how', '')}")
    if not rec:
        L.append("- [ ] *(no recordings or screenshots planned yet: add them to the asset plan)*")
    L += ["", "## Before every take", "", "- [ ] Right project open, no test data, no personal data, no keys or emails on screen", "- [ ] Notifications off, clock and theme the same across takes",
          "- [ ] Window sized for a 16:9 capture at 2x density", "", "## After every take", "", "- [ ] Register it with `promo footage add` (commit SHA, URL params, framing)"]
    return "\n".join(L) + "\n"


def _risks(ctx):
    L = [f"# Claims and risks: {_title(ctx['boards'], ctx['story'])}", "", "Every caption and voice line may state only what the footage shows or what the product verifiably does today.", "",
         "| Scene | Says | Evidence | Status |", "|---|---|---|---|"]
    n = 0
    for sid, b, s in _scenes(ctx["boards"], ctx["story"]):
        for what in (s.get("caption"), s.get("vo")):
            if what:
                n += 1
                L.append(f"| {_cell(s.get('id'))} | {_cell(what)} | {_cell(s.get('proof'))} | {'backed' if s.get('proof') else 'NEEDS EVIDENCE'} |")
    if not n:
        L.append("| - | no captions or voice lines yet | - | - |")
    L += ["", "## Open risks", "", "- [ ] Anything on screen that must not appear (cost counters, wrong project, personal data)", "- [ ] Licences for every music, voice and effect asset",
          "- [ ] Nothing published until the person approves"]
    return "\n".join(L) + "\n"


def _deliverables(ctx):
    return ("# Deliverables\n\n| File | Spec | For |\n|---|---|---|\n| 1080 master | 1920x1080, 30 fps, -14 LUFS, true peak below -1 dB | web |\n"
            "| 1080 social | 1920x1080, about -9 LUFS | social platforms |\n| 2160 master | 3840x2160, same spec as 1080 | archive, large screens |\n"
            "| Contact sheet, check report, edit list | PDF/PNG, JSON, markdown | review |\n| Licence and credit lines | text | description and end card |\n\n"
            "## Cutdowns\n\n- *(lengths and aspect ratios the person wants beyond the 60 s 16:9 master)*\n\n## Approval\n\n- [ ] A person approves every draft and the final. Agents never publish.\n")


def _treatment(ctx):
    return (f"# Treatment: {_title(ctx['boards'], ctx['story'])}\n\n> {ctx['intent']}\n\n## The one idea\n\n*(one sentence)*\n\n## Audience and where they watch\n\n*(who, which platform, sound on or off)*\n\n"
            f"## Tone and style\n\n{ctx['style'] or '*(style the person chose)*'}\n\n## Structure\n\n1. Hook\n2. Proof, in the real product\n3. Payoff\n4. End card\n\n## Must show\n\n- *(features)*\n\n## Must not claim\n\n- *(list)*\n")


def _direction(ctx):
    return ("# Director's notes\n\n## Look\n\n*(light, colour, frame, how much of the product fills the frame)*\n\n## Pace\n\n*(where the film breathes and where it speeds up)*\n\n"
            "## Camera\n\n*(push-ins on real UI, how tight, how slow)*\n\n## Do\n\n- *(what every shot should have)*\n\n## Do not\n\n- Edit the app's UI in post, or add anything that is not on screen.\n")


def _schedule(ctx):
    return ("# Schedule\n\n| Step | Who | By | Status |\n|---|---|---|---|\n| Approve the script | the person | - | open |\n| Approve the storyboard | the person | - | open |\n"
            "| Record the real footage | the agent | - | open |\n| Build the first draft | the agent | - | open |\n| Review rounds (up to 5) | both | - | open |\n| Final and delivery | the agent | - | open |\n")


def _research(ctx):
    return "# Research\n\n## References studied\n\n- *(link, what it does well, what to borrow)*\n\n## Examples of this kind of video done well\n\n- *(link, why)*\n"


def _review(ctx):
    return "# Review notes\n\n## Round *(n)*\n\n**Feedback, verbatim:** *(the person's words)*\n\n**Changed:**\n\n- *(what changed in this draft)*\n\n**Not changed, and why:**\n\n- *(anything skipped)*\n"


def _script(ctx):
    L = [f"# Script: {_title(ctx['boards'], ctx['story'])}", "", f"> {ctx['intent']}", ""]
    for sid, b, s in _scenes(ctx["boards"], ctx["story"]):
        t = s.get("t") or [0, 0]
        L += [f"## {s.get('id')}. {s.get('beat', '')}  ({t[0]:g}–{t[1]:g} s)", "", f"**Picture:** {s.get('action', '')}"]
        if s.get("caption"):
            L.append(f"**On screen:** {s['caption']}")
        if s.get("vo"):
            L.append(f"**Voice:** {s['vo']}")
        if s.get("sound"):
            L.append(f"**Sound:** {s['sound']}")
        L.append("")
    return "\n".join(L)


TEMPLATES = dict(script=_script, shotlist=_shotlist, edit=_edit, audio=_audio, capture=_capture, risks=_risks, deliverables=_deliverables, treatment=_treatment,
                 direction=_direction, schedule=_schedule, research=_research, review=_review)
# the pack `promo flow plan pack` writes: everything generic to direct, storyboard, workshop and edit a video
STORY_KINDS = {"treatment", "shotlist", "edit", "audio", "capture", "risks", "script"}      # built per story; the rest describe the whole job
PACK = ["treatment", "direction", "shotlist", "edit", "audio", "capture", "risks", "deliverables", "schedule"]


def render_template(kind, ctx):
    if kind not in TEMPLATES:
        raise DocError(f"no template for `{kind}`: one of {', '.join(sorted(TEMPLATES))}")
    return TEMPLATES[kind](ctx)
