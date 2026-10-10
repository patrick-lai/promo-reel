"""The Stage's timeline editor (promo/editor.py): the edit language, edits applied to promo.yaml as text, drafts that keep their own file, and
the build cache that makes a re-render after an edit cheap."""
import json
import re
import os
import subprocess
import types

import pytest
import yaml

from promo import cli
from promo import editor as E
from promo import flow as F
from promo.cache import Stamps

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = json.load(open(os.path.join(HERE, "edit-cases.json")))


def subset(want, got, path="$"):
    if isinstance(want, dict):
        assert isinstance(got, dict), f"{path}: {got!r}"
        for k, v in want.items():
            assert k in got, f"{path}.{k} missing in {got!r}"
            subset(v, got[k], f"{path}.{k}")
    elif isinstance(want, list):
        more = bool(want) and want[-1] == "..."          # a list ending in "..." only checks its first items
        want = want[:-1] if more else want
        assert isinstance(got, list) and (len(got) >= len(want) if more else len(got) == len(want)), f"{path}: {got!r} has {len(got)} items, expected {len(want)}"
        for i, v in enumerate(want):
            subset(v, got[i], f"{path}[{i}]")
    else:
        assert want == got, f"{path}: {got!r} != {want!r}"


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["name"] for c in CASES["cases"]])
def test_shared_edit_cases(case):
    """The same cases run through PF.editApply in mods/promo-flow/test/logic.test.js: preview and render make the same edit."""
    if "error" in case:
        with pytest.raises(E.EditError, match=re.escape(case["error"])):
            E.apply_ops(CASES["spec"], E.parse(case["ops"]), CASES["B"])
        return
    got, _ = E.apply_ops(CASES["spec"], E.parse(case["ops"]), CASES["B"])
    subset(case["expect"], got)
    for path in case.get("absent", []):
        x = got
        for k in path[:-1]:
            x = x[k]
        assert path[-1] not in x, f"{path} should be gone"
    assert CASES["spec"]["shots"][0]["beats"] == [0, 8]          # the input is never changed in place


@pytest.mark.parametrize("case", CASES["parse"], ids=[c["text"][:30] or "empty" for c in CASES["parse"]])
def test_shared_parse_cases(case):
    if "error" in case:
        with pytest.raises(E.EditError, match=case["error"]):
            E.parse(case["text"])
        return
    ops = [{k: v for k, v in o.items() if k != "_n"} for o in E.parse(case["text"])]
    assert ops == case["ops"]
    assert [{k: v for k, v in o.items() if k != "_n"} for o in E.parse(E.text_of(E.parse(case["text"])))] == ops      # text round trip


# ---------------------------------------------------------------- a small real project
SPEC = """# A test promo. This comment must survive every edit.
project: {name: ed, title: Editor test}
output: {name: ed, resolution: 1080, fps: 30, duration: 8.0}   # 16 beats at 120
paths: {build: build, out: out}
assets: assets.yaml
footage: footage/manifest.yaml
timeline: {bpm: 120, beats: 16}
music:
  asset: music-a
  bpm: 120
  track_beat: 0.5
  track_offset: 0.0
  edit:
    segments: [[0, 0, 16]]
    crossfade: 0.03
    gains: []
sfx:
  library:
    hit: {asset: sfx-hit}
mix:
  bus_db: {music: -5.0, sfx: -8.0, vo: 1.5}    # levels
shots:
  # the opening
  - id: "01"
    beats: [0, 8]
    type: clip
    source: rec-a      # first take
    t_in: 0.0
    overlays:
      - {type: caption, text: "Tell it.", t: [0, 2.5]}
  - id: "02"
    beats: [8, 16]
    type: clip
    source: rec-b
    sfx:
      - {sfx: hit, at: 0.5, db: -5}
"""
ASSETS = """assets:
- id: music-a
  kind: music
  path: media/music/a.wav
  licence: CC0-1.0
  source_url: https://example.com/a
- id: sfx-hit
  kind: sfx
  path: media/sfx/hit.wav
  licence: CC0-1.0
  source_url: https://example.com/hit
"""


