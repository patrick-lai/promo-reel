"""The Stage's timeline editor, the backend: a short edit language, applied to promo.yaml as text so its comments survive, then an incremental
rebuild that becomes the next draft.

    promo flow edit view [--json]                          the editor's state (`edit` in the snapshot): shots, captions, VO, music, SFX, freshness
    promo flow edit timeline                               the timeline as text: every shot, caption, voice line, sound, the music, what is built
    promo flow edit look (--at S | --shot ID | --from S --to S) [--frames N]   a PNG sheet of frames as they are now (read it to see)
    promo flow edit listen (--shot ID | --from S --to S) [--stem mix|music|vo|sfx]   a WAV excerpt + loudness, an envelope, voice lines and sounds in it
    promo flow edit preview (--shot ID | --from S --to S) [--note T]   build only that span's shots and the sound, cut it with the new mix: a quick clip
    promo flow edit apply --dry-run (--file F|- | "OPS")   the promo.yaml diff and the build steps that would run; nothing is written
    promo flow edit apply  (--file F|- | "OPS") --by NAME   apply edits to promo.yaml (undo: `promo flow restore --undo K --by NAME`)
    promo flow edit render (--file F|- | "OPS") --by NAME [--note T] [--scale S]
                                                          apply, `promo build` (only what changed), `promo check`, keep the file as flow/drafts/dN.mp4, add the draft
    promo flow edit import FILE --kind music|sfx|voice|video --licence T --source T --by NAME [--id ID]
    promo flow edit bin [--open NAME | --close NAME]      the bin of assets; --open attaches an earlier project's playable media to the next publish
    promo flow edit suggest (--file F|- | "OPS") --note T  the agent's answer to "try 3 music options": a card the person previews and keeps
    promo flow edit keep ID --by NAME                      the person kept suggestion ID (its edits are in their pending edits)
    promo flow edit replay --by NAME                       a GENERATED promo.yaml was regenerated: apply every logged edit again

The edit language, one op per line (or `;` between ops), parsed with shlex:
    swap 07 rec-w-ask [t_in=1.2]          shot source (a footage id); `project:clip` copies an earlier project's manifest entry (same sha256)
    trim 07 end=34 | trim 07 start=30     move the cut after (before) shot 07 to that beat; trimming the last shot changes the film's length
    move 07 before=03 | move 07 after=03  reorder; beats are rewritten, lengths kept
    split 07 at=4                         4 beats into the shot: 07 and 07b (the source runs on: t_in advances)
    delete 07                             ripple: later shots move up, the timeline and the music get shorter
    caption 07 "Tell it what to ship."    the shot's caption ("" removes it)
    music music-eternal-hope [offset=S]   another track (or `project:asset`, its assets.yaml entry copied with licence), laid from S seconds of the file
    bus music -3                          mix.bus_db
    vo a3 at=2.0 [shot=08] | vo a3 mute | vo a3 unmute | vo a3 db=-5 | vo a3 take=PATH|project:PATH
    sfx 07 add hit at=0.5 [db=-5] | sfx 07 rm 1 | sfx 07 set 1 at=0.8 [db=-3]
    grade 01 contrast=1.1 saturation=0.9 temperature=5600 [brightness= gamma= vignette=] | grade 01 off      plates only (`ui: false`): rule 2
    fade 23 in=0.5 out=1.5 | fade 23 off  the picture from / to black at the shot's edges
    speed 07 1.5                          how fast the source plays (shots with footage)
    fx music radio [amount=0.6] | fx vo tape | fx vo:a3 telephone | fx mix vintage | fx music off   character effects (promo/audiofx.py)
    gain music from=24 to=32 db=-6 [ramp=0.3] | gain music clear      a level change of the music over beats
    import PATH kind=music|sfx|voice|video licence="..." source="..." [id=ID]

Rules 1-4 hold: a swap only takes footage from a manifest (real captures, or a generated plate that stays on a `ui: false` shot, which
`promo check` gates), nothing edits the app's pixels, captions are the person's words (the next round checks them), and every imported or copied
audio file carries a licence and a source. The same ops run in the mod (`PF.editApply` in mods/promo-flow/logic.js) for the instant preview;
tests/edit-cases.json keeps the two the same.
"""
from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

import yaml

from . import flow as F
from . import versions as VR

EDIT_STAGES = ("drafts", "review", "final")
OPS = ("swap", "trim", "move", "split", "delete", "caption", "music", "bus", "vo", "sfx", "grade", "fade", "speed", "fx", "gain", "import")
GRADE_KEYS = ("brightness", "contrast", "saturation", "gamma", "temperature", "vignette")       # ffmpeg eq / colortemperature / vignette
GRADE_RANGE = dict(brightness=(-0.5, 0.5), contrast=(0.5, 2.0), saturation=(0.0, 2.5), gamma=(0.5, 2.0), temperature=(2500, 10000), vignette=(0.0, 1.0))
FX_PRESETS = ("radio", "tape", "vintage", "telephone", "vinyl", "crackle", "none")
BUSES = ("music", "sfx", "vo", "amb")
IMPORT_KINDS = ("music", "sfx", "voice", "video")
GENERATED_RE = re.compile(r"GENERATED by\s+(\S+)")
SPEC_KEYS = ("timeline", "output", "music", "vo", "sfx", "mix", "shots")     # the part of promo.yaml the Stage's preview edits (PF.editApply)
FILE_LIMIT = 190             # the host keeps at most 200 `$file` objects per state; the editor's media give way first
PEAKS = 400
THUMBS = 3
OWN = "My own recording"     # the licence of a file the person recorded themselves; their name is added


class EditError(F.FlowError):
    pass


def now():
    return F.now()


def edir(pd):
    return os.path.join(F.fdir(pd), "edit")


def _spec_path(pd):
    return os.path.join(pd, "promo.yaml")


# ---------------------------------------------------------------- the edit language
def _num(v, what, line):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise EditError(f"line {line}: {what} must be a number, not {v!r}")
    return int(x) if x.is_integer() else x


def _split(text):
    """[(line number, [tokens])]: one op per line, `;` (outside quotes) also ends an op."""
    out = []
    for n, raw in enumerate(str(text or "").splitlines(), 1):
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        lex = shlex.shlex(raw, posix=True, punctuation_chars=";")
        lex.whitespace_split = True
        lex.commenters = ""
        try:
            toks = list(lex)
        except ValueError as e:
            raise EditError(f"line {n}: {e} in {raw.strip()!r} (a quote is not closed)")
        cur = []
        for t in toks:
            if t and set(t) == {";"}:
                if cur:
                    out.append((n, cur))
                cur = []
            else:
                cur.append(t)
        if cur:
            out.append((n, cur))
    return out


def _kv(toks, n, allowed, flags=()):
    kv, fl = {}, []
    for t in toks:
        if "=" in t:
            k, v = t.split("=", 1)
            if k not in allowed:
                raise EditError(f"line {n}: unknown setting {k}= (use {', '.join(k + '=' for k in allowed)})")
            kv[k] = v
        elif t in flags:
            fl.append(t)
        else:
            raise EditError(f"line {n}: did not understand {t!r}")
    return kv, fl


def parse(text):
    """The ops of an edit text, validated at the boundary: a plain-language error names the line that is wrong."""
    ops = []
    for n, t in _split(text):
        op, a = t[0].lower(), t[1:]
        need = lambda k, what: (a[k] if len(a) > k else (_ for _ in ()).throw(EditError(f"line {n}: `{op}` needs {what}")))  # noqa: E731
        if op == "swap":
            sid, src = need(0, "a shot id"), need(1, "a footage id")
            kv, _ = _kv(a[2:], n, ("t_in",))
            o = dict(op=op, shot=sid, source=src)
            if "t_in" in kv:
                o["t_in"] = _num(kv["t_in"], "t_in", n)
        elif op == "trim":
            sid = need(0, "a shot id")
            kv, _ = _kv(a[1:], n, ("end", "start"))
            if len(kv) != 1:
                raise EditError(f"line {n}: trim takes one of end=BEAT or start=BEAT")
            k = next(iter(kv))
            o = dict(op=op, shot=sid, **{k: _num(kv[k], k, n)})
        elif op == "move":
            sid = need(0, "a shot id")
            kv, _ = _kv(a[1:], n, ("before", "after"))
            if len(kv) != 1:
                raise EditError(f"line {n}: move takes one of before=SHOT or after=SHOT")
            o = dict(op=op, shot=sid, **kv)
        elif op == "split":
            sid = need(0, "a shot id")
            kv, _ = _kv(a[1:], n, ("at",))
            if "at" not in kv:
                raise EditError(f"line {n}: split needs at=BEATS (how far into the shot)")
            o = dict(op=op, shot=sid, at=_num(kv["at"], "at", n))
        elif op == "delete":
            o = dict(op=op, shot=need(0, "a shot id"))
            if len(a) > 1:
                raise EditError(f"line {n}: delete takes only a shot id")
        elif op == "caption":
            sid = need(0, "a shot id")
            if len(a) != 2:
                raise EditError(f"line {n}: caption takes a shot id and the words in quotes, e.g. caption 07 \"Tell it what to ship.\"")
            o = dict(op=op, shot=sid, text=" ".join(a[1].split()))
        elif op == "music":
            o = dict(op=op, asset=need(0, "an asset id"))
            kv, _ = _kv(a[1:], n, ("offset",))
            if "offset" in kv:
                o["offset"] = _num(kv["offset"], "offset", n)
        elif op == "bus":
            b = need(0, "a bus (music, sfx, vo or amb)")
            if b not in BUSES:
                raise EditError(f"line {n}: bus is one of {', '.join(BUSES)}, not {b!r}")
            if len(a) != 2:
                raise EditError(f"line {n}: bus takes a bus and a level in dB, e.g. bus music -3")
            o = dict(op=op, bus=b, db=_num(a[1], "the level", n))
        elif op == "vo":
            lid = need(0, "a voice line id")
            kv, fl = _kv(a[1:], n, ("at", "shot", "db", "take"), ("mute", "unmute"))
            if not kv and not fl:
                raise EditError(f"line {n}: vo {lid} needs at=, shot=, db=, take=, mute or unmute")
            if "mute" in fl and "unmute" in fl:
                raise EditError(f"line {n}: mute or unmute, not both")
            o = dict(op=op, line=lid)
            for k in ("at", "db"):
                if k in kv:
                    o[k] = _num(kv[k], k, n)
            for k in ("shot", "take"):
                if k in kv:
                    o[k] = kv[k]
            if fl:
                o["mute"] = fl[0] == "mute"
        elif op == "sfx":
            sid, act = need(0, "a shot id"), need(1, "add, rm or set")
            if act == "add":
                kv, _ = _kv(a[3:], n, ("at", "db"))
                o = dict(op=op, shot=sid, act=act, sfx=need(2, "a sound name"), at=_num(kv.get("at", 0), "at", n))
                if "db" in kv:
                    o["db"] = _num(kv["db"], "db", n)
            elif act in ("rm", "set"):
                i = _num(need(2, "the number of the sound (1 = the first)"), "the sound number", n)
                if not isinstance(i, int) or i < 1:
                    raise EditError(f"line {n}: sounds are numbered from 1")
                kv, _ = _kv(a[3:], n, ("at", "db") if act == "set" else ())
                if act == "set" and not kv:
                    raise EditError(f"line {n}: sfx set needs at= or db=")
                o = dict(op=op, shot=sid, act=act, i=i, **{k: _num(v, k, n) for k, v in kv.items()})
            else:
                raise EditError(f"line {n}: sfx takes add, rm or set, not {act!r}")
        elif op == "grade":
            sid = need(0, "a shot id")
            if a[1:] == ["off"]:
                o = dict(op=op, shot=sid, off=True)
            else:
                kv, _ = _kv(a[1:], n, GRADE_KEYS)
                if not kv:
                    raise EditError(f"line {n}: grade needs one of {', '.join(k + '=' for k in GRADE_KEYS)}, or off")
                o = dict(op=op, shot=sid)
                for k, v in kv.items():
                    x = _num(v, k, n)
                    lo, hi = GRADE_RANGE[k]
                    if not lo <= x <= hi:
                        raise EditError(f"line {n}: {k} must be between {lo:g} and {hi:g}")
                    o[k] = x
        elif op == "fade":
            sid = need(0, "a shot id")
            if a[1:] == ["off"]:
                o = dict(op=op, shot=sid, off=True)
            else:
                kv, _ = _kv(a[1:], n, ("in", "out"))
                if not kv:
                    raise EditError(f"line {n}: fade needs in=SECONDS and/or out=SECONDS, or off")
                o = dict(op=op, shot=sid, **{k: _num(v, k, n) for k, v in kv.items()})
                if any(o[k] < 0 for k in kv):
                    raise EditError(f"line {n}: a fade cannot be negative")
        elif op == "speed":
            sid = need(0, "a shot id")
            if len(a) != 2:
                raise EditError(f"line {n}: speed takes a shot id and a factor, e.g. speed 07 1.5")
            x = _num(a[1], "the speed", n)
            if not 0.1 <= x <= 8:
                raise EditError(f"line {n}: speed must be between 0.1 and 8")
            o = dict(op=op, shot=sid, speed=x)
        elif op == "fx":
            tgt = need(0, "what it applies to: music, vo, vo:LINE or mix")
            if not (tgt in ("music", "vo", "mix") or tgt.startswith("vo:")):
                raise EditError(f"line {n}: fx applies to music, vo, vo:LINE or mix, not {tgt!r}")
            pre = need(1, "a preset (" + ", ".join(FX_PRESETS) + ") or off")
            if pre != "off" and pre not in FX_PRESETS:
                raise EditError(f"line {n}: fx preset is one of {', '.join(FX_PRESETS)} (or off), not {pre!r}")
            kv, _ = _kv(a[2:], n, ("amount",))
            o = dict(op=op, target=tgt, preset=pre)
            if "amount" in kv:
                o["amount"] = _num(kv["amount"], "amount", n)
                if not 0 <= o["amount"] <= 1:
                    raise EditError(f"line {n}: amount is between 0 and 1")
        elif op == "gain":
            if need(0, "music") != "music":
                raise EditError(f"line {n}: gain works on the music (gain music from=BEAT to=BEAT db=DB)")
            if a[1:] == ["clear"]:
                o = dict(op=op, clear=True)
            else:
                kv, _ = _kv(a[1:], n, ("from", "to", "db", "ramp"))
                if not {"from", "to", "db"} <= set(kv):
                    raise EditError(f"line {n}: gain music needs from=BEAT to=BEAT db=DB")
                o = dict(op=op, **{k: _num(v, k, n) for k, v in kv.items()})
                if o["to"] <= o["from"]:
                    raise EditError(f"line {n}: gain to= must be after from=")
        elif op == "import":
            path = need(0, "a file path")
            kv, _ = _kv(a[1:], n, ("kind", "licence", "source", "id"))
            if kv.get("kind") not in IMPORT_KINDS:
                raise EditError(f"line {n}: import needs kind= one of {', '.join(IMPORT_KINDS)}")
            for k in ("licence", "source"):
                if not (kv.get(k) or "").strip():
                    raise EditError(f"line {n}: import needs {k}=\"...\" (rule 4: every file carries a licence and where it came from; "
                                    f"\"{OWN}\" is fine for the person's own)")
            o = dict(op=op, path=path, **kv)
        else:
            raise EditError(f"line {n}: unknown edit {t[0]!r} (one of {', '.join(OPS)})")
        o["_n"] = n
        ops.append(o)
    if not ops:
        raise EditError("no edits: write one edit per line, e.g. `swap 07 rec-w-ask` or `music music-eternal-hope`")
    return ops


