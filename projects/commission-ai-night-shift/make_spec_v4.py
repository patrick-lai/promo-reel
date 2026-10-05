"""Night shift v4: the dialogue film (reference: OpenAI 'Introducing dots'; brief.yaml + reference/dots/DOSSIER.md).
Generates promo.yaml so beats, voice timing and the music swell are computed, not hand-added.

    ../../.venv/bin/python make_spec.py > promo.yaml
"""
import hashlib, json, os, sys
import yaml

BPM, BEAT, OFFSET = 100.434, 0.597408, 0.038
HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = {"radius": 22}

def ui(sid, n, source, t_in, cam, plate, plate_t, speed=None, vo=None, sfx=None, notes="", **extra):
    d = dict(id=sid, n=n, type="cinema", source=source, t_in=t_in, cam=cam,
             look={"backdrop": {"plate": plate, "t": plate_t, "blur": 0.03, "dim": 0.62, "warm": 0.12, "parallax": 0.35}},
             panel={"w": 0.86, "cy": 0.5}, notes=notes)
    if speed: d["speed"] = speed
    if sfx: d["sfx"] = sfx
    if vo: d["vo"] = vo
    d.update(extra)
    return d

def scene(sid, n, source, t_in, vo=None, sfx=None, notes="", **extra):
    d = dict(id=sid, n=n, type="cinema", ui=False, source=source, t_in=t_in, look={"backdrop": "none"},
             cam=[[0, 0.5, 0.5, 1.0], ["end", 0.5, 0.5, 0.96]], notes=notes)
    if sfx: d["sfx"] = sfx
    if vo: d["vo"] = vo
    d.update(extra)
    return d