def wav(p, secs=1.0):
    import numpy as np
    import soundfile as sf
    os.makedirs(os.path.dirname(p), exist_ok=True)
    sf.write(p, (0.1 * np.sin(np.linspace(0, 440 * 6.28 * secs, int(48000 * secs)))).astype("float32"), 48000)


def clip(p):
    with open(p, "wb") as f:
        f.write(os.urandom(64) + p.encode())


def project(root, name="ed"):
    pd = os.path.join(root, name)
    os.makedirs(os.path.join(pd, "footage"))
    open(os.path.join(pd, "promo.yaml"), "w").write(SPEC.replace("name: ed", f"name: {name}"))
    open(os.path.join(pd, "assets.yaml"), "w").write(ASSETS)
    wav(os.path.join(pd, "media", "music", "a.wav"))
    wav(os.path.join(pd, "media", "sfx", "hit.wav"), 0.2)
    from promo import footage as FT
    clips = []
    for cid in ("rec-a", "rec-b", "rec-c"):
        p = os.path.join(pd, "footage", cid + ".mov")
        clip(p)
        clips.append(dict(id=cid, shots=[], path=p, sha256=E._sha_file(p), app_commit="abc", capture="test", framing="full", resolution="3840x2160", dpr=2, fps=30, demo=False))
    with open(os.path.join(pd, "footage", "manifest.yaml"), "w") as f:
        yaml.safe_dump({"clips": clips}, f, sort_keys=False)
    F.init(pd, "Make a test promo.")
    st = F.load(pd)
    st["stage"] = "drafts"
    F.save(pd, st)
    return pd


@pytest.fixture
def pd(tmp_path, monkeypatch):
    monkeypatch.setenv("PROMO_PROJECTS", str(tmp_path / "projects"))
    return project(str(tmp_path / "projects"))


def test_apply_keeps_comments_and_touches_only_what_changed(pd):
    before = open(os.path.join(pd, "promo.yaml")).read()
    ops, k = E.apply(pd, 'swap 01 rec-c t_in=1.5\ncaption 01 "Say it once."\nbus music -3', "Sam")
    after = open(os.path.join(pd, "promo.yaml")).read()
    for comment in ("# A test promo. This comment must survive every edit.", "# 16 beats at 120", "# levels", "# the opening", "# first take"):
        assert comment in after
    changed = [ln for ln in after.splitlines() if ln not in before.splitlines()]
    assert changed == ["  bus_db: {music: -3, sfx: -8.0, vo: 1.5}    # levels", "    source: rec-c      # first take", "    t_in: 1.5",
                       "      - {type: caption, text: Say it once., t: [0, 2.5]}"], changed
    raw = yaml.safe_load(after)
    assert raw["shots"][0]["source"] == "rec-c" and raw["shots"][0]["overlays"][0]["text"] == "Say it once." and raw["mix"]["bus_db"]["music"] == -3
    st = F.load(pd)
    assert st["restores"][-1]["undo"] == k and st["restores"][-1]["what"].startswith("Edited in the editor")
    F.main(["--project", pd, "restore", "--undo", str(k), "--by", "Sam"])           # the edit is undone like any restore
    assert open(os.path.join(pd, "promo.yaml")).read() == before
    assert json.loads(open(os.path.join(pd, "flow", "edit", "log.jsonl")).readline())["text"].startswith("swap 01 rec-c")


def test_an_asset_without_a_licence_is_refused_and_nothing_changes(pd, tmp_path):
    before = {f: open(os.path.join(pd, f)).read() for f in ("promo.yaml", "assets.yaml")}
    song = str(tmp_path / "song.wav")
    wav(song)
    with pytest.raises(E.EditError, match="licence"):
        E.apply(pd, f"import {song} kind=music licence= source=https://x", "Sam")
    with pytest.raises(E.EditError):              # an id the manifest does not have: the gates refuse it and promo.yaml is put back
        E.apply(pd, "music music-nope", "Sam")
    assert {f: open(os.path.join(pd, f)).read() for f in before} == before
    fid, what = E.import_file(pd, song, "music", "My own recording", "recorded at home", "Sam")
    row = next(r for r in E._assets_rows(pd) if r["id"] == fid)
    assert row["licence"].startswith("My own recording (Sam)") and row["source_url"] == "recorded at home" and len(row["sha256"]) == 64
    E.apply(pd, f"music {fid} offset=0.5", "Sam")
    assert yaml.safe_load(open(os.path.join(pd, "promo.yaml")))["music"]["asset"] == fid