def _q(s):
    return s if re.fullmatch(r"[\w.:/@+-]+", str(s)) else '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def text_of(ops):
    """The ops back as edit text (the same serialisation as `PF.editText`)."""
    out = []
    for o in ops:
        x = o["op"]
        if x == "swap":
            out.append(f"swap {o['shot']} {o['source']}" + (f" t_in={o['t_in']}" if "t_in" in o else ""))
        elif x == "trim":
            out.append(f"trim {o['shot']} " + (f"end={o['end']}" if "end" in o else f"start={o['start']}"))
        elif x == "move":
            out.append(f"move {o['shot']} " + (f"before={o['before']}" if "before" in o else f"after={o['after']}"))
        elif x == "split":
            out.append(f"split {o['shot']} at={o['at']}")
        elif x == "delete":
            out.append(f"delete {o['shot']}")
        elif x == "caption":
            out.append(f'caption {o["shot"]} "' + o["text"].replace("\\", "\\\\").replace('"', '\\"') + '"')
        elif x == "music":
            out.append(f"music {o['asset']}" + (f" offset={o['offset']}" if "offset" in o else ""))
        elif x == "bus":
            out.append(f"bus {o['bus']} {o['db']}")
        elif x == "vo":
            parts = [f"{k}={_q(o[k])}" for k in ("at", "shot", "db", "take") if k in o] + (["mute" if o["mute"] else "unmute"] if "mute" in o else [])
            out.append(f"vo {o['line']} " + " ".join(parts))
        elif x == "sfx":
            if o["act"] == "add":
                out.append(f"sfx {o['shot']} add {o['sfx']} at={o['at']}" + (f" db={o['db']}" if "db" in o else ""))
            else:
                out.append(f"sfx {o['shot']} {o['act']} {o['i']}" + "".join(f" {k}={o[k]}" for k in ("at", "db") if k in o))
        elif x == "grade":
            out.append(f"grade {o['shot']} " + ("off" if o.get("off") else " ".join(f"{k}={o[k]}" for k in GRADE_KEYS if k in o)))
        elif x == "fade":
            out.append(f"fade {o['shot']} " + ("off" if o.get("off") else " ".join(f"{k}={o[k]}" for k in ("in", "out") if k in o)))
        elif x == "speed":
            out.append(f"speed {o['shot']} {o['speed']}")
        elif x == "fx":
            out.append(f"fx {o['target']} {o['preset']}" + (f" amount={o['amount']}" if "amount" in o else ""))
        elif x == "gain":
            out.append("gain music clear" if o.get("clear") else "gain music " + " ".join(f"{k}={o[k]}" for k in ("from", "to", "db", "ramp") if k in o))
        elif x == "import":
            out.append(f"import {_q(o['path'])} kind={o['kind']} licence={_q(o['licence'])} source={_q(o['source'])}" + (f" id={_q(o['id'])}" if o.get("id") else ""))
    return "\n".join(out)


# ---------------------------------------------------------------- the model: ops on the promo.yaml data (mirrored by PF.editApply)
def local_id(ref):
    """`project:id` (an earlier project's footage or asset) is copied in as `project-id`; a plain id is this project's."""
    if ":" not in str(ref):
        return str(ref)
    proj, rid = str(ref).split(":", 1)
    return rid if rid.startswith(proj + "-") else f"{proj}-{rid}"


def take_file(ref):
    """Where a voice take lands in the VO folder: `project:path/a3.wav` -> takes/project-a3.wav; a path of this project's VO folder stays."""
    if ":" not in str(ref):
        return str(ref)
    proj, rel = str(ref).split(":", 1)
    return f"takes/{proj}-{os.path.basename(rel)}"


def _n(x):
    x = round(float(x), 6)
    return int(x) if x.is_integer() else x


def _beats(s, bpb=4, off=0):
    if "beats" in s:
        return [float(s["beats"][0]), float(s["beats"][1])]
    return [s["bars"][0] * bpb + off, s["bars"][1] * bpb + off]


def _set_beats(s, b0, b1):
    s.pop("bars", None)
    s["beats"] = [_n(b0), _n(b1)]


def _find(shots, sid, n):
    i = next((k for k, s in enumerate(shots) if str(s.get("id")) == str(sid)), None)
    if i is None:
        raise EditError(f"line {n}: there is no shot {sid}")
    return i


def _vo_line(raw, lid, n):
    lines = (raw.get("vo") or {}).get("lines") or []
    for ln in lines:
        if str(ln.get("id", ln.get("shot"))) == str(lid):
            return ln
    raise EditError(f"line {n}: there is no voice line {lid}" + (f" (lines: {', '.join(str(x.get('id', x.get('shot'))) for x in lines)})" if lines else " (this video has no voice-over)"))


def _retime_ok(s, b0, b1, bpb, n):
    """retime.move_cut's refusals: explicit segs durations, a card that would outrun the shorter shot."""
    if s.get("segs") and any("dur" in g for g in s["segs"]):
        raise EditError(f"line {n}: shot {s['id']} has explicit segs durations, so its length cannot change here: ask the agent to re-time it")
    bars = (b1 - b0) / bpb
    for c in s.get("cards") or []:
        cb = c.get("bars")
        if cb and cb[1] != "end" and float(cb[1]) > bars + 1e-9:
            raise EditError(f"line {n}: shot {s['id']} card {c.get('text') or c.get('text_from')!r} runs to bar {cb[1]}, past the {bars:g}-bar shot")


def _rebeat(shots):
    cur = 0.0
    for s in shots:
        b0, b1 = _beats(s)
        _set_beats(s, cur, cur + (b1 - b0))
        cur += b1 - b0
    return cur


def _set_length(raw, beats, B):
    raw.setdefault("timeline", {})["beats"] = _n(beats)
    raw.setdefault("output", {})["duration"] = _n(round(beats * B, 3))
    m = raw.get("music")
    if m and isinstance(m.get("edit"), dict):
        e = m["edit"]
        e["segments"] = [[_n(t0), _n(k0), _n(min(k1, k0 + beats - t0))] for t0, k0, k1 in e.get("segments") or [] if t0 < beats]
        if e.get("silence_from_beat") is not None and e["silence_from_beat"] >= beats:
            e.pop("silence_from_beat")
        e["gains"] = [dict(g, beats=[_n(g["beats"][0]), _n(min(g["beats"][1], beats))]) for g in e.get("gains") or [] if g["beats"][0] < beats]


def _shift_items(items, key, cut, first):
    """Split a shot's timed items (overlays `t: [a, b]`, sfx `at`) at `cut` seconds: the first part keeps what starts before it, the second
    what is still on after it, moved to its own clock."""
    out = []
    for it in items or []:
        it = copy.deepcopy(it)
        if key == "t" and isinstance(it.get("t"), list) and len(it["t"]) == 2:
            a, b = float(it["t"][0]), float(it["t"][1])
            if first and a < cut:
                out.append(it)
            elif not first and b > cut:
                it["t"] = [_n(max(0.0, a - cut)), _n(b - cut)]
                out.append(it)
        elif key == "at" and "at" in it:
            if first == (float(it["at"]) < cut):
                if not first:
                    it["at"] = _n(round(float(it["at"]) - cut, 3))
                out.append(it)
        else:
            out.append(it)
    return out