keys = [{"sfx": f"key{i % 6}", "at": round(t, 2), "db": -9} for i, t in enumerate([0.15, 0.35, 0.5, 0.72, 0.9, 1.1, 1.3, 1.42, 1.65, 1.9, 2.1, 2.35, 2.6])]
S = [
    scene("01", 6, "p-window-rain", 0.0, fade_in=1.2, title_bloom={"text": "commission-ai", "at": 1.0, "dur": 2.2, "cy": 0.46, "size": 1.3},
          sfx=[{"sfx": "rain_bed", "at": 0.0, "db": -13}], notes="generated: rainy night window (no people, no UI); title blooms out of the dark like dots"),
    scene("02", 5, "p-hands-keys", 0.5, sfx=keys + [{"sfx": "room_tone", "at": 0.0, "db": -24}], notes="generated: hands typing at night"),
    scene("03", 7, "p-desk-night", 0.3, vo=("DEV-1", 0.25), notes="generated: the dev, tired, tells the laptop what to ship (voice-over, DEV-1)"),
    ui("04", 7, "shot-10b-4k", 0.0, [[0, 0.22, 0.17, 0.30], [1.2, 0.22, 0.17, 0.30], ["end", 0.23, 0.40, 0.36]], "p-desk-night", 3.0, speed=0.45,
       vo=("AGENT-1", 0.2), sfx=[{"sfx": "rain_bed", "at": 0.85, "db": -13}],
       notes="real UI: composer bubble 'Ship the checkout revamp tonight. No broken builds.' then the plan 'eight checkout tickets in three waves' (AGENT-1)"),
    ui("05", 5, "shot-04p-4k", 0.5, [[0, 0.40, 0.40, 0.90], ["end", 0.40, 0.42, 0.80]], "p-desk-night", 3.0,
       notes="real UI: board, Wave 1/2/3, 8 tickets (PAY-103..PAY-110)"),
    scene("06", 6, "p-desk-night", 3.2, sfx=[{"sfx": "thud_soft", "at": 1.0, "db": -6}], notes="generated: she closes the laptop and lets out a breath"),
    scene("07", 5, "p-desk-empty-glow", 0.5, sfx=[{"sfx": "rain_bed", "at": 1.7, "db": -13}], notes="generated: empty desk, laptop glowing, rain: the night shift"),
    ui("08", 6, "shot-01-dusk-4k", 6.8, [[0, 0.5, 0.58, 0.72], ["end", 0.5, 0.56, 0.64]], "p-desk-empty-glow", 2.5,
       notes="real UI: the Workshop at night, agents at work (header bar cropped out)"),
    ui("09", 6, "shot-08-dpr2", 0.8, [[0, 0.55, 0.38, 0.86], ["end", 0.56, 0.38, 0.78]], "p-desk-empty-glow", 2.5,
       sfx=[{"sfx": "tick", "at": 0.8, "db": -10}, {"sfx": "tick2", "at": 1.9, "db": -10}, {"sfx": "tick", "at": 2.9, "db": -10}],
       notes="real UI: PAY-104 drawer Running/Verifying, stepper Coding -> Checks"),
    scene("10", 6, "p-dawn-curtains", 0.5, notes="generated: morning light through the curtains, same office"),
    scene("11", 6, "p-coffee-morning", 0.3, notes="generated: she pours coffee, calm morning"),
    scene("12", 6, "p-sits-morning", 0.5, vo=("AGENT-2", 0.5), sfx=[{"sfx": "chime", "at": 0.1, "db": -9}],
          notes="generated: she sits at the desk and looks at the laptop (AGENT-2: 'Good morning. One command needs your approval.')"),
    ui("13", 7, "shot-10b-4k", 1.6, [[0, 0.56, 0.80, 0.42], ["end", 0.56, 0.80, 0.36]], "p-sits-morning", 3.5, vo=("DEV-2", 1.3),
       sfx=[{"sfx": "click", "at": 1.55, "db": -8}],
       notes="real UI: PAY-106 'Needs you' + the real click on Allow once (DEV-2 'Allow once.')"),
    ui("14", 4, "shot-merged-drawer-dpr2", 0.3, [[0, 0.72, 0.30, 0.52], ["end", 0.72, 0.30, 0.46]], "p-sits-morning", 4.0, vo=("AGENT-3", 0.15),
       notes="real UI: drawer, stepper at PR raised, PR #432 (AGENT-3 'Pull request four thirty-two is open. The reviewer approved it.')"),
    ui("15", 4, "shot-12b-4k", 1.0, [[0, 0.46, 0.60, 0.92], ["end", 0.46, 0.62, 0.88]], "p-sits-morning", 4.0,
       notes="real UI: reviewer line 'Approved. Cart summary uses the pricing engine matches the plan'"),
    ui("16", 4, "shot-merged-drawer-dpr2", 3.6, [[0, 0.72, 0.30, 0.50], ["end", 0.72, 0.31, 0.46]], "p-face-screenlight", 3.0, vo=("AGENT-4", 0.35),
       sfx=[{"sfx": "chime", "at": 0.45, "db": -6}, {"sfx": "swell", "at": 0.3, "db": -10}],
       notes="real UI: header flips to Done, stepper Merged lit, PR #432 chip Merged (AGENT-4 'And it's merged.'); the music swells here"),
    scene("17", 5, "p-face-screenlight", 1.0, vo=("DEV-3", 0.7), notes="generated: her face lit by the screen, a quiet smile (DEV-3 'Amazing.')"),
    ui("18", 6, "shot-01-dawn-dpr2-4k", 0.8, [[0, 0.5, 0.60, 0.62], ["end", 0.5, 0.56, 0.80]], "p-dawn-curtains", 2.0,
       lower_copy=[{"text": "Tell it at night. Wake up to merged PRs.", "at": 0.6, "dur": 2.6, "align": "center", "size": 1.4}],
       notes="real UI: the Workshop at dawn (06:30, run complete); the pitch line from the brief, owner to confirm"),
    scene("19", 5, "", 0.0, fade_out=1.5, title_bloom={"text": "commission-ai", "at": 0.1, "dur": 2.6, "cy": 0.46, "size": 1.3},
          notes="end title"),
]
S[-1].pop("source"); S[-1].pop("t_in"); S[-1].pop("cam")
total = sum(s["n"] for s in S)
swell_at = 86  # edit beat where the Merged flip lands (shot 16 starts at beat 86)
starts, b = {}, 0
for s in S:
    starts[s["id"]] = b
    b += s["n"]
