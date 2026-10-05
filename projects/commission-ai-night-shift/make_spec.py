"""Night shift v5: the dialogue film (reference: OpenAI 'Introducing dots'; brief.yaml + reference/dots/DOSSIER.md).
Human lines are SPOKEN ON CAMERA by the generated actress (Grok video with lip-synced speech); the agent's lines are a warm voice
generated the same way (audio used as voice-over only); the UI is the real recording, in her monitor (type screen) or as a lit panel
over the room (type cinema); music is Kevin MacLeod 'Eternal Hope' (CC BY 4.0). Generates promo.yaml:

    ../../.venv/bin/python make_spec.py > promo.yaml
"""
import json, math, os, sys
import yaml

BPM, BEAT, OFFSET = 100.434, 0.597408, 0.038
HERE = os.path.dirname(os.path.abspath(__file__))
MAN = yaml.safe_load(open(os.path.join(HERE, "../commission-ai-shared/footage/manifest.yaml")))["clips"]
HAVE = {c["id"] for c in MAN}
T = json.load(open(os.path.expanduser("~/promo-footage/speech/speech-timing.json")))

def has(c): return c in HAVE
NIGHT_SCREEN = has("d-ots-night2")
MORNING_SCREEN = has("d-ots-morning2") or has("d-ots-morning")
MORN_PLATE = "m-ots" if has("m-ots") else "d-ots-morning2"
HAVE_A6 = has("a-6")

def voice(clip, text, at=0.0, t_in=None, dur=None, bus="vo", aliases=None, db=0.0):
    tm = T.get(clip.replace("d-dev1", "dev1").replace("a-1", "agent1"), {})
    s = max((tm.get("start") or 0.0) - 0.12, 0.0) if t_in is None else t_in
    e = (tm.get("end") or 3.0) + 0.25
    a = {"from": clip, "t_in": round(s, 2), "dur": round(dur if dur else e - s, 2), "at": at, "lufs": -16.0, "bus": bus, "text": text, "db": db,
         "fade": {"in": 0.04, "out": 0.12}}
    if aliases: a["asr_aliases"] = aliases
    return a, (a["dur"] + at)

def own(clip, text, at=0.0, aliases=None, lead=0.45):
    """audio from the shot's own source clip (the actress speaking on camera); the picture starts `lead` s before her first word"""
    tm = T.get(clip.replace("d-dev1", "dev1"), {})
    st = tm.get("start") or 0.0
    pic = max(st - lead, 0.0)
    a_in = max(st - 0.12, 0.0)
    e = (tm.get("end") or 3.0) + 0.3
    a = {"from": "source", "t_in": round(a_in, 2), "dur": round(e - a_in, 2), "at": round(a_in - pic + at, 2), "lufs": -16.0, "bus": "vo", "text": text, "fade": {"in": 0.04, "out": 0.12}}
    if aliases: a["asr_aliases"] = aliases
    return a, pic, e

SOUND = lambda n, at, db: {"sfx": n, "at": at, "db": db}
PANEL = {"w": 0.86, "cy": 0.5, "glow": {"alpha": 0.40}, "rim": {"alpha": 0.26}}
def backdrop(plate, t): return {"backdrop": {"plate": plate, "t": t, "blur": 0.03, "dim": 0.62, "warm": 0.12, "parallax": 0.35}}

S = []   # dict(id, min_dur, shot) ; beats computed from max(min_dur, content)

def add(sid, dur, shot, content=0.0):
    sh = dict(shot); sh.setdefault("type", "cinema"); sh["id"] = sid
    S.append(dict(id=sid, dur=max(dur, content), shot=sh))

# ---- ACT 1: night, the hand-off
add("01", 3.6, dict(ui=False, source="p-window-rain", t_in=0.0, look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .96]], fade_in=1.2,
    title_bloom={"text": "commission-ai", "at": 0.8, "dur": 2.8, "cy": 0.27, "size": 1.3}, sfx=[SOUND("rain_bed", 0.0, -13)],
    notes="generated: rainy night window; the title blooms out of the dark like dots"))