def apply_ops(raw, ops, B, bpb=4):
    """The spec data after `ops` (a new dict) and {new shot id: the shot it was split from}. `B` is seconds per beat."""
    raw = copy.deepcopy(raw)
    origin = {}
    shots = raw.setdefault("shots", [])
    for o in ops:
        n, x = o.get("_n", "?"), o["op"]
        if x == "swap":
            s = shots[_find(shots, o["shot"], n)]
            if "source" not in s:
                raise EditError(f"line {n}: shot {o['shot']} ({s.get('type', 'clip')}) has no footage to swap")
            s["source"] = local_id(o["source"])
            if "t_in" in o:
                s["t_in"] = o["t_in"]
        elif x == "trim":
            i = _find(shots, o["shot"], n)
            if "start" in o:
                if i == 0:
                    raise EditError(f"line {n}: the first shot starts at beat 0")
                i, new = i - 1, float(o["start"])
            else:
                new = float(o["end"])
            a = shots[i]
            a0, a1 = _beats(a)
            if i == len(shots) - 1:
                if not new > a0:
                    raise EditError(f"line {n}: shot {a['id']} would end before it starts (it starts at beat {_n(a0)})")
                _retime_ok(a, a0, new, bpb, n)
                _set_beats(a, a0, new)
                _set_length(raw, new, B)
                continue
            b = shots[i + 1]
            b0, b1 = _beats(b)
            if not a0 < new < b1:
                raise EditError(f"line {n}: the cut between {a['id']} and {b['id']} must stay between beats {_n(a0)} and {_n(b1)}")
            _retime_ok(a, a0, new, bpb, n)
            _retime_ok(b, new, b1, bpb, n)
            _set_beats(a, a0, new)
            _set_beats(b, new, b1)
        elif x == "move":
            i = _find(shots, o["shot"], n)
            ref = o.get("before", o.get("after"))
            if str(ref) == str(o["shot"]):
                raise EditError(f"line {n}: a shot cannot move next to itself")
            s = shots.pop(i)
            j = _find(shots, ref, n) + (1 if "after" in o else 0)
            shots.insert(j, s)
            _rebeat(shots)
        elif x == "split":
            i = _find(shots, o["shot"], n)
            s = shots[i]
            b0, b1 = _beats(s)
            k = float(o["at"])
            if not 0 < k < b1 - b0:
                raise EditError(f"line {n}: split at= must be inside the shot (between 0 and {_n(b1 - b0)} beats)")
            if s.get("segs"):
                raise EditError(f"line {n}: shot {s['id']} is made of segs: split it by hand")
            ids = {str(x.get("id")) for x in shots}
            nid = next(str(s["id"]) + c for c in "bcdefghijklmnopqrstuvwxyz" if str(s["id"]) + c not in ids)
            cut = round(k * B, 6)
            t = copy.deepcopy(s)
            t["id"] = nid
            _set_beats(s, b0, b0 + k)
            _set_beats(t, b0 + k, b1)
            if "source" in t:
                t["t_in"] = _n(round(float(s.get("t_in", 0)) + cut * float(s.get("speed", 1)), 3))
            for key, field in (("overlays", "t"), ("sfx", "at")):
                if key in s:
                    s[key], t[key] = _shift_items(s[key], field, cut, True), _shift_items(s[key], field, cut, False)
                    for part in (s, t):
                        if not part[key]:
                            part.pop(key)
            shots.insert(i + 1, t)
            origin[nid] = origin.get(str(s["id"]), str(s["id"]))
            for ln in (raw.get("vo") or {}).get("lines") or []:
                if str(ln.get("shot")) == str(s["id"]) and float(ln.get("at", 0)) >= cut:
                    ln["shot"], ln["at"] = nid, _n(round(float(ln.get("at", 0)) - cut, 3))
        elif x == "delete":
            i = _find(shots, o["shot"], n)
            if len(shots) == 1:
                raise EditError(f"line {n}: the video's only shot cannot be deleted")
            s = shots.pop(i)
            vo = raw.get("vo") or {}
            if vo.get("lines"):
                vo["lines"] = [ln for ln in vo["lines"] if str(ln.get("shot")) != str(s["id"])]
            _set_length(raw, _rebeat(shots), B)
        elif x == "caption":
            s = shots[_find(shots, o["shot"], n)]
            ovs = s.get("overlays") or []
            caps = [v for v in ovs if isinstance(v, dict) and v.get("type") == "caption"]
            if not o["text"]:
                s["overlays"] = [v for v in ovs if v not in caps]
                if not s["overlays"]:
                    s.pop("overlays")
            elif caps:
                caps[0]["text"] = o["text"]
            else:
                b0, b1 = _beats(s)
                s["overlays"] = ovs + [dict(type="caption", text=o["text"], t=[0, _n(round((b1 - b0) * B, 3))])]
        elif x == "music":
            m = raw.get("music") or {}
            aid = local_id(o["asset"])
            beats = float((raw.get("timeline") or {}).get("beats", 0))
            if aid != m.get("asset") or not m.get("edit"):
                m = dict(m, asset=aid, bpm=_n(60.0 / B), track_beat=_n(round(B, 6)), track_offset=_n(o.get("offset", 0)),
                         edit=dict(segments=[[0, 0, _n(beats)]], crossfade=0.03, gains=[]))
            elif "offset" in o:
                m["track_offset"] = _n(o["offset"])
            raw["music"] = m
        elif x == "bus":
            raw.setdefault("mix", {}).setdefault("bus_db", {})[o["bus"]] = o["db"]
        elif x == "vo":
            ln = _vo_line(raw, o["line"], n)
            if "shot" in o:
                _find(shots, o["shot"], n)
                ln["shot"] = str(o["shot"])
            if "at" in o:
                ln["at"] = o["at"]
            if "db" in o:
                ln["db"] = o["db"]
            if "take" in o:
                if (raw.get("vo") or {}).get("engine") != "files":
                    raise EditError(f"line {n}: this voice-over is synthesised, so a recorded take cannot replace a line")
                ln["file"] = take_file(o["take"])
                ln.pop("sha256", None)
            if o.get("mute") is True:
                ln["mute"] = True
            elif o.get("mute") is False:
                ln.pop("mute", None)
        elif x == "grade":
            s = shots[_find(shots, o["shot"], n)]
            if o.get("off"):
                s.pop("grade", None)
            else:
                if s.get("ui", True) is not False:
                    raise EditError(f"line {n}: shot {o['shot']} shows the product, and its pixels are never graded (rule 2); grade plates (ui: false) only")
                s["grade"] = dict(s.get("grade") or {}, **{k: o[k] for k in GRADE_KEYS if k in o})
        elif x == "fade":
            s = shots[_find(shots, o["shot"], n)]
            if o.get("off"):
                s.pop("fade", None)
            else:
                b0, b1 = _beats(s)
                if sum(float(o.get(k, (s.get("fade") or {}).get(k, 0))) for k in ("in", "out")) > (b1 - b0) * B + 1e-6:
                    raise EditError(f"line {n}: the fades are longer than shot {o['shot']}")
                s["fade"] = dict(s.get("fade") or {}, **{k: o[k] for k in ("in", "out") if k in o})
        elif x == "speed":
            s = shots[_find(shots, o["shot"], n)]
            if "source" not in s:
                raise EditError(f"line {n}: shot {o['shot']} has no footage to speed up or slow down")
            s["speed"] = o["speed"]
        elif x == "fx":
            fx = o["preset"] if "amount" not in o else dict(preset=o["preset"], amount=o["amount"])
            t = o["target"]
            if t.startswith("vo:"):
                ln = _vo_line(raw, t[3:], n)
                if o["preset"] == "off":
                    ln.pop("fx", None)
                else:
                    ln["fx"] = fx
            else:
                sec = raw.get(t)
                if t != "mix" and not sec:
                    raise EditError(f"line {n}: this video has no {'voice-over' if t == 'vo' else t}")
                sec = raw.setdefault(t, {})
                if o["preset"] == "off":
                    sec.pop("fx", None)
                else:
                    sec["fx"] = fx
        elif x == "gain":
            m = raw.get("music") or {}
            if not isinstance(m.get("edit"), dict):
                raise EditError(f"line {n}: this video has no music edit to change the level of")
            if o.get("clear"):
                m["edit"]["gains"] = []
            else:
                g = dict(beats=[o["from"], o["to"]], db=o["db"])
                if "ramp" in o:
                    g["ramp"] = o["ramp"]
                m["edit"]["gains"] = list(m["edit"].get("gains") or []) + [g]
        elif x == "sfx":
            s = shots[_find(shots, o["shot"], n)]
            lst = s.get("sfx") or []
            if o["act"] == "add":
                name = local_id(o["sfx"])
                lib = raw.setdefault("sfx", {}).setdefault("library", {})
                if name not in lib:
                    lib[name] = dict(asset=name)
                e = dict(sfx=name, at=o["at"])
                if "db" in o:
                    e["db"] = o["db"]
                s["sfx"] = lst + [e]
            else:
                if not 1 <= o["i"] <= len(lst):
                    raise EditError(f"line {n}: shot {o['shot']} has {len(lst)} sound{'s' if len(lst) != 1 else ''}, so there is no number {o['i']}")
                if o["act"] == "rm":
                    lst = lst[:o["i"] - 1] + lst[o["i"]:]
                    if lst:
                        s["sfx"] = lst
                    else:
                        s.pop("sfx")
                else:
                    e = lst[o["i"] - 1]
                    for k in ("at", "db"):
                        if k in o:
                            e[k] = o[k]
    return raw, origin


# ---------------------------------------------------------------- writing promo.yaml as text (comments survive)
def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _blank(line):
    s = line.strip()
    return not s or s.startswith("#")


def _key_span(lines, lo, hi, key, ind):
    """(start, end) of `key:` at indent `ind` in lines[lo:hi] (an item's first line `- key:` counts too), or None."""
    pat = re.compile(r"^ {%d}%s:(\s|$)" % (ind, re.escape(key)))
    pat_item = re.compile(r"^ {%d}- %s:(\s|$)" % (max(0, ind - 2), re.escape(key)))
    for i in range(lo, hi):
        ln = lines[i]
        if pat.match(ln) or (i == lo and pat_item.match(ln)):
            j = i + 1
            while j < hi:
                s = lines[j]
                if _blank(s):
                    j += 1
                    continue
                k = _indent(s)
                if k > ind or (k == ind and s.lstrip().startswith("-")):
                    j += 1
                    continue
                break
            while j > i + 1 and _blank(lines[j - 1]):
                j -= 1
            return i, j
    return None


def _items(lines, lo, hi):
    """[(start, end)] of the sequence items in lines[lo:hi] (the lines under a `key:`); trailing comments travel with the item before them."""
    starts = []
    ind = None
    for i in range(lo, hi):
        s = lines[i]
        if _blank(s):
            continue
        if s.lstrip().startswith("-"):
            if ind is None:
                ind = _indent(s)
            if _indent(s) == ind:
                starts.append(i)
    return [(a, starts[k + 1] if k + 1 < len(starts) else hi) for k, a in enumerate(starts)], ind


def _split_comment(line):
    q = None
    for i, c in enumerate(line):
        if q:
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "#" and i and line[i - 1] in " \t":
            j = i
            while j and line[j - 1] in " \t":
                j -= 1
            return line[:j], line[j:].rstrip("\n")
    return line.rstrip("\n"), ""


def _dump(key, value, ind):
    """`key: value` at indent `ind`: scalars and lists / maps of scalars on one line ([a, b], {x: 1}), deeper values as blocks."""
    flow = False if not isinstance(value, (dict, list)) else None
    txt = yaml.safe_dump({key: value}, default_flow_style=flow, sort_keys=False, allow_unicode=True, width=4096)
    return [" " * ind + ln + "\n" for ln in txt.splitlines()]


def _dump_item(value, ind):
    txt = yaml.safe_dump([value], default_flow_style=None, sort_keys=False, allow_unicode=True, width=4096)
    return [" " * ind + ln + "\n" for ln in txt.splitlines()]


def _set_key(lines, lo, hi, key, value, ind, delete=False, old=None):
    """Replace (or add, or with delete=True remove) `key:` in lines[lo:hi]; returns the new lines of that range. A one-line key keeps its comment;
    a list with as many items as before (`old`) is rewritten item by item, so each keeps its style and comments."""
    block = lines[lo:hi]
    sp = _key_span(block, 0, len(block), key, ind)
    if delete:
        if sp:
            del block[sp[0]:sp[1]]
        return block
    if sp and isinstance(old, list) and isinstance(value, list) and len(old) == len(value) and sp[1] - sp[0] > 1:
        items, _ = _items(block, sp[0] + 1, sp[1])
        if len(items) == len(old):
            out = []
            for (i0, i1), o, v in zip(items, old, value):
                out += _write_item(_ends_nl(block[i0:i1]), o, v)
            block[items[0][0]:items[-1][1]] = out
            return block
    new = _dump(key, value, ind)
    if sp:
        a, b = sp
        first = block[a]
        if first.lstrip().startswith("- "):          # the item's first line: keep its "- "
            new[0] = " " * (ind - 2) + "- " + new[0].lstrip(" ")
        if b - a == 1 and len(new) == 1:
            _, com = _split_comment(first)
            if com:
                new[0] = new[0].rstrip("\n") + com + "\n"
        block[a:b] = new
    else:
        at = len(block)
        while at > 1 and _blank(block[at - 1]):
            at -= 1
        if at and not block[at - 1].endswith("\n"):
            block[at - 1] += "\n"
        block[at:at] = new
    return block


def _ends_nl(lines):
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return lines


def _write_item(item_lines, old, new):
    """An item (a shot or a VO line) with only its changed keys rewritten; a one-line `- {...}` item is written out again."""
    if old == new:
        return item_lines
    first = item_lines[0]
    ind = _indent(first)
    if first.lstrip().startswith("- {") or not isinstance(old, dict) or not isinstance(new, dict):
        com = [ln for ln in item_lines[1:]]
        one = yaml.safe_dump(new, default_flow_style=True, sort_keys=False, allow_unicode=True, width=4096).strip()
        body = [" " * ind + "- " + one + "\n"] if first.lstrip().startswith("- {") and "\n" not in one else _dump_item(new, ind)
        if len(body) == 1:
            _, c = _split_comment(first)
            body[0] = body[0].rstrip("\n") + c + "\n" if c else body[0]
        return body + com
    lines = _ends_nl(list(item_lines))
    kind = ind + 2
    for k in list(old):
        if k not in new:
            lines = _set_key(lines, 0, len(lines), k, None, kind, delete=True)
    for k, v in new.items():
        if k not in old or old[k] != v:
            lines = _set_key(lines, 0, len(lines), k, v, kind, old=old.get(k))
    return lines


def _top(lines):
    """{top-level key: (start, end)}."""
    out = {}
    for i, ln in enumerate(lines):
        m = re.match(r"^([A-Za-z_][\w-]*):(\s|$)", ln)
        if m:
            out[m.group(1)] = _key_span(lines, i, len(lines), m.group(1), 0)
    return out