assert starts["16"] == swell_at, starts
ENTRY_TRACK_BEAT = 140.18
join = 48
t2 = round(ENTRY_TRACK_BEAT - (swell_at + 0.6 - join), 2)   # entry ~0.6 beat into the Merged shot

shots, vo_lines = [], []
vo_json = json.load(open(os.path.join(HERE, "audio/vo/lines.json")))
vo_by_id = {l["id"]: l for l in vo_json["lines"]}
for s in S:
    n = s.pop("n"); b0 = starts[s["id"]]
    vo = s.pop("vo", None)
    if vo:
        vid, at = vo
        l = vo_by_id[vid]
        vo_lines.append(dict(id=vid, shot=s["id"], at=at, file=f"{vid}.wav", text=l["text"], host=l["role"].title(),
                             sha256=hashlib.sha256(open(os.path.join(HERE, "audio/vo", f"{vid}.wav"), "rb").read()).hexdigest()))
    d = dict(id=s["id"], beats=[b0, b0 + n], type="cinema")
    for k in ("ui", "source", "t_in", "speed", "look", "panel", "cam", "fade_in", "fade_out", "title_bloom", "lower_copy", "sfx", "notes"):
        if k in s: d[k] = s[k]
    shots.append(d)
for v in vo_lines:
    if v["id"] == "AGENT-3": v["asr_aliases"] = {"432": "four thirty-two"}
    if v["id"] == "DEV-1": v["asr_aliases"] = {"revamped": "revamp"}

spec = dict(
    project={"name": "commission-ai-night-shift", "title": "Commission-ai: Night shift (dialogue film)"},
    output={"name": "night-shift", "resolution": 1080, "fps": 30, "duration": round(total * BEAT, 3)},
    paths={"build": "build", "out": "out"}, assets="assets.yaml", footage="../commission-ai-shared/footage/manifest.yaml",
    style={"preset": "cinematic-story", "pacing": {"ui_min_hold_s": 1.8}, "typography": {"serif_fonts": ["/Users/patricklai/promo-footage/fonts/SourceSerif4.ttf"]}},
    music={"asset": "music-eternal-hope", "bpm": BPM, "track_beat": BEAT, "track_offset": OFFSET,
           "edit": {"segments": [[0, 4, 52], [join, t2, round(t2 + total - join, 2)]], "crossfade": 0.03,
                    "gains": [{"beats": [total - 3, total], "db": -30, "ramp": 1.8}], "silence_from_beat": total}},
    timeline={"bpm": BPM, "beats": total},
    vo={"engine": "files", "asset": "vo-night-shift", "model_asset": "kokoro-model", "voices_asset": "kokoro-voices", "lines": vo_lines},
    shots=shots,
    sfx={"library": {n: {"asset": f"sfx-{n}"} for n in ("tick", "tick2", "chime", "swell", "key0", "key1", "key2", "key3", "key4", "key5", "rain_bed", "room_tone", "thud_soft", "click")}},
    mix={"sr": 48000, "bus_db": {"music": 16.0, "sfx": 10.0, "vo": 1.5}, "vo_line_lufs": -16.0,
         "duck": {"db": 8.0, "attack": 0.12, "release": 0.5, "pre": 0.1, "post": 0.2}, "fade_out": 1.5,
         "masters": [{"name": "web", "suffix": "", "lufs": -16.0, "ceiling": -1.2, "max_true_peak": -1.0}]},
    qa={"vo_max_wer": 0.0, "asr_model": "small.en"},
)
head = ("# commission-ai 'Night shift' v4: the dialogue film (reference: OpenAI 'Introducing dots').\n"
        "# GENERATED by make_spec.py (beats, voice timing and the music swell are computed). See brief.yaml + reference/dots/DOSSIER.md.\n"
        "# People scenes are generated (user lifted the real-footage-only rule for this film, brief.yaml conflict 1); UI is real recordings.\n")
sys.stdout.write(head + yaml.safe_dump(spec, sort_keys=False, default_flow_style=None, width=200, allow_unicode=True))