a, s, e = own("d-dev1", "Ship the checkout revamp tonight. No broken builds.", aliases={"revamped": "revamp", "shift": "ship"})
add("02", e - s + 0.15, dict(ui=False, source="d-dev1", t_in=round(s, 2), look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]],
    audio=[a], sfx=[SOUND("room_tone", 0.0, -24)],
    notes="generated: the dev speaks on camera (lip-synced). VOICE: the clip's own audio"))
va, vend = voice("a-1", "Got it. Eight tickets, three waves. I'll check in when something needs your approval.", at=0.25, t_in=0.0, dur=4.95)
if NIGHT_SCREEN:
    add("03", vend + 0.4, dict(type="screen", plate="d-ots-night2", plate_t_in=0.0, source="shot-10b-4k", t_in=0.0, speed=0.18,
        cam=[[0, .36, .20, .62], ["end", .36, .30, .62]], screen={"glow": {"alpha": 0.40}}, audio=[dict(va, db=-1.0)],
        notes="real UI in her monitor: the bubble then the plan; AGENT voice-over (generated)"))
else:
    add("03", vend + 0.4, dict(source="shot-10b-4k", t_in=0.0, speed=0.18, cam=[[0, .36, .20, .62], ["end", .36, .30, .62]],
        look=backdrop("n-empty", 1.5), panel=PANEL, audio=[va],
        notes="real UI as a lit panel over the study: the bubble then the plan; AGENT voice-over (generated)"))
a, s, e = own("d-dev2", "Start with the design tokens.")
add("04", e - s + 0.2, dict(ui=False, source="d-dev2", t_in=round(s, 2), look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]],
    audio=[a], notes="generated: the dev speaks on camera"))
va, vend = voice("a-2", "Design tokens first. Wave one is running.", at=0.1, t_in=0.6, dur=3.5)
add("05", vend + 0.3, dict(type="screen" if NIGHT_SCREEN else "cinema", **({"plate": "d-ots-night2", "plate_t_in": 1.5, "screen": {"glow": {"alpha": 0.40}}} if NIGHT_SCREEN else {"look": backdrop("n-empty", 1.5), "panel": PANEL}),
    source="shot-04p-4k", t_in=0.5, cam=[[0, .42, .42, .96], ["end", .42, .42, .90]],
    audio=[dict(va, db=-1.0)], notes="real UI: Wave 1 'Design tokens for checkout surfaces' Running; AGENT voice-over (generated)"))
a, s, e = own("d-dev3", "Okay. I'm going to bed.")
add("06", 3.6, dict(ui=False, source="d-dev3", t_in=0.0, look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]],
    audio=[a], notes="generated: she says goodnight and closes the laptop (lid sound is in the clip)"))
va, vend = voice("a-3", "Rest up. I'll flag anything that needs you.", at=0.2, t_in=1.9, dur=3.3)
add("07", vend + 0.3, dict(ui=False, source="n-empty", t_in=0.5, look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .95]], audio=[va],
    sfx=[SOUND("rain_bed", 0.5, -13)], notes="generated: the empty study at night, rain; AGENT voice-over (generated)"))
# ---- the night shift (music, rain, keys)
add("08", 2.4, dict(type="screen" if NIGHT_SCREEN else "cinema", **({"plate": "d-ots-night2", "plate_t_in": 3.0, "screen": {"glow": {"alpha": 0.40}}} if NIGHT_SCREEN else {"look": backdrop("n-empty", 2.5), "panel": PANEL}),
    source="shot-01-dusk-4k", t_in=6.8, cam=[[0, .5, .58, .72], ["end", .5, .56, .64]],
    notes="real UI on her monitor in the dark study: the Workshop, agents at work"))