def write_text(text, old, new, origin=None):
    """promo.yaml text with `old` (its data) changed to `new`, touching only what differs. Comments outside the changed lines stay."""
    origin = origin or {}
    lines = _ends_nl(text.splitlines(keepends=True))
    reps = []
    spans = _top(lines)
    for key in new:
        if key in old and old[key] == new[key]:
            continue
        sp = spans.get(key)
        if sp is None:
            reps.append((len(lines), len(lines), _dump(key, new[key], 0)))
            continue
        a, b = sp
        if key == "shots" and isinstance(old.get(key), list):
            items, ind = _items(lines, a + 1, b)
            if len(items) == len(old["shots"]):
                blocks = {str(s.get("id")): (lines[i0:i1], s) for (i0, i1), s in zip(items, old["shots"])}
                moved = [str(s.get("id")) for s in new["shots"]] != list(blocks)          # an alias can only lose its anchor when shots move or go
                out = []
                for s in new["shots"]:
                    sid = str(s.get("id"))
                    src = blocks.get(sid) or blocks.get(origin.get(sid, ""))
                    if src is None:
                        out += _dump_item(s, ind if ind is not None else 0)
                        continue
                    blk = _ends_nl(list(src[0]))
                    if sid not in blocks:                          # a split's second half: the copy must not define the anchor again
                        blk = [ANCHOR_RE.sub("", ln) for ln in blk]
                    blk = _write_item(blk, src[1], s)
                    out += _explicit_aliases(blk, s) if moved else blk
                reps.append((items[0][0] if items else a + 1, items[-1][1] if items else b, out))
                continue
        if key == "vo" and isinstance(old.get(key), dict) and isinstance(new.get(key), dict) \
                and {k: v for k, v in old["vo"].items() if k != "lines"} == {k: v for k, v in new["vo"].items() if k != "lines"}:
            ls = _key_span(lines, a + 1, b, "lines", _child_indent(lines, a, b))
            if ls:
                items, ind = _items(lines, ls[0] + 1, ls[1])
                ol, nl_ = old["vo"].get("lines") or [], new["vo"].get("lines") or []
                if len(items) == len(ol):
                    byid = {str(x.get("id", x.get("shot"))): (lines[i0:i1], x) for (i0, i1), x in zip(items, ol)}
                    out = []
                    for x in nl_:
                        src = byid.get(str(x.get("id", x.get("shot"))))
                        out += _write_item(_ends_nl(list(src[0])), src[1], x) if src else _dump_item(x, ind or 0)
                    reps.append((items[0][0], items[-1][1], out))
                    continue
        if isinstance(old.get(key), dict) and isinstance(new[key], dict) and not lines[a].split(":", 1)[1].strip().split("#")[0].strip():
            ci = _child_indent(lines, a, b)
            blk = lines[a:b]
            for k in list(old[key]):
                if k not in new[key]:
                    blk = blk[:1] + _set_key(blk, 1, len(blk), k, None, ci, delete=True)
            for k, v in new[key].items():
                if k not in old[key] or old[key][k] != v:
                    blk = blk[:1] + _set_key(blk, 1, len(blk), k, v, ci, old=old[key].get(k))
            reps.append((a, b, blk))
            continue
        new_lines = _dump(key, new[key], 0)
        _, com = _split_comment(lines[a])
        if b - a == 1 and len(new_lines) == 1 and com:
            new_lines[0] = new_lines[0].rstrip("\n") + com + "\n"
        reps.append((a, b, new_lines))
    for key in old:
        if key not in new and spans.get(key):
            reps.append((*spans[key], []))
    for a, b, rep in sorted(reps, key=lambda r: r[0], reverse=True):
        lines[a:b] = rep
    return "".join(lines)


ANCHOR_RE = re.compile(r"&[\w-]+ ")
ALIAS_RE = re.compile(r"^( *)(?:- )?([\w-]+):\s*\*[\w-]+\s*(#.*)?$")


def _explicit_aliases(blk, s):
    """`crop: *id001` in a shot that moves, or whose anchor's shot moves or goes, would point at nothing: write the value out instead."""
    for i, ln in enumerate(list(blk)):
        m = ALIAS_RE.match(ln)
        if m and m.group(2) in s:
            ind = len(m.group(1)) + (2 if ln.lstrip().startswith("- ") else 0)
            new = _dump(m.group(2), s[m.group(2)], ind)
            if ln.lstrip().startswith("- "):
                new[0] = m.group(1) + "- " + new[0].lstrip(" ")
            if len(new) == 1:
                blk[i] = new[0]
    return blk


def _child_indent(lines, a, b):
    for i in range(a + 1, b):
        if not _blank(lines[i]):
            return _indent(lines[i])
    return 2


# ---------------------------------------------------------------- files: undo snapshot, cross-project copies, gates
def _sha_file(path):
    from .assets import sha256_file
    return sha256_file(path)


def _link_or_copy(src, dst):
    """An independent copy: a clone on APFS (instant, no extra space until one side changes), else a plain copy. Never a hardlink: a tool that
    rewrites the source in place (ffmpeg -y on out/<name>.mp4) would change the copy too, which is how 11 drafts once became one file."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.exists(dst):
        os.remove(dst)
    if sys.platform == "darwin" and subprocess.run(["cp", "-c", src, dst], capture_output=True).returncode == 0:
        return dst
    shutil.copy2(src, dst)
    return dst


def _project_dir(name):
    for d in __import__("promo.home", fromlist=["x"]).flow_projects():
        if os.path.basename(os.path.normpath(d)) == name:
            return d
    from . import home
    d = home.resolve(name)
    if os.path.isfile(os.path.join(d, "promo.yaml")):
        return d
    raise EditError(f"no earlier project called {name} (the bin lists them)")


def _load_yaml(p, default=None):
    if not os.path.isfile(p):
        return default
    with open(p) as f:
        return yaml.safe_load(f) or default


def _assets_rows(pd):
    d = _load_yaml(os.path.join(pd, "assets.yaml"), {}) or {}
    return d.get("assets", d) if isinstance(d, dict) else d


def _spec_raw(pd):
    return _load_yaml(_spec_path(pd), {}) or {}


def _foreign_spec(proj_dir):
    from .spec import load_spec
    return load_spec(_spec_path(proj_dir), plugins=False)


def _append_asset(pd, entry, header="# Every asset needs a licence; music / vo / sfx also need source_url.\n"):
    p = os.path.join(pd, "assets.yaml")
    text = open(p).read() if os.path.isfile(p) else header + "assets:\n"
    rows = _assets_rows(pd) or []
    if any(r.get("id") == entry["id"] for r in rows):
        return False
    body = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True, width=4096)
    if not re.search(r"(?m)^assets:\s*$", text):
        text = text.rstrip("\n") + "\nassets:\n"
    with open(p, "w") as f:
        f.write(text.rstrip("\n") + "\n" + body)
    return True


def _copy_footage(pd, ref):
    """`project:clip` -> this project's manifest gets the same entry (same path and sha256) as `project-clip`."""
    from . import footage as FT
    proj, cid = ref.split(":", 1)
    src = _foreign_spec(_project_dir(proj))
    man = FT.load(src)
    if cid not in man:
        raise EditError(f"{proj} has no footage {cid}")
    nid = local_id(ref)
    here = FT.load_raw(os.path.join(pd, "footage", "manifest.yaml"))
    have = next((c for c in here if c.get("id") == nid), None)
    if have:
        if have.get("sha256") != man[cid].get("sha256"):
            raise EditError(f"this project already has a different footage {nid}")
        return nid
    e = {k: v for k, v in man[cid].items()}
    e["id"], e["shots"] = nid, []
    e["notes"] = (str(e.get("notes") or "") + f" Copied from project {proj} ({cid}) in the editor.").strip()
    spec_here = _foreign_spec(pd)
    FT.save(spec_here, here + [e])
    FT.sync_md(spec_here)
    return nid


def _copy_asset(pd, ref, kinds):
    """`project:asset` -> its file linked into media/<kind>/ and its assets.yaml row (licence, source_url) copied as `project-asset`."""
    from . import assets as A
    proj, aid = ref.split(":", 1)
    src = _foreign_spec(_project_dir(proj))
    man = A.load_manifest(src)
    if aid not in man:
        raise EditError(f"{proj} has no asset {aid}")
    a = man[aid]
    if a.get("kind") not in kinds:
        raise EditError(f"{proj}'s {aid} is {a.get('kind')}, not {' or '.join(kinds)}")
    if not str(a.get("licence") or "").strip() or not str(a.get("source_url") or "").strip():
        raise EditError(f"{proj}'s {aid} has no licence or source in its assets.yaml, so it cannot be used (rule 4)")
    nid = local_id(ref)
    if any(r.get("id") == nid for r in _assets_rows(pd) or []):
        return nid
    p = a["abs_path"]
    if not p or not os.path.isfile(p):
        raise EditError(f"{proj}'s {aid} file is missing: {p}")
    rel = os.path.join("media", a["kind"], nid + os.path.splitext(p)[1])
    _link_or_copy(p, os.path.join(pd, rel))
    e = {k: v for k, v in a.items() if k not in ("abs_path", "id", "path", "fetch_url")}
    e = dict(id=nid, kind=a["kind"], path=rel, **{k: v for k, v in e.items() if k != "kind"})
    e["sha256"] = _sha_file(os.path.join(pd, rel))
    e["notes"] = (str(e.get("notes") or "") + f" Copied from project {proj} ({aid}) in the editor.").strip()
    _append_asset(pd, e)
    return nid


def _vo_dir(pd, raw):
    from .spec import load_spec
    from . import assets as A
    spec = load_spec(_spec_path(pd), plugins=False)
    return A.asset_path(spec, raw["vo"]["asset"])


def _copy_take(pd, raw, ref):
    proj, rel = ref.split(":", 1)
    d = _project_dir(proj)
    cands = [os.path.join(d, rel)]
    try:
        fs = _foreign_spec(d)
        if (fs.raw.get("vo") or {}).get("asset"):
            from . import assets as A
            cands.append(os.path.join(A.asset_path(fs, fs.raw["vo"]["asset"]), rel))
    except Exception:  # noqa: BLE001  (an earlier project without a readable spec: only its folder is searched)
        pass
    src = next((p for p in cands if os.path.isfile(p)), None)
    if not src:
        raise EditError(f"no voice take {rel} in {proj}")
    dst = os.path.join(_vo_dir(pd, raw), take_file(ref))
    _link_or_copy(src, dst)
    return dst


def import_file(pd, path, kind, licence, source, by, fid=None):
    """Copy the person's file into media/<kind>/ and record it with its licence and source (rule 4). Returns (id, what)."""
    by = F.human(by)
    if kind not in IMPORT_KINDS:
        raise EditError(f"kind is one of {', '.join(IMPORT_KINDS)}")
    if not os.path.isfile(path):
        raise EditError(f"no such file {path}")
    if not (licence or "").strip() or not (source or "").strip():
        raise EditError(f"a licence and a source are needed (rule 4); \"{OWN}\" is fine for the person's own")
    if licence.strip().lower() == OWN.lower():
        licence = f"{OWN} ({by}): theirs to use"
    stem = re.sub(r"[^\w-]+", "-", os.path.splitext(os.path.basename(path))[0]).strip("-").lower() or kind
    fid = fid or f"{ {'voice': 'vo-take', 'video': 'rec'}.get(kind, kind)}-{stem}"
    ext = os.path.splitext(path)[1].lower()
    raw = _spec_raw(pd)
    if kind == "video":
        from . import footage as FT
        from .spec import load_spec
        dst = os.path.join(pd, "footage", fid + ext)
        _link_or_copy(path, dst)
        spec = load_spec(_spec_path(pd), plugins=False)
        FT.add(spec, dst, fid, commit="imported", capture=f"imported in the editor by {by}", framing="as recorded",
               notes=f"Licence: {licence}. Source: {source}. Imported by {by}.")
        what = f"video {fid} (footage manifest)"
    else:
        if kind == "voice" and (raw.get("vo") or {}).get("engine") == "files":
            dst = os.path.join(_vo_dir(pd, raw), "takes", fid + ext)
        else:
            dst = os.path.join(pd, "media", kind, fid + ext)
        _link_or_copy(path, dst)
        if not _append_asset(pd, dict(id=fid, kind="vo" if kind == "voice" else kind, path=os.path.relpath(dst, pd), licence=licence, source_url=source,
                                      sha256=_sha_file(dst), notes=f"Imported in the editor by {by}.")):
            raise EditError(f"this project already has an asset {fid}: pass id=... for another name")
        what = f"{kind} {fid}" + (f" (use it with: vo LINE take=takes/{fid}{ext})" if kind == "voice" and "takes" in dst else "")
    _log(pd, dict(kind="import", by=by, text=f"import {fid} kind={kind}", what=what))
    return fid, what