def test_cross_project_swap_copies_the_manifest_entry_with_its_sha(pd, tmp_path):
    other = project(str(tmp_path / "projects"), "jev")
    src = yaml.safe_load(open(os.path.join(other, "footage", "manifest.yaml")))["clips"][1]
    E.apply(pd, "swap 02 jev:rec-b", "Sam")
    here = {c["id"]: c for c in yaml.safe_load(open(os.path.join(pd, "footage", "manifest.yaml")))["clips"]}
    assert here["jev-rec-b"]["sha256"] == src["sha256"] and here["jev-rec-b"]["path"] == src["path"]
    assert yaml.safe_load(open(os.path.join(pd, "promo.yaml")))["shots"][1]["source"] == "jev-rec-b"
    E.apply(pd, "music jev:music-a", "Sam")                 # its music: the file comes over with its licence and source
    row = next(r for r in E._assets_rows(pd) if r["id"] == "jev-music-a")
    assert row["licence"] == "CC0-1.0" and row["source_url"] == "https://example.com/a" and os.path.isfile(os.path.join(pd, row["path"]))
    b = E.bin_(pd)
    assert [p["name"] for p in b["projects"]] == ["jev"] and b["projects"][0]["items"] == []          # closed: names and counts only
    E.open_bin(pd, "jev")
    assert any(it["media"] for it in E.bin_(pd)["projects"][0]["items"])


def test_every_draft_keeps_its_own_file(pd):
    out = os.path.join(pd, "out", "ed-1080.mp4")
    os.makedirs(os.path.dirname(out))
    for n, body in ((1, b"first cut"), (2, b"second cut")):
        if os.path.exists(out):
            os.remove(out)          # what `promo build` does now before it assembles
        open(out, "wb").write(body)
        assert F.add_draft(pd, out, f"cut {n}") == n
    st = F.load(pd)
    assert [open(d["file"], "rb").read() for d in st["drafts"]] == [b"first cut", b"second cut"]
    assert st["drafts"][0]["file"].endswith(os.path.join("flow", "drafts", "d1.mp4")) and st["drafts"][0]["source"] == out
    with open(out, "wb") as f:      # even a tool that rewrites the out/ file in place leaves the drafts alone
        f.write(b"rewritten in place")
    assert open(F.load(pd)["drafts"][1]["file"], "rb").read() == b"second cut"


def test_render_applies_builds_checks_and_registers_the_draft(pd, monkeypatch):
    calls = []

    def fake_main(argv):
        calls.append(argv[2:])
        if argv[2] == "build":
            os.makedirs(os.path.join(pd, "out"), exist_ok=True)
            open(os.path.join(pd, "out", "ed-1080.mp4"), "wb").write(b"video " + str(len(calls)).encode())
        return 0
    monkeypatch.setattr(cli, "main", fake_main)
    n = E.render(pd, "bus music -2", "Sam")
    assert n == 1 and calls == [["build"], ["check", "--json"]]
    assert yaml.safe_load(open(os.path.join(pd, "promo.yaml")))["mix"]["bus_db"]["music"] == -2
    n2 = E.render(pd, "bus music -1", "Sam")
    st = F.load(pd)
    assert n2 == 2 and open(st["drafts"][0]["file"], "rb").read() != open(st["drafts"][1]["file"], "rb").read()


def test_suggestions_are_checked_then_kept(pd):
    sid = E.suggest(pd, "bus music -8\ncaption 01 \"Quiet start.\"", "Quieter music under the opening")
    assert F.load(pd)["edit"]["suggestions"][0]["text"] == 'bus music -8\ncaption 01 "Quiet start."'
    with pytest.raises(E.EditError, match="no shot 09"):
        E.suggest(pd, "delete 09", "nope")
    E.keep(pd, sid, "Sam")
    assert F.load(pd)["edit"]["suggestions"][0]["kept"]["by"] == "Sam"
    with pytest.raises(F.FlowError):
        E.keep(pd, sid, "Claude")          # an agent cannot keep for the person