# ---- ACT 2: morning
add("10", 3.0, dict(ui=False, source="m-enter", t_in=1.0, look={"backdrop": "none"}, cam=[[0, .30, .42, .60], ["end", .32, .42, .56]], notes="generated: dawn, she walks in with a mug and sits"))
va, vend = voice("a-4", "Good morning. One command needs your approval.", at=0.1, t_in=0.6, dur=3.5)
if MORNING_SCREEN:
    add("11", vend + 0.3, dict(type="screen", plate=MORN_PLATE, plate_t_in=0.0, source="shot-10b-4k", t_in=0.9, speed=0.7, cam=[[0, .56, .80, .44], ["end", .56, .80, .38]],
        screen={"glow": {"alpha": 0.40}}, audio=[va], sfx=[SOUND("chime", 0.05, -10)],
        notes="real UI in her monitor: PAY-106 'Needs you'; AGENT voice-over (generated)"))
else:
    add("11", vend + 0.3, dict(source="shot-10b-4k", t_in=1.6, cam=[[0, .56, .80, .44], ["end", .56, .80, .38]], look=backdrop("d-empty-dawn", 1.5), panel=PANEL,
        audio=[va], sfx=[SOUND("chime", 0.05, -10)], notes="real UI panel: PAY-106 'Needs you'; AGENT voice-over (generated)"))
a, s, e = own("m-dev4", "Let me see. Yeah, allow it once.")
add("12", e - s + 0.2, dict(ui=False, source="m-dev4", t_in=round(s, 2), look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]],
    audio=[a], notes="generated: she leans in and says it on camera"))
add("13", 2.2, dict(type="screen", plate=MORN_PLATE, plate_t_in=2.0, source="shot-10b-4k", t_in=2.4, cam=[[0, .60, .86, .34], ["end", .60, .88, .30]],
    screen={"glow": {"alpha": 0.40}}, sfx=[SOUND("click", 1.50, -8)], notes="real UI in her monitor: the real click on Allow once (click sound on the visible press)"))
va, vend = voice("a-5", "Thanks. Pull request four thirty-two is open, and the reviewer approved it.", at=0.45, t_in=0.0, dur=4.65, aliases={"432": "four thirty-two"})
add("14", 1.4, dict(ui=False, source="m-listen", t_in=1.0, look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]], audio=[va],
    notes="generated: she listens, a small relieved smile; AGENT voice-over (generated)"))
add("15", 1.8, dict(source="shot-merged-drawer-dpr2", t_in=0.3, cam=[[0, .50, .33, 1.0], ["end", .50, .33, 1.0]], look=backdrop("d-empty-dawn", 1.5), panel=PANEL,
    notes="real UI: header 'In review - Review and merge PR #432', stepper at PR raised"))
add("16", 1.8, dict(source="shot-12b-4k", t_in=1.0, cam=[[0, .50, .45, 1.0], ["end", .50, .46, 1.0]], look=backdrop("d-empty-dawn", 1.5), panel=PANEL,
    notes="real UI: reviewer line 'Approved. Cart summary uses the pricing engine matches the plan'"))
a, s, e = own("m-dev5", "Merge it.")
add("17", e - s + 0.2, dict(ui=False, source="m-dev5", t_in=round(s, 2), look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]],
    audio=[a], notes="generated: she says it on camera"))
mer = dict(source="shot-merged-drawer-dpr2", t_in=3.6, cam=[[0, .50, .36, 1.0], ["end", .50, .38, .96]], look=backdrop("d-empty-dawn", 1.5), panel=PANEL,
           sfx=[SOUND("chime", 0.3, -13)],
           notes="real UI: header flips to Done, stepper Merged lit, PR #432 chip Merged. The music swells here")
if HAVE_A6:
    va, vend = voice("a-6", "Merged.", at=0.2, t_in=0.8, dur=0.95)
    mer["audio"] = [va]
add("18", 2.6, mer)
a, s, e = own("m-dev6", "Amazing. Thank you.")
add("19", e - s + 0.3, dict(ui=False, source="m-dev6", t_in=round(s, 2), look={"backdrop": "none"}, cam=[[0, .5, .5, 1.0], ["end", .5, .5, .97]],
    audio=[a], notes="generated: the smile, then 'Amazing. Thank you.' on camera"))