def _prepare(pd, ops, raw):
    """Copy what the ops take from earlier projects; returns the files written (for the undo) as {path: text or None}."""
    touched = {}

    def keep(rel):
        p = os.path.join(pd, rel)
        if p not in touched:
            touched[p] = open(p).read() if os.path.isfile(p) else None
    for o in ops:
        if o["op"] == "swap" and ":" in o["source"]:
            keep(os.path.join("footage", "manifest.yaml"))
            keep(os.path.join("footage", "manifest.md"))
            _copy_footage(pd, o["source"])
        elif o["op"] == "music" and ":" in o["asset"]:
            keep("assets.yaml")
            _copy_asset(pd, o["asset"], ("music",))
        elif o["op"] == "sfx" and o["act"] == "add" and ":" in o["sfx"]:
            keep("assets.yaml")
            _copy_asset(pd, o["sfx"], ("sfx",))
        elif o["op"] == "vo" and ":" in str(o.get("take", "")):
            _copy_take(pd, raw, o["take"])
    return touched


def _gates(pd):
    from . import assets as A
    from . import footage as FT
    from .spec import SpecError, load_spec
    try:
        spec = load_spec(_spec_path(pd))
        errs = spec.validate()
        if errs:
            raise EditError("; ".join(errs))
        A.gate(spec)
        FT.gate(spec)
        names = set((spec.raw.get("sfx") or {}).get("library") or {})
        for s in spec.shots:
            for e in s.get("sfx") or []:
                if e.get("sfx") not in names:
                    raise EditError(f"shot {s.id}: no sound called {e.get('sfx')} in the sfx library")
        if spec.raw.get("vo", {}).get("engine") == "files":
            from . import vo as VO
            for ln in spec.raw["vo"].get("lines") or []:
                p = VO.line_file(spec, ln)
                if not os.path.isfile(p):
                    raise EditError(f"voice line {VO.line_id(ln)}: no file {p}")
    except EditError:
        raise
    except (SpecError, KeyError, ValueError) as e:
        raise EditError(str(e))


def _log(pd, rec):
    os.makedirs(edir(pd), exist_ok=True)
    with open(os.path.join(edir(pd), "log.jsonl"), "a") as f:
        f.write(json.dumps(dict(at=now(), **rec)) + "\n")


def log_rows(pd):
    p = os.path.join(edir(pd), "log.jsonl")
    if not os.path.isfile(p):
        return []
    out = []
    for ln in open(p):
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _B(pd, raw):
    from .spec import load_spec
    spec = load_spec(_spec_path(pd), plugins=False)
    return spec.timeline.B, (spec.grid.beats_per_bar if spec.grid else 4)


def summary_of(ops):
    """What the edits are, in a few words: "music, shot 07 source, 2 captions"."""
    parts = {}
    for o in ops:
        x = o["op"]
        k = {"swap": "footage", "trim": "cuts", "move": "order", "split": "splits", "delete": "deletions", "caption": "captions", "music": "music",
             "bus": "levels", "vo": "voice", "sfx": "sounds", "grade": "grades", "fade": "fades", "speed": "speeds", "fx": "effects", "gain": "music levels",
             "import": "imports"}[x]
        parts[k] = parts.get(k, 0) + 1
    return ", ".join(f"{v} {k}" if v > 1 else k for k, v in parts.items())


def apply(pd, text, by, kind="apply"):
    """Apply edit text to promo.yaml (+ manifests). Every gate runs before it counts; a refused edit leaves every file as it was.
    Returns (ops, undo number)."""
    by = F.human(by)
    ops = parse(text) if isinstance(text, str) else text
    for o in ops:
        if o["op"] == "import":
            import_file(pd, o["path"], o["kind"], o["licence"], o["source"], by, o.get("id"))
    ops = [o for o in ops if o["op"] != "import"]
    if not ops:
        return [], None
    sp = _spec_path(pd)
    if not os.path.isfile(sp):
        raise EditError(f"no promo.yaml in {pd}: the editor works on a built project")
    text0 = open(sp).read()
    raw0 = yaml.safe_load(text0) or {}
    B, bpb = _B(pd, raw0)
    new, origin = apply_ops(raw0, ops, B, bpb)          # the whole batch is checked on the data before any file is touched
    st = F.load(pd)
    name, k = VR._undo_name(st)
    VR.keep(pd, name)
    touched = {}
    try:
        touched = _prepare(pd, ops, raw0)
        out = write_text(text0, raw0, new, origin)
        try:
            back = yaml.safe_load(out)
        except yaml.YAMLError as e:
            raise EditError(f"promo.yaml could not be edited cleanly as text ({e.problem}): ask the agent to make this change by hand")
        if back != new:
            raise EditError("promo.yaml could not be edited cleanly as text: ask the agent to make this change by hand")
        with open(sp, "w") as f:
            f.write(out)
        _gates(pd)
    except BaseException:
        with open(sp, "w") as f:
            f.write(text0)
        for p, t in touched.items():
            if t is None:
                if os.path.isfile(p):
                    os.remove(p)
            else:
                with open(p, "w") as f:
                    f.write(t)
        raise
    what = f"Edited in the editor: {summary_of(ops)}"
    st = F.load(pd)
    st.setdefault("restores", []).append(dict(at=now(), by=by, draft=None, scene=None, shots=[], undo=k, from_undo=None, what=what, edit=True))
    F.log(st, f"{what} by {by} (undo: restore --undo {k})")
    F.save(pd, st)
    _log(pd, dict(kind=kind, by=by, text=text_of(ops), undo=k, base=hashlib.sha256(text0.encode()).hexdigest(),
                  after=hashlib.sha256(open(sp, "rb").read()).hexdigest()))
    return ops, k


def replay(pd, by):
    """A GENERATED promo.yaml was made again by its generator: put every logged edit back on top, in order. Nothing to do when the current
    spec is already an edited one."""
    by = F.human(by)
    rows = [r for r in log_rows(pd) if r.get("kind") in ("apply", "render") and r.get("text")]
    if not rows:
        return 0
    cur = hashlib.sha256(open(_spec_path(pd), "rb").read()).hexdigest()
    if any(r.get("after") == cur for r in rows):
        return 0
    n = 0
    for r in rows:
        apply(pd, r["text"], by, kind="replay")
        n += 1
    return n


def generated(pd):
    """The generator named in a `GENERATED by X` header of promo.yaml, else None."""
    try:
        head = "".join(open(_spec_path(pd)).readlines()[:6])
    except OSError:
        return None
    m = GENERATED_RE.search(head)
    return m.group(1).rstrip(":,.") if m else None


def keep_draft_file(pd, n, src):
    """flow/drafts/d<N><ext>: the draft's own file, so a later build that writes the same out/ path never replaces an earlier draft."""
    dst = os.path.join(F.fdir(pd), "drafts", f"d{n}{os.path.splitext(src)[1] or '.mp4'}")
    return _link_or_copy(src, dst)


def render(pd, text, by, note="", scale=None, log=print):
    """apply -> `promo build` (only the steps whose inputs changed) -> `promo check` -> the next draft. Returns the draft number."""
    from . import cli
    by = F.human(by)
    ops = parse(text) if (text or "").strip() else []
    if ops:
        ops, _ = apply(pd, ops, by, kind="render")
    sp = _spec_path(pd)
    pre = ["-p", sp] + (["--scale", str(scale)] if scale else [])
    F.note(pd, "Rendering your edit: " + (summary_of(ops) if ops else "rebuild"), "render")
    rc = cli.main(pre + ["build"])
    if rc:
        raise EditError("the build failed (see above); the edit is applied: fix it and run `promo flow edit render --by NAME` again")
    from .spec import load_spec
    spec = load_spec(sp, scale=scale)
    with _stdout_to_stderr():
        rc_check = cli.main(pre + ["check", "--json"])
    report = os.path.join(spec.out, f"{spec.name}-{spec.tag}-check.json")
    out = spec.output_path("")
    st = F.load(pd)
    nxt = len(st["drafts"]) + 1
    n = F.add_draft(pd, out, note or ("Edited in the editor: " + summary_of(ops) if ops else "Rebuilt"), report if os.path.isfile(report) else None)
    assert n == nxt
    rows = log_rows(pd)
    if rows and rows[-1].get("kind") == "render":
        _log(pd, dict(kind="drafted", by=by, draft=n))
    F.note(pd, f"Draft {n} is ready" + ("" if rc_check == 0 else ": some checks failed, see the draft"), "render", True)
    log(f"draft {n} registered from {out}" + ("" if rc_check == 0 else " (promo check reported failures)"))
    return n


class _stdout_to_stderr:
    """`promo check --json` prints its payload to stdout; inside `render` that goes to stderr so the CLI's own output stays readable."""

    def __enter__(self):
        self.old = sys.stdout
        sys.stdout = sys.stderr

    def __exit__(self, *a):
        sys.stdout = self.old


# ---------------------------------------------------------------- suggestions (the agent's answers the person can preview and keep)
def suggest(pd, text, note, by="agent"):
    ops = parse(text)
    raw = _spec_raw(pd)
    B, bpb = _B(pd, raw)
    apply_ops(raw, [o for o in ops if o["op"] != "import"], B, bpb)          # a suggestion that cannot apply is refused now, not when the person keeps it
    st = F.load(pd)
    ed = st.setdefault("edit", {})
    sid = f"s{ed.get('seq', 0) + 1}"
    ed["seq"] = ed.get("seq", 0) + 1
    ed.setdefault("suggestions", []).append(dict(id=sid, note=F._clip(note or summary_of(ops), 240), text=text_of(ops), by=by, at=now()))
    F.log(st, f"edit suggestion {sid}: {note}")
    F.save(pd, st)
    return sid


def keep(pd, sid, by):
    by = F.human(by)
    st = F.load(pd)
    ed = st.setdefault("edit", {})
    s = next((x for x in ed.get("suggestions") or [] if x["id"] == sid), None)
    if not s:
        raise EditError(f"no suggestion {sid}")
    s["kept"] = dict(by=by, at=now())
    F.log(st, f"{by} kept edit suggestion {sid}")
    F.save(pd, st)
    _log(pd, dict(kind="keep", by=by, text=s["text"], suggestion=sid))
    return s


def open_bin(pd, name, close=False):
    st = F.load(pd)
    ed = st.setdefault("edit", {})
    opened = [x for x in ed.get("open") or [] if x != name]
    if not close:
        _project_dir(name)
        opened = (opened + [name])[-2:]          # two earlier projects at a time keep the published state small
    ed["open"] = opened
    F.save(pd, st)
    return opened


# ---------------------------------------------------------------- the editor's state for the Stage
def _media(p):
    return F._media(p)


def _cache(pd):
    d = os.path.join(edir(pd), "cache")
    os.makedirs(d, exist_ok=True)
    return d


def _sig_key(*paths):
    from .cache import file_sig
    return hashlib.sha1("|".join(file_sig(p) + p for p in paths).encode()).hexdigest()[:16]


def _probe_dur(p):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", p], capture_output=True, text=True, timeout=30)
        return round(float(r.stdout.strip()), 3)
    except (ValueError, OSError, subprocess.SubprocessError):
        return None


def _durs(pd, paths):
    """Durations of media files, cached by their size and date."""
    cp = os.path.join(_cache(pd), "durations.json")
    try:
        cache = json.load(open(cp))
    except (OSError, ValueError):
        cache = {}
    out, dirty = {}, False
    for p in paths:
        if not p or not os.path.isfile(p):
            continue
        k = _sig_key(p)
        if k not in cache:
            cache[k] = _probe_dur(p)
            dirty = True
        out[p] = cache[k]
    if dirty:
        with open(cp, "w") as f:
            json.dump(cache, f)
    return out