def test_replay_puts_logged_edits_back_on_a_regenerated_spec(pd):
    sp = os.path.join(pd, "promo.yaml")
    gen = "# GENERATED by tools/gen_spec.py: edit that, not this file.\n" + open(sp).read()
    open(sp, "w").write(gen)
    assert E.generated(pd) == "tools/gen_spec.py"
    E.apply(pd, "bus music -2\nswap 02 rec-c", "Sam")
    assert E.replay(pd, "Sam") == 0                # already there
    open(sp, "w").write(gen)                         # the generator ran again
    assert E.replay(pd, "Sam") == 1
    raw = yaml.safe_load(open(sp))
    assert raw["mix"]["bus_db"]["music"] == -2 and raw["shots"][1]["source"] == "rec-c"


# ---------------------------------------------------------------- the build cache
def _spec(pd):
    from promo.spec import load_spec
    return load_spec(os.path.join(pd, "promo.yaml"))


def test_shot_digest_ignores_sound_cues_and_a_move_of_a_built_in_shot(pd):
    s0 = _spec(pd)
    d01, d02 = (cli.shot_digest(s0, s) for s in s0.shots)
    E.apply(pd, 'sfx 02 add hit at=1.0 db=-3', "Sam")
    assert cli.shot_digest(_spec(pd), _spec(pd).shots[1]) == d02            # a sound effect is the mix's business
    E.apply(pd, "move 02 before=01", "Sam")
    s1 = _spec(pd)
    moved = {s.id: cli.shot_digest(s1, s) for s in s1.shots}
    assert moved["02"] == d02 and moved["01"] == d01 and [s.id for s in s1.shots] == ["02", "01"]
    E.apply(pd, "trim 02 end=6", "Sam")
    s2 = _spec(pd)
    assert {s.id: cli.shot_digest(s2, s) for s in s2.shots} != moved          # a length change re-renders both sides of the cut
    assert cli.shot_digest(s0, s0.shots[0], legacy=True) != d01               # the old formula kept absolute beats


def _shot_step(spec, sid):
    return next(st for st in cli.plan(spec) if st["name"] == f"shot {sid}")


def test_a_segment_cache_hit_skips_the_render_and_a_legacy_stamp_counts_once(pd, monkeypatch):
    spec = _spec(pd)
    st = _shot_step(spec, "01")
    renders = []

    def fake_run(a):
        os.makedirs(spec.segs_dir, exist_ok=True)
        if os.path.exists(spec.seg_path("01")):
            os.remove(spec.seg_path("01"))
        open(spec.seg_path("01"), "wb").write(b"seg rec-a")
        renders.append(1)
    st["run"] = fake_run
    args = types.SimpleNamespace(force=False)
    assert cli.run_step(spec, args, st) is True and len(renders) == 1
    E.apply(pd, "swap 01 rec-c", "Sam")
    spec2 = _spec(pd)
    st2 = _shot_step(spec2, "01")
    st2["run"] = lambda a: (os.remove(spec2.seg_path("01")), open(spec2.seg_path("01"), "wb").write(b"seg rec-c"), renders.append(2))
    assert cli.run_step(spec2, args, st2) is True and len(renders) == 2
    E.apply(pd, "swap 01 rec-a", "Sam")             # swapped back: the first render comes back from the cache, nothing renders
    spec3 = _spec(pd)
    st3 = _shot_step(spec3, "01")
    st3["run"] = lambda a: renders.append(3)
    assert cli.run_step(spec3, args, st3) is False and len(renders) == 2
    assert open(spec3.seg_path("01"), "rb").read() == b"seg rec-a"
    # a stamp written by the old formula is accepted once and rewritten with the new digest
    stamps = Stamps(spec3.build)
    stamps.write(st3["key"], st3["legacy"](), at=0, secs=12.0)
    assert cli.run_step(spec3, args, st3) is False and len(renders) == 2
    assert stamps.get(st3["key"])["digest"] == st3["dig"]() and stamps.get(st3["key"])["secs"] == 12.0


