"""SFX + VO placement events from the spec (port of make_events.py, generic) -> build/audio/events.json.

Per-shot `sfx:` entries:
    {sfx: name, at: <shot-local out s>, [offset: s], [db: dB], [pan: p]}
    {sfx: name, src: <source s>, [offset: s], [db: ...]}           mapped through the shot type's src_to_out (dropped if off-screen)
    {sfx: typing, src_runs: [{start, step, count}, ...], [db: ...]} every key time mapped through src_to_out; event t = first time
Global time = round(round(shot_t0 + out, 3) + offset, 3) exactly like the legacy `add(name, g(...) - 0.12)`.
VO times come from `vo.lines[].at` (shot-local) via the same g().
Clip audio (`shot.audio`, promo/shot_audio.py) lands in `clips`: [{id, shot, t, bus, db, lufs, file (relative to build/), text}].
"""
from __future__ import annotations

import json
import os

from .shots import get_type
from .spec import number


def _run_times(run):
    """Source times of one typing run: start + i*step ('1/6' keeps the legacy `i / 6` expression)."""
    start, step, count = run["start"], run["step"], int(run["count"])
    if isinstance(step, str) and "/" in step:
        a, b = (float(x) for x in step.split("/"))
        return [start + (i * a) / b for i in range(count)]
    step = number(step)
    return [start + i * step for i in range(count)]


def compute_events(spec):
    sfx = []

    def add(name, t, db=0.0, **kw):
        if t is not None:
            sfx.append(dict(sfx=name, t=round(t, 3), db=db, **kw))

    for shot in spec.shots:
        st = get_type(shot.type)
        for e in shot.get("sfx", []) or []:
            name, db = e["sfx"], e.get("db", 0.0)
            extra = {"pan": e["pan"]} if "pan" in e else {}
            offset = e.get("offset", 0.0)
            if "src_runs" in e:
                times = []
                for run in e["src_runs"]:
                    for k in _run_times(run):
                        o = st.src_to_out(shot, k)
                        if o is not None:
                            times.append(spec.g(shot.id, o))
                if times:
                    sfx.append(dict(sfx=name, t=times[0], times=times, db=db))
                continue
            if "src" in e:
                o = st.src_to_out(shot, e["src"])
                out = None if o is None else spec.g(shot.id, o)
            else:
                out = spec.g(shot.id, e["at"])
            add(name, None if out is None else (out + offset if offset else out), db, **extra)
    vo = {}
    for line in spec.raw.get("vo", {}).get("lines", []):
        vo[str(line.get("id", line["shot"]))] = spec.g(line["shot"], line.get("at", 0.0))
    ev = dict(sfx=sorted(sfx, key=lambda e: e["t"]), vo=vo)
    from . import shot_audio
    clips = shot_audio.event_rows(spec)         # per-shot `audio:` lines (clip soundtrack), placed like VO lines
    if clips:
        ev["clips"] = clips
    return ev


def events_path(spec):
    return os.path.join(spec.audio_dir, "events.json")


def write_events(spec):
    ev = compute_events(spec)
    os.makedirs(spec.audio_dir, exist_ok=True)
    with open(events_path(spec), "w") as f:
        json.dump(ev, f, indent=1)
    return ev