def _peaks(pd, wav, n=PEAKS):
    if not wav or not os.path.isfile(wav):
        return []
    cp = os.path.join(_cache(pd), f"peaks-{_sig_key(wav)}.json")
    if os.path.isfile(cp):
        return json.load(open(cp))
    try:
        import numpy as np
        import soundfile as sf
        x, _ = sf.read(wav, always_2d=True, dtype="float32")
        a = np.abs(x).max(1)
        k = max(1, len(a) // n)
        pk = [round(float(v), 3) for v in a[: k * n].reshape(-1, k).max(1)][:n] if len(a) >= n else [round(float(v), 3) for v in a]
    except Exception as e:  # noqa: BLE001  (a file the decoder cannot read: no waveform, the track still plays)
        print(f"  no waveform for {wav}: {e}", file=sys.stderr)
        pk = []
    with open(cp, "w") as f:
        json.dump(pk, f)
    return pk


def _strip(pd, rows, w=192, h=108):
    """ONE picture for every shot's filmstrip (THUMBS frames per row), so the state carries one file instead of one per frame.
    rows: [(file, t0, dur)] (None for a shot with nothing to show). Cached by what went in."""
    key = hashlib.sha1(json.dumps([[r[0] and _sig_key(r[0]), r[1], r[2]] if r else None for r in rows]).encode()).hexdigest()[:16]
    out = os.path.join(_cache(pd), f"strip-{key}.jpg")
    if os.path.isfile(out):
        return out
    from PIL import Image
    sheet = Image.new("RGB", (w * THUMBS, h * max(1, len(rows))), (16, 16, 18))
    for i, r in enumerate(rows):
        if not r or not r[0] or not os.path.isfile(r[0]):
            continue
        p, t0, dur = r
        for k in range(THUMBS):
            t = t0 + dur * (k + 0.5) / THUMBS
            fp = os.path.join(_cache(pd), f"fr-{_sig_key(p)}-{t:.3f}.jpg")
            if not os.path.isfile(fp):
                if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                    try:
                        Image.open(p).convert("RGB").resize((w, h)).save(fp, quality=80)
                    except OSError:
                        continue
                else:
                    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-ss", f"{max(0.0, t):.3f}", "-i", p, "-frames:v", "1",
                                    "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}", "-q:v", "5", fp], capture_output=True)
            if os.path.isfile(fp):
                try:
                    sheet.paste(Image.open(fp).convert("RGB").resize((w, h)), (k * w, i * h))
                except OSError:
                    pass
    for old in os.listdir(_cache(pd)):
        if old.startswith("strip-") and old != os.path.basename(out):
            os.remove(os.path.join(_cache(pd), old))
    sheet.save(out, quality=78)
    return out


def _preview_of(path):
    """A playable stand-in for a footage file: <stem>-preview.mp4 next to it (the capture scripts make one), else the file if a browser plays it."""
    if not path:
        return None
    stem = os.path.splitext(path)[0]
    for c in (stem + "-preview.mp4", stem + ".mp4"):
        if os.path.isfile(c):
            return c
    return path if path.lower().endswith((".mp4", ".m4v", ".webm", ".png", ".jpg", ".jpeg", ".webp")) and os.path.isfile(path) else None


def _poster_of(path):
    if not path:
        return None
    stem = os.path.splitext(path)[0]
    for c in (stem + "-poster.png", stem + "-poster.jpg"):
        if os.path.isfile(c):
            return c
    return path if path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and os.path.isfile(path) else None


def _caption(s):
    for v in s.get("overlays") or []:
        if isinstance(v, dict) and v.get("type") == "caption":
            return v.get("text")
    return None


def view(pd, st=None):
    """`edit` in the snapshot (drafts, review and final): the timeline as built and what is fresh. Media are `$file` objects. Schema: mods/promo-flow/README.md."""
    from . import assets as A
    from . import cli
    from . import footage as FT
    from .cache import file_sig
    from .spec import load_spec
    st = st or F.load(pd)
    sp = _spec_path(pd)
    if not os.path.isfile(sp):
        return None
    try:
        spec = load_spec(sp)
    except Exception as e:  # noqa: BLE001  (a spec the agent is half way through editing: the editor says so instead of breaking the Stage)
        return dict(error=f"promo.yaml cannot be read right now: {F._clip(str(e), 200)}")
    raw = spec.raw
    status = {}
    try:
        for row in cli.cmd_status(spec, type("A", (), dict(force=False))())["steps"]:
            status[row["step"]] = row["status"]
    except Exception as e:  # noqa: BLE001
        print(f"  editor: build status unknown: {e}", file=sys.stderr)
    try:
        man = FT.load(spec)
    except Exception:  # noqa: BLE001
        man = {}
    try:
        amap = A.load_manifest(spec)
    except Exception:  # noqa: BLE001
        amap = {}
    ev = {}
    evp = os.path.join(spec.audio_dir, "events.json")
    if os.path.isfile(evp):
        ev = json.load(open(evp))
    boards = F.boards(pd, st)
    scenes = [s for _, b, _ in boards[:1] for s in b.get("scenes") or []]
    rows, shots = [], []
    for s in spec.shots:
        seg = spec.seg_path(s.id)
        fresh = status.get(f"shot {s.id}") == "up-to-date"
        src = s.get("source")
        src_path = man.get(src, {}).get("path") if isinstance(src, str) else None
        prev = _preview_of(src_path)
        overlap = [sc for sc in scenes if float(sc["t"][0]) < s.t1 - 1e-6 and float(sc["t"][1]) > s.t0 + 1e-6]
        scene = max(overlap, key=lambda sc: min(s.t1, float(sc["t"][1])) - max(s.t0, float(sc["t"][0])))["id"] if overlap else None
        rows.append((seg, 0.0, s.dur) if fresh or (os.path.isfile(seg) and not prev) else (prev, float(s.get("t_in", 0) or 0), s.dur) if prev else None)
        shots.append(dict(id=s.id, start_s=round(s.t0, 3), end_s=round(s.t1, 3), beats=[_n(s.b0), _n(s.b1)], type=s.type, source=src if isinstance(src, str) else None,
                          t_in=s.get("t_in"), speed=s.get("speed"), caption=_caption(s.cfg), ui=s.get("ui", True) is not False, scene=scene, local=cli.local_time(s),
                          seg=_media(seg) if fresh else None, fresh=fresh, src_preview=None if fresh else _media(prev), src_t=float(s.get("t_in", 0) or 0),
                          generated=bool(man.get(src, {}).get("generated")) if isinstance(src, str) else False,
                          sfx=[dict(i=i + 1, sfx=e.get("sfx"), at=e.get("at"), db=e.get("db", 0)) for i, e in enumerate(s.get("sfx") or []) if "at" in e]))
    vo = None
    vcfg = raw.get("vo") or {}
    if vcfg.get("lines"):
        vj = os.path.join(spec.vo_dir, "vo.json")
        meta = {str(x.get("id", x["shot"])): x for x in json.load(open(vj))["lines"]} if os.path.isfile(vj) else {}
        gains = _vo_gains(pd, spec, meta)
        lines = []
        for ln in vcfg["lines"]:
            lid = str(ln.get("id", ln["shot"]))
            m = meta.get(lid) or {}
            f = m.get("file")
            f = f if not f or os.path.isabs(f) else os.path.join(spec.vo_dir, f)
            try:
                at = spec.g(str(ln["shot"]), float(ln.get("at", 0)))
            except Exception:  # noqa: BLE001
                at = None
            lines.append(dict(id=lid, shot=str(ln["shot"]), at=ln.get("at", 0), at_s=at, dur=m.get("dur"), text=ln.get("text"), db=ln.get("db", 0),
                              muted=bool(ln.get("mute")), gain_db=gains.get(lid), file=_media(f)))
        vo = dict(engine=vcfg.get("engine", "kokoro"), lines=lines)
    music = None
    mcfg = raw.get("music") or {}
    if mcfg.get("asset"):
        from .music import music_path
        mp = music_path(spec)
        rawp = (amap.get(mcfg["asset"]) or {}).get("abs_path")
        music = dict(asset=mcfg["asset"], label=_label(amap.get(mcfg["asset"]) or {"id": mcfg["asset"]}), file=_media(mp) if status.get("music") == "up-to-date" else None,
                     raw=_media(rawp) if rawp and os.path.isfile(rawp) and os.path.getsize(rawp) < 100 << 20 else None, offset=mcfg.get("track_offset", 0),
                     track_beat=mcfg.get("track_beat"), peaks=_peaks(pd, mp) if os.path.isfile(mp) else [], fresh=status.get("music") == "up-to-date",
                     licence=(amap.get(mcfg["asset"]) or {}).get("licence"))
    lib = (raw.get("sfx") or {}).get("library") or {}
    sfx_files = {}
    for name, e in lib.items():
        if e.get("asset") and (amap.get(e["asset"]) or {}).get("abs_path"):
            sfx_files[name] = amap[e["asset"]]["abs_path"]
    sfx_events = []
    for e in ev.get("sfx") or []:
        sfx_events.append(dict(sfx=e["sfx"], at_s=e["t"], db=e.get("db", 0), times=e.get("times")[:64] if e.get("times") else None))
    mix = raw.get("mix") or {}
    bus = {"music": -5.0, "sfx": -8.0, "vo": 1.5, "amb": 0.0}
    bus.update(mix.get("bus_db") or {})
    duck = mix.get("duck") or {}
    masters = {m["name"]: _media(os.path.join(spec.audio_dir, f"mix-{m['name']}.wav")) for m in spec.masters}
    stems = {k: _media(os.path.join(spec.audio_dir, "stems", f"{k}.wav")) for k in ("music", "vo", "sfx")}
    edl_p = os.path.join(spec.out, "EDL.md")
    ed = st.get("edit") or {}
    log = [dict(at=r["at"], by=r.get("by"), text=r.get("text") or "", kind=r.get("kind"), draft=r.get("draft")) for r in log_rows(pd)[-12:]]
    est = _estimate(spec, status)
    return dict(
        fps=spec.fps, bpm=spec.timeline.bpm, beat_s=round(spec.timeline.B, 6), beats=_n(spec.timeline.beats), duration=spec.duration, beats_per_bar=spec.grid.beats_per_bar if spec.grid else 4,
        resolution=f"{spec.OW}x{spec.OH}", shots=shots, strip=_media(_strip(pd, rows)), strip_cols=THUMBS, vo=vo, music=music,
        sfx_lib=[dict(name=n, file=_media(p)) for n, p in sfx_files.items()], sfx_events=sfx_events[:200],
        buses={k: bus[k] for k in ("music", "sfx", "vo")}, duck=dict(db=duck.get("db", 7.0), pre=duck.get("pre", 0.12), post=duck.get("post", 0.1)),
        masters=masters, stems=stems, edl=open(edl_p).read()[:20000] if os.path.isfile(edl_p) else None, master_video=_media(spec.output_path("")) if status.get("assemble") == "up-to-date" else None,
        fresh=all(v == "up-to-date" for k, v in status.items() if k not in ("assets", "footage")) if status else False, estimate=est,
        spec=json.loads(json.dumps({k: raw.get(k) for k in SPEC_KEYS if k in raw}, default=str)), generated=generated(pd), suggestions=[dict(id=x["id"], note=x["note"], text=x["text"], by=x.get("by"), kept=bool(x.get("kept"))) for x in ed.get("suggestions") or []][-8:],
        log=log, sig=file_sig(sp)[:16],
        previews=[dict(id=x["id"], start=x["start"], end=x["end"], shots=x["shots"], note=x.get("note") or "", by=x.get("by"), at=x["at"], file=_media(os.path.join(pd, x["file"])))
                  for x in (ed.get("previews") or [])[-3:]][::-1])


def _estimate(spec, status):
    """Seconds the last build of each step took (from the stamps): the Render button's "about 1 min" per kind of change."""
    from .cache import Stamps
    stamps = Stamps(spec.build)
    out = {}
    for k in ("sfx", "vo", "music", "events", "mix", f"assemble_{spec.OW}", f"contact_{spec.OW}"):
        s = stamps.get(k)
        if s and "secs" in s:
            out[k.split("_")[0]] = s["secs"]
    shot = [stamps.get(f"shot_{s.id}_{spec.OW}") for s in spec.shots]
    secs = [x["secs"] for x in shot if x and "secs" in x and not x.get("cached")]
    out["shot"] = round(sum(secs) / len(secs), 1) if secs else 30.0
    return out


def _vo_gains(pd, spec, meta):
    """The gain the mix gives each VO line (level to mix.vo_line_lufs, plus its `db`), so the rough preview mix sits near the real one."""
    cp = os.path.join(_cache(pd), "vo-lufs.json")
    try:
        cache = json.load(open(cp))
    except (OSError, ValueError):
        cache = {}
    target = float((spec.raw.get("mix") or {}).get("vo_line_lufs", -16.0))
    lines = {str(x.get("id", x.get("shot"))): x for x in (spec.raw.get("vo") or {}).get("lines") or []}
    out, dirty = {}, False
    for lid, m in meta.items():
        f = m.get("file")
        f = f if not f or os.path.isabs(f) else os.path.join(spec.vo_dir, f)
        if not f or not os.path.isfile(f):
            continue
        k = _sig_key(f)
        if k not in cache:
            try:
                import pyloudnorm as pyln
                import soundfile as sf
                x, sr = sf.read(f, always_2d=True)
                cache[k] = round(float(pyln.Meter(sr).integrated_loudness(x)), 2) if len(x) > sr * 0.5 else -20.0
            except Exception:  # noqa: BLE001
                cache[k] = -20.0
            dirty = True
        out[lid] = round(target - cache[k] + float((lines.get(lid) or {}).get("db", 0) or 0), 2)
    if dirty:
        with open(cp, "w") as f:
            json.dump(cache, f)
    return out