def test_cli_edit_commands(pd, capsys):
    assert F.main(["--project", pd, "edit", "apply", "caption 02 \"Then it plans.\"", "--by", "Sam"]) == 0
    assert "applied 1 edit" in capsys.readouterr().out
    assert F.main(["--project", pd, "edit", "apply", "delete 07", "--by", "Sam"]) == 1
    assert "there is no shot 07" in capsys.readouterr().err
    assert F.main(["--project", pd, "edit", "suggest", "bus vo 2", "--note", "Louder voice"]) == 0
    snap = F.snapshot(pd)
    assert snap["edit"]["suggestions"][0]["note"] == "Louder voice" and [s["id"] for s in snap["edit"]["shots"]] == ["01", "02"]
    assert snap["edit"]["shots"][1]["caption"] == "Then it plans." and snap["bin"]["here"]


def test_mute_drops_the_line_from_events_and_db_sets_its_level(pd):
    from promo import events, mix
    sp = os.path.join(pd, "promo.yaml")
    with open(sp, "a") as f:
        f.write("vo:\n  engine: kokoro\n  lines:\n  - {shot: '01', at: 0.5, text: Tell it.}\n  - {shot: '02', at: 0.2, text: It plans.}\n")
    E.apply(pd, "vo 01 mute\nvo 02 db=-4", "Sam")
    ev = events.compute_events(_spec(pd))
    assert list(ev["vo"]) == ["02"]
    assert mix.vo_line_gain_db({"vo_line_lufs": -16}, {"db": -4}, -20.0) == 0.0


def test_the_agent_reads_the_timeline_and_dry_runs_an_edit_without_writing(pd):
    txt = E.timeline_text(pd)
    assert "SHOT" in txt and '"Tell it."' in txt and "MUSIC music-a" in txt and "[1] hit@0.5 -5dB" in txt
    before = open(os.path.join(pd, "promo.yaml")).read()
    diff, runs, already = E.dry_run(pd, "caption 02 \"It plans.\"\nbus music -2")
    assert open(os.path.join(pd, "promo.yaml")).read() == before
    assert "+      text: It plans." in diff and "+  bus_db: {music: -2, sfx: -8.0, vo: 1.5}    # levels" in diff
    assert "shot 02" in runs and "shot 02" in already          # nothing is built in this test project yet: every step was already due


def test_grade_and_fade_are_ffmpeg_filters_on_the_cached_render(pd, monkeypatch):
    with open(os.path.join(pd, "promo.yaml")) as f:
        txt = f.read()
    open(os.path.join(pd, "promo.yaml"), "w").write(txt.replace('    source: rec-b\n', '    source: rec-b\n    ui: false\n'))
    spec = _spec(pd)
    st = _shot_step(spec, "02")
    renders, posts = [], []

    def render(a):
        os.makedirs(spec.segs_dir, exist_ok=True)
        open(spec.seg_path("02"), "wb").write(b"raw")
        renders.append(1)
    st["run"] = render
    args = types.SimpleNamespace(force=False)
    cli.run_step(spec, args, st)
    E.apply(pd, "grade 02 contrast=1.2 temperature=5600\nfade 02 out=0.5", "Sam")
    spec2 = _spec(pd)
    assert cli.post_filter(spec2.shot("02").cfg, 4.0) == "eq=contrast=1.2,colortemperature=temperature=5600,fade=t=out:st=3.500:d=0.5"
    st2 = _shot_step(spec2, "02")
    st2["run"] = lambda a: renders.append(2)
    st2["post"] = lambda: posts.append(open(spec2.seg_path("02"), "rb").read())
    assert st2["raw"]() == st["dig"]()                   # the ungraded render is the one already cached
    cli.run_step(spec2, args, st2)
    assert renders == [1] and posts == [b"raw"]         # graded from the cache, not rendered again
    with pytest.raises(E.EditError, match="never graded"):
        E.apply(pd, "grade 01 contrast=1.1", "Sam")