add("20", 4.2, dict(type="screen", plate=MORN_PLATE, plate_t_in=4.0, source="shot-01-dawn-dpr2-4k", t_in=0.8, cam=[[0, .5, .60, .62], ["end", .5, .54, 1.0]],
    screen={"glow": {"alpha": 0.40}}, sfx=[SOUND("swell", 0.2, -8)],
    notes="real UI: the Workshop at dawn (06:30, run complete): slow pull-back; no caption (the reference has none)"))
add("21", 2.4, dict(ui=False, look={"backdrop": "none"}, fade_out=1.5, title_bloom={"text": "commission-ai", "at": 0.1, "dur": 2.6, "cy": 0.46, "size": 1.3}, notes="end title"))

# ---- beats
shots, b, starts = [], 0, {}
for x in S:
    n = max(2, math.ceil(x["dur"] / BEAT - 1e-9))
    sh = dict(x["shot"])
    sh["beats"] = [b, b + n]
    starts[x["id"]] = b
    b += n
    shots.append(sh)
total = b
swell = starts["20"] + 0.3
join = 48
ENTRY = 140.18
t2 = round(ENTRY - (swell - join), 2)
order = ["id", "beats", "type", "ui", "plate", "plate_t_in", "source", "t_in", "speed", "look", "panel", "cam", "screen", "fade_in", "fade_out", "title_bloom",
         "lower_copy", "audio", "sfx", "notes"]
shots = [{k: s[k] for k in order if k in s} for s in shots]
spec = dict(
    project={"name": "commission-ai-night-shift", "title": "Commission-ai: Night shift (dialogue film)"},
    output={"name": "night-shift", "resolution": 1080, "fps": 30, "duration": round(total * BEAT, 3)},
    paths={"build": "build", "out": "out"}, assets="assets.yaml", footage="../commission-ai-shared/footage/manifest.yaml",
    style={"preset": "cinematic-story", "pacing": {"ui_min_hold_s": 1.4}, "typography": {"serif_fonts": ["/Users/patricklai/promo-footage/fonts/SourceSerif4.ttf"]}},
    music={"asset": "music-eternal-hope", "bpm": BPM, "track_beat": BEAT, "track_offset": OFFSET,
           "edit": {"segments": [[0, 4, 52], [join, t2, round(t2 + total - join, 2)]], "crossfade": 0.03,
                    "gains": [{"beats": [total - 3, total], "db": -30, "ramp": 1.8}], "silence_from_beat": total}},
    timeline={"bpm": BPM, "beats": total},
    shots=shots,
    sfx={"library": {n: {"asset": f"sfx-{n}"} for n in ("tick", "tick2", "chime", "swell", "key0", "key1", "key2", "key3", "key4", "key5", "rain_bed", "room_tone", "thud_soft", "click")}},
    mix={"sr": 48000, "bus_db": {"music": 16.0, "sfx": 10.0, "vo": 1.5}, "vo_line_lufs": -16.0,
         "duck": {"db": 7.0, "attack": 0.1, "release": 0.4, "pre": 0.08, "post": 0.2}, "fade_out": 1.5,
         "masters": [{"name": "web", "suffix": "", "lufs": -16.0, "ceiling": -1.2, "max_true_peak": -1.0}]},
    qa={"vo_max_wer": 0.2, "asr_model": "small.en"},
)
head = ("# commission-ai 'Night shift' v5: the dialogue film (reference: OpenAI 'Introducing dots').\n"
        "# GENERATED by make_spec.py. People scenes + voices are generated (user lifted the real-footage-only rule for this film, brief.yaml conflict 1);\n"
        "# the UI is real recordings. See brief.yaml + reference/dots/DOSSIER.md.\n")
sys.stdout.write(head + yaml.safe_dump(spec, sort_keys=False, default_flow_style=None, width=200, allow_unicode=True))