def _label(a):
    from .flow import _asset_label
    return a.get("label") or _asset_label(dict(a, id=a.get("id", "")))


AUDIO_KINDS = {"music": "music", "sfx": "sfx", "vo": "voice"}


def _bin_items(pd, st, with_media, here=True, cache_pd=None):
    """The bin rows of one project: footage, plates, music, voice, sound effects (and, for this project, scripts and drafts)."""
    from . import assets as A
    from . import footage as FT
    from .spec import load_spec
    spec = load_spec(_spec_path(pd), plugins=False)
    items = []
    try:
        man = FT.load(spec)
    except Exception:  # noqa: BLE001
        man = {}
    refs = FT.referenced(spec) if man else {}
    cache_pd = cache_pd or pd          # durations are cached in the project being edited, never written into an earlier one
    durs = _durs(cache_pd, [c.get("path") for c in man.values()]) if with_media else {}
    for cid, c in man.items():
        p = c.get("path")
        prev = _preview_of(p)
        items.append(dict(key=f"footage:{cid}", id=cid, kind="plate" if c.get("generated") else "footage", label=cid, dur=durs.get(p), licence="generated non-UI plate" if c.get("generated") else ("demo mode" if c.get("demo") else "real capture"),
                          ui=not c.get("generated"), used_in=refs.get(cid, []), poster=_media(_poster_of(p)), media=_media(prev) if with_media else None,
                          resolution=c.get("resolution")))
    try:
        amap = A.load_manifest(spec)
    except Exception:  # noqa: BLE001
        amap = {}
    raw = spec.raw
    lib = (raw.get("sfx") or {}).get("library") or {}
    used_sfx = {}
    for s in spec.shots:
        for e in s.get("sfx") or []:
            used_sfx.setdefault(e.get("sfx"), []).append(s.id)
    adurs = _durs(cache_pd, [a.get("abs_path") for a in amap.values() if a.get("kind") in ("music", "sfx")]) if with_media else {}
    for aid, a in amap.items():
        kind = AUDIO_KINDS.get(a.get("kind"))
        p = a.get("abs_path")
        if kind not in ("music", "sfx") or not p or not os.path.isfile(p) or not p.lower().endswith((".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac")):
            continue
        names = [n for n, e in lib.items() if e.get("asset") == aid]
        used = (["music"] if (raw.get("music") or {}).get("asset") == aid else []) + [x for n in names for x in used_sfx.get(n, [])]
        items.append(dict(key=f"{kind}:{aid}", id=aid, kind=kind, label=_label(dict(a, id=aid)), dur=adurs.get(p), licence=a.get("licence"), source=a.get("source_url"),
                          used_in=used, names=names, media=_media(p) if with_media and os.path.getsize(p) < 100 << 20 else None, poster=None))
    if (raw.get("vo") or {}).get("engine") == "files":
        try:
            from . import vo as VO
            vdir = A.asset_path(spec, raw["vo"]["asset"], amap)
            lic = (amap.get(raw["vo"]["asset"]) or {}).get("licence")
            used = {VO.line_file(spec, ln, amap): VO.line_id(ln) for ln in raw["vo"].get("lines") or []}
            files = sorted(os.path.join(r, f) for r, _, fs in os.walk(vdir) for f in fs if f.lower().endswith(".wav"))[:80]
            for p in files:
                rel = os.path.relpath(p, vdir)
                items.append(dict(key=f"voice:{rel}", id=rel, kind="voice", label=rel, licence=lic, used_in=[used[p]] if p in used else [],
                                  media=_media(p) if with_media else None, poster=None))
        except Exception as e:  # noqa: BLE001
            print(f"  editor bin: voice folder unreadable: {e}", file=sys.stderr)
    if here:
        for s in st.get("scripts") or []:
            items.append(dict(key=f"script:{s['id']}", id=s["id"], kind="script", label=s["title"], used_in=[], media=None, poster=None))
        for i, d in enumerate(st.get("drafts") or []):
            items.append(dict(key=f"draft:d{i + 1}", id=f"d{i + 1}", kind="draft", label=f"Draft {i + 1}", note=d.get("note"), used_in=[], media=None, poster=None))
    return items


def bin_(pd, st=None):
    """`bin` in the snapshot: this project's assets with their media, and the earlier projects by name and counts (their media once opened)."""
    st = st or F.load(pd)
    from . import home
    if not os.path.isfile(_spec_path(pd)):
        return None
    here = _bin_items(pd, st, True)
    opened = (st.get("edit") or {}).get("open") or []
    me = os.path.realpath(pd)
    projects = []
    for d in home.flow_projects():
        if os.path.realpath(d) == me or not os.path.isfile(_spec_path(d)):
            continue
        name = os.path.basename(os.path.normpath(d))
        try:
            fst = F.load(d)
            items = _bin_items(d, fst, name in opened, here=False, cache_pd=pd)
        except Exception as e:  # noqa: BLE001  (an earlier project that no longer reads: listed, not opened)
            projects.append(dict(name=name, error=F._clip(str(e), 160), counts={}, items=[], open=False))
            continue
        counts = {}
        for it in items:
            counts[it["kind"]] = counts.get(it["kind"], 0) + 1
        poster = next((it["poster"] for it in items if it.get("poster")), None)
        projects.append(dict(name=name, title=F._clip(fst.get("intent", "").split(".")[0], 80), counts=counts, poster=poster, open=name in opened,
                             items=items if name in opened else []))
    return dict(here=here, projects=projects)


def count_files(x):
    if isinstance(x, dict):
        return 1 if set(x) == {"$file"} else sum(count_files(v) for v in x.values())
    if isinstance(x, list):
        return sum(count_files(v) for v in x)
    return 0


def fit_files(snap, limit=FILE_LIMIT):
    """The host takes at most 200 files per state and drops the rest without telling anyone: give way in a fixed order, least useful first
    (look-comparison stills of older drafts, earlier projects' media, posters, ...), and say what was left out."""
    if count_files(snap) <= limit:
        return snap
    dropped = []
    b = snap.get("bin") or {}
    e = snap.get("edit") or {}
    drafts = snap.get("drafts") or []

    def drop(objs, field, what):
        for o in objs:
            if count_files(snap) <= limit:
                return
            if isinstance(o, dict) and o.get(field):
                o[field] = None
                if what not in dropped:
                    dropped.append(what)
    looks = lambda ds: [sc for d in ds for sc in ((d.get("look") or {}).get("scenes") or [])]  # noqa: E731
    job = snap.get("job") or {}
    done_job = [x for x in job.get("items") or [] if job.get("state") != "running"]
    here = b.get("here") or []
    theirs = [it for p in b.get("projects") or [] for it in p.get("items") or []]
    steps = [(looks(drafts[:-1]), "pair", "older drafts' look stills"),
             ([it for it in theirs if it["kind"] in ("footage", "plate", "voice")], "media", "earlier projects' footage and takes"),
             (theirs + (b.get("projects") or []), "poster", "earlier projects' posters"),
             (done_job, "path", "the finished build's step pictures"),
             (here, "poster", "posters"),
             ([x for x in here if x["kind"] == "voice" and not x.get("used_in")], "media", "unused voice takes"),
             (looks(drafts[-1:]), "pair", "the latest draft's look stills"),
             ([x for x in here if x["kind"] in ("footage", "plate") and not x.get("used_in")], "media", "unused footage"),
             ([x for x in here if x["kind"] in ("footage", "plate")], "media", "footage previews"),
             (theirs, "media", "earlier projects' sounds and music"),
             (here, "media", "the bin's sounds and music"),
             ([e.get("stems") or {}], "music", "stems"), ([e.get("stems") or {}], "sfx", "stems"), ([e.get("stems") or {}], "vo", "stems"),
             ([e.get("music") or {}], "raw", "the music's source file"),
             ([s for s in e.get("shots") or [] if not s.get("fresh")], "src_preview", "source previews")]
    for objs, field, what in steps:
        drop(objs, field, what)
    if dropped and e:
        e["files_note"] = "Too many files for the Stage at once, so these are left out: " + ", ".join(dropped) + "."
    return snap


# ---------------------------------------------------------------- the agent's eyes and ears: read, look, listen, preview, dry run
def _clock(t):
    t = max(0.0, float(t or 0))
    return f"{int(t // 60)}:{t % 60:04.1f}"


def timeline_text(pd):
    """The timeline as text: every shot, caption, voice line, sound and the music, with beats and times, and what is built."""
    st = F.load(pd)
    v = view(pd, st)
    if not v or v.get("error"):
        raise EditError((v or {}).get("error") or "no promo.yaml")
    fresh = sum(1 for s in v["shots"] if s["fresh"])
    out = [f"{v['duration']:g} s, {v['beats']} beats at {v['bpm']:g} BPM (beat {v['beat_s']:g} s, bar {v['beat_s'] * v['beats_per_bar']:g} s), {v['resolution']} {v['fps']} fps. "
           f"Built: {fresh} of {len(v['shots'])} shots" + (", the rest is up to date" if v["fresh"] else "; `promo flow edit render` builds the rest")]
    if v.get("generated"):
        out.append(f"promo.yaml is GENERATED by {v['generated']}: after it runs again, `promo flow edit replay --by NAME`")
    spec = {str(s.get("id")): s for s in (v.get("spec") or {}).get("shots") or []}
    out.append(f"{'SHOT':<5} {'BEATS':<11} {'TIME':<15} {'TYPE':<8} {'SOURCE (t_in, speed)':<34} BUILT  CAPTION / GRADE / FADE / SOUNDS")
    for s in v["shots"]:
        c = spec.get(s["id"], {})
        src = f"{s['source']} ({s['t_in'] or 0:g}" + (f", x{s['speed']:g}" if s.get("speed") else "") + ")" if s["source"] else "-"
        extra = [f'"{s["caption"]}"' if s["caption"] else None, "grade " + json.dumps(c["grade"]) if c.get("grade") else None, "fade " + json.dumps(c["fade"]) if c.get("fade") else None,
                 ", ".join(f"[{e['i']}] {e['sfx']}@{e['at']:g}" + (f" {e['db']:g}dB" if e.get("db") else "") for e in s["sfx"]) or None, "plate" if not s["ui"] else None]
        out.append(f"{s['id']:<5} {str(s['beats'][0]) + '-' + str(s['beats'][1]):<11} {_clock(s['start_s']) + '-' + _clock(s['end_s']):<15} {s['type']:<8} {src:<34} "
                   f"{'yes' if s['fresh'] else 'NO':<6} " + " | ".join(x for x in extra if x))
    for ln in ((v.get("vo") or {}).get("lines") or []):
        out.append(f"VOICE {ln['id']:<4} shot {ln['shot']} +{float(ln['at']):g} s = {_clock(ln['at_s'])}" + (f"-{_clock(ln['at_s'] + ln['dur'])}" if ln.get("dur") and ln.get("at_s") is not None else "")
                   + f" \"{ln['text']}\"" + (f" db {ln['db']:g}" if ln.get("db") else "") + (" MUTED" if ln["muted"] else ""))
    m = v.get("music")
    raw = v.get("spec") or {}
    if m:
        e = (raw.get("music") or {}).get("edit") or {}
        out.append(f"MUSIC {m['asset']} from {float(m['offset'] or 0):g} s of the file; edit segments {e.get('segments')}" + (f"; gains {e['gains']}" if e.get("gains") else "")
                   + (f"; fx {raw['music']['fx']}" if (raw.get("music") or {}).get("fx") else ""))
    out.append(f"MIX   bus dB {v['buses']}; duck {v['duck']['db']:g} dB under the voice" + (f"; fx {(raw.get('mix') or {}).get('fx')}" if (raw.get("mix") or {}).get("fx") else ""))
    out.append("SOUNDS " + ", ".join(x["name"] for x in v.get("sfx_lib") or []))
    return "\n".join(out)


def _range(v, at=None, shot=None, start=None, end=None):
    """(start, end, [shot ids]) of a moment, a shot or a span on the timeline."""
    shots = v["shots"]
    if shot:
        s = next((x for x in shots if x["id"] == str(shot)), None)
        if not s:
            raise EditError(f"there is no shot {shot}")
        return s["start_s"], s["end_s"], [s["id"]]
    if at is not None:
        start, end = at, at
    start = max(0.0, float(start or 0))
    end = min(float(v["duration"]), float(end if end is not None else v["duration"]))
    if end < start:
        raise EditError("--to must come after --from")
    ids = [x["id"] for x in shots if x["start_s"] < max(end, start + 1e-3) and x["end_s"] > start]
    return start, end, ids


def _frame(path, t, out, w=640):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-ss", f"{max(0.0, t):.3f}", "-i", path, "-frames:v", "1", "-vf", f"scale={w}:-2", out], capture_output=True)
    return os.path.isfile(out)


def look(pd, at=None, shot=None, start=None, end=None, frames=4):
    """A sheet of frames as they are now: from the built segment of a shot that is up to date, else (marked) from its source footage at t_in.
    Returns the PNG path (read it to see)."""
    from PIL import Image, ImageDraw
    from .spec import load_spec
    st = F.load(pd)
    v = view(pd, st)
    spec = load_spec(_spec_path(pd))
    a, b, ids = _range(v, at, shot, start, end)
    times = [a] if b - a < 1e-3 else [a + (b - a) * (k + 0.5) / frames for k in range(frames)]
    d = os.path.join(edir(pd), "look")
    os.makedirs(d, exist_ok=True)
    tiles = []
    for k, t in enumerate(times):
        s = next((x for x in v["shots"] if x["start_s"] <= t < x["end_s"] + 1e-6), v["shots"][-1])
        seg = spec.seg_path(s["id"])
        src, how = (seg, "built") if s["fresh"] and os.path.isfile(seg) else (None, "NOT BUILT")
        lt = t - s["start_s"]
        if src is None:
            from . import footage as FT
            try:
                p = FT.load(spec).get(s["source"] or "", {}).get("path")
            except Exception:  # noqa: BLE001
                p = None
            src = _preview_of(p) or p
            lt = float(s.get("t_in") or 0) + lt * float(s.get("speed") or 1)
            how = "NOT BUILT: source at t_in"
        fp = os.path.join(d, f"f{k}.png")
        ok = bool(src) and (_frame(src, lt, fp) if not src.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) else bool(Image.open(src).convert("RGB").resize((640, 360)).save(fp) or True))
        im = Image.open(fp).convert("RGB").resize((640, 360)) if ok else Image.new("RGB", (640, 360), (30, 30, 34))
        dr = ImageDraw.Draw(im)
        dr.rectangle((0, 0, 640, 22), fill=(0, 0, 0))
        dr.text((6, 5), f"{_clock(t)}  shot {s['id']}  {how}" + (f"  \"{s['caption']}\"" if s["caption"] else ""), fill=(255, 220, 90) if how != "built" else (230, 230, 230))
        tiles.append(im)
    cols = min(len(tiles), 2)
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (640 * cols, 360 * rows), (0, 0, 0))
    for k, im in enumerate(tiles):
        sheet.paste(im, ((k % cols) * 640, (k // cols) * 360))
    out = os.path.join(d, f"look-{_clock(a).replace(':', '_')}-{_clock(b).replace(':', '_')}.png")
    sheet.save(out)
    return out, ids


def listen(pd, start=None, end=None, shot=None, stem="mix"):
    """A WAV excerpt of the current mix (or one stem) and what it sounds like in numbers: loudness, peak, a loudness line every 0.25 s,
    and when each voice line and sound starts. Returns (wav path, text)."""
    import numpy as np
    import soundfile as sf
    from .spec import load_spec
    st = F.load(pd)
    v = view(pd, st)
    spec = load_spec(_spec_path(pd))
    a, b, ids = _range(v, None, shot, start, end)
    if b - a < 0.05:
        b = min(float(v["duration"]), a + 2.0)
    src = os.path.join(spec.audio_dir, f"mix-{spec.masters[0]['name']}.wav") if stem == "mix" else os.path.join(spec.audio_dir, "stems", f"{stem}.wav")
    if stem == "music" and not os.path.isfile(src):
        src = os.path.join(spec.audio_dir, "music-edit.wav")
    if not os.path.isfile(src):
        raise EditError(f"no {stem} yet: `promo flow edit render` (or promo build) makes it")
    x, sr = sf.read(src, always_2d=True)
    seg = x[int(a * sr):int(b * sr)]
    d = os.path.join(edir(pd), "listen")
    os.makedirs(d, exist_ok=True)
    out = os.path.join(d, f"{stem}-{a:.2f}-{b:.2f}.wav")
    sf.write(out, seg.astype("float32"), sr)
    lines = [f"{stem} {_clock(a)}-{_clock(b)} ({b - a:.2f} s){'' if v['fresh'] else ' — NOTE: not everything is built, this is the last build'}"]
    try:
        import pyloudnorm as pyln
        L = pyln.Meter(sr).integrated_loudness(seg) if len(seg) > sr * 0.4 else float("nan")
        lines.append(f"loudness {L:.1f} LUFS, peak {20 * np.log10(np.abs(seg).max() + 1e-9):.1f} dBFS")
    except Exception:  # noqa: BLE001
        pass
    hop = int(sr * 0.25)
    env = []
    for k in range(0, max(1, len(seg) - hop + 1), hop):
        rms = float(np.sqrt((seg[k:k + hop] ** 2).mean()) + 1e-9)
        env.append(f"{_clock(a + k / sr)} {20 * np.log10(rms):6.1f} dB " + "#" * max(0, int((20 * np.log10(rms) + 60) / 2)))
    lines += env[:240]
    for ln in ((v.get("vo") or {}).get("lines") or []):
        if ln.get("at_s") is not None and a - 3 <= ln["at_s"] <= b:
            lines.append(f"voice {ln['id']} at {_clock(ln['at_s'])}{' (muted)' if ln['muted'] else ''}: \"{ln['text']}\"")
    for e in v.get("sfx_events") or []:
        if a <= e["at_s"] <= b:
            lines.append(f"sound {e['sfx']} at {_clock(e['at_s'])} {e.get('db', 0):g} dB")
    return out, "\n".join(lines)


def preview(pd, start=None, end=None, shot=None, by="agent", note="", scale=None):
    """Build only what a span needs (its shots and the sound; no other shot, no assembly, no check) and cut that span into a short clip with
    the new mix: the quick look before a whole draft. The clip is kept in flow/edit/previews/ and shown in the editor."""
    from . import cli
    from .spec import load_spec
    st = F.load(pd)
    v = view(pd, st)
    a, b, ids = _range(v, None, shot, start, end)
    if b - a < 0.1:
        raise EditError("a preview needs a span (--from and --to, or --shot)")
    pre = ["-p", _spec_path(pd)] + (["--scale", str(scale)] if scale else [])
    rc = cli.main(pre + ["build", "--shots", *ids])
    if rc:
        raise EditError("the build of those shots failed (see above)")
    spec = load_spec(_spec_path(pd), scale=scale)
    d = os.path.join(edir(pd), "previews")
    os.makedirs(d, exist_ok=True)
    ed = st.setdefault("edit", {})
    n = ed.get("pseq", 0) + 1
    out = os.path.join(d, f"p{n}.mp4")
    lst = os.path.join(d, f"p{n}.txt")
    with open(lst, "w") as f:
        for s in spec.shots:
            if s.id in ids:
                f.write(f"file '{spec.seg_path(s.id)}'\n")
    t0 = next(s.t0 for s in spec.shots if s.id == ids[0])
    wav = os.path.join(spec.audio_dir, f"mix-{spec.masters[0]['name']}.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-threads", "2", "-f", "concat", "-safe", "0", "-ss", f"{a - t0:.3f}", "-i", lst, "-ss", f"{a:.3f}", "-i", wav,
                    "-t", f"{b - a:.3f}", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", out], check=True)
    st = F.load(pd)
    ed = st.setdefault("edit", {})
    ed["pseq"] = n
    ed["previews"] = (ed.get("previews") or [])[-4:] + [dict(id=f"p{n}", file=os.path.relpath(out, pd), start=round(a, 3), end=round(b, 3), shots=ids, at=now(), by=by, note=note)]
    F.log(st, f"edit preview p{n}: {_clock(a)}-{_clock(b)} (shots {', '.join(ids)})")
    F.save(pd, st)
    return out, ids


def dry_run(pd, text):
    """What `apply` would change: the promo.yaml diff and the build steps that would run (worked out from the real stamps), nothing written."""
    import difflib
    from . import cli
    from .spec import load_spec
    ops = [o for o in parse(text) if o["op"] != "import"]
    sp = _spec_path(pd)
    text0 = open(sp).read()
    raw0 = yaml.safe_load(text0) or {}
    B, bpb = _B(pd, raw0)
    new, origin = apply_ops(raw0, ops, B, bpb)
    out = write_text(text0, raw0, new, origin)
    diff = "".join(difflib.unified_diff(text0.splitlines(True), out.splitlines(True), "promo.yaml", "promo.yaml (after)", n=1))
    before = {r["step"]: r["status"] for r in cli.cmd_status(load_spec(sp), None)["steps"]}
    try:
        with open(sp, "w") as f:
            f.write(out)
        try:
            after = {r["step"]: r["status"] for r in cli.cmd_status(load_spec(sp), None)["steps"]}
        except Exception as e:  # noqa: BLE001  (an op that needs an import or a copy first: the steps cannot be worked out yet)
            after = {"?": f"unknown until applied ({e})"}
    finally:
        with open(sp, "w") as f:
            f.write(text0)
    runs = [k for k, s in after.items() if s != "up-to-date" and k not in ("assets", "footage")]
    already = [k for k in runs if before.get(k) not in (None, "up-to-date")]
    return diff, runs, already


# ---------------------------------------------------------------- `promo flow edit ...`
def _ops_text(a):
    if a.file:
        return sys.stdin.read() if a.file == "-" else open(a.file).read()
    if a.arg:
        return a.arg
    raise EditError("give the edits as text, or --file F (- reads them from stdin)")


def cli(pd, a):
    """Returns True when the flow changed (the caller publishes)."""
    x = a.action
    if x == "view":
        st = F.load(pd)
        print(json.dumps(dict(edit=view(pd, st), bin=bin_(pd, st)) if a.json else view(pd, st), indent=1, default=str))
        return False
    if x == "timeline":
        print(timeline_text(pd))
        return False
    if x == "look":
        out, ids = look(pd, a.at, a.shot, a.from_, a.to, a.frames or 4)
        print(f"{out}  (shots {', '.join(ids)}; read the PNG to see them)")
        return False
    if x == "listen":
        out, txt = listen(pd, a.from_, a.to, a.shot, a.stem or "mix")
        print(txt + f"\n{out}")
        return False
    if x == "preview":
        out, ids = preview(pd, a.from_, a.to, a.shot, "agent", a.note, a.scale)
        print(f"preview of shots {', '.join(ids)}: {out} (in the editor for the person to watch); `promo flow edit look` / `listen` to check it")
        return True
    if x == "apply" and a.dry_run:
        diff, runs, already = dry_run(pd, _ops_text(a))
        print(diff or "(promo.yaml would not change)")
        print("would run: " + (", ".join(runs) or "nothing") + (f"  (already stale before: {', '.join(already)})" if already else ""))
        return False
    if x == "apply":
        ops, k = apply(pd, _ops_text(a), a.by)
        print(f"applied {len(ops)} edit{'s' if len(ops) != 1 else ''} ({summary_of(ops) or 'imports only'})" + (f"; undo: promo flow restore --undo {k} --by NAME" if k else "")
              + "; `promo flow edit render` (or promo build) makes the draft")
        return True
    if x == "render":
        text = _ops_text(a) if (a.file or a.arg) else ""
        n = render(pd, text, a.by, a.note, a.scale)
        print(f"draft {n} is registered; it is in the Stage")
        return True
    if x == "import":
        if not a.arg:
            raise EditError("import needs the file")
        fid, what = import_file(pd, a.arg, a.kind, a.licence, a.source, a.by, a.id)
        print(f"imported {what}")
        return True
    if x == "bin":
        if a.open or a.close:
            print("open in the bin: " + (", ".join(open_bin(pd, a.open or a.close, close=bool(a.close))) or "none"))
            return True
        b = bin_(pd)
        for it in (b or {}).get("here") or []:
            print(f"{it['kind']:<8} {it['id']:<36} {', '.join(it['used_in']) or '-'}")
        for p in (b or {}).get("projects") or []:
            print(f"project  {p['name']:<36} " + ", ".join(f"{v} {k}" for k, v in p.get("counts", {}).items()))
        return False
    if x == "suggest":
        sid = suggest(pd, _ops_text(a), a.note, "agent")
        print(f"suggestion {sid} is in the editor for the person to preview and keep")
        return True
    if x == "keep":
        if not a.arg:
            raise EditError("keep needs the suggestion id (s1, s2, ...)")
        keep(pd, a.arg, a.by)
        print(f"suggestion {a.arg} kept")
        return True
    if x == "replay":
        n = replay(pd, a.by)
        print(f"replayed {n} logged edit{'s' if n != 1 else ''}" if n else "nothing to replay: promo.yaml already has the logged edits")
        return bool(n)
    return False
