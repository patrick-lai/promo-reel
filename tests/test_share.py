import json
import os
import stat

import pytest

from promo import flow as F
from promo import share as SH

FAKE_TWG = '''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
assert args[:4] == ["-o", "json", "--output-summary", "none"], args
cmd = args[4:]
log = os.environ["FAKE_TWG_LOG"]
calls = [json.loads(x) for x in open(log)] if os.path.exists(log) else []
open(log, "a").write(json.dumps(cmd) + "\\n")
def out(data):
    print(json.dumps({"apiVersion": "v2", "data": data}))
def fail(msg, code=1):
    print('error:\\n  message: "%s"' % msg, file=sys.stderr)
    sys.exit(code)
if cmd[:3] == ["artifacts", "file", "list"]:
    out({"artifacts": []})
elif cmd[:3] == ["loom", "space", "query"]:
    out({"spaces": []}) if os.environ.get("FAKE_LOOM") else fail("No Loom workspace for site data")
elif cmd[:3] == ["artifacts", "file", "create"]:
    if os.environ.get("FAKE_UPLOAD_FAILS"):
        fail("storage refused the file")
    n = sum(1 for c in calls if c[:3] == ["artifacts", "file", "create"]) + 1
    out({"artifact": {"id": "art-%d" % n, "artifactUrl": "https://site.example/artifacts/art-%d" % n}})
elif cmd[:3] == ["artifacts", "file", "update"]:
    out({"artifact": {"id": cmd[3], "artifactUrl": "https://site.example/artifacts/" + cmd[3]}})
elif cmd[:3] == ["loom", "video", "upload"]:
    n = sum(1 for c in calls if c[:3] == ["loom", "video", "upload"]) + 1
    out({"video": {"shareUrl": "https://www.loom.com/share/loom%d" % n}})
else:
    fail("unexpected " + " ".join(cmd), 2)
'''


@pytest.fixture
def twg(tmp_path, monkeypatch):
    exe = tmp_path / "twg"
    exe.write_text(FAKE_TWG)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "twg-calls.jsonl"
    monkeypatch.setenv("PROMO_TWG", str(exe))
    monkeypatch.setenv("FAKE_TWG_LOG", str(log))

    def calls(*prefix):
        rows = [json.loads(x) for x in open(log)] if log.exists() else []
        return [c for c in rows if c[:len(prefix)] == list(prefix)]
    return calls


@pytest.fixture
def pd(tmp_path):
    d = str(tmp_path / "acme-promo")
    F.init(d, "Make a 60s promo for Acme Tasks: tell it at night, wake up to merged PRs.")
    return d


def video(pd, name, body):
    p = os.path.join(pd, "out", name)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(body)
    return p


def register(pd, drafts=(), finals=()):
    st = F.load(pd)
    st.update(stage="final" if finals else "review", drafts=[dict(file=f, note=n, at="", cycle=1) for f, n in drafts], finals=[dict(file=f, at="") for f in finals])
    F.save(pd, st)


def test_uploads_are_offered_only_where_twg_says_the_product_is_there(pd, twg, monkeypatch):
    register(pd, drafts=[(video(pd, "d1.mp4", b"one"), "")])
    assert F.snapshot(pd)["share"]["destinations"] == []
    F.share_detect(pd)
    assert [d["id"] for d in F.snapshot(pd)["share"]["destinations"]] == ["artifacts"]
    monkeypatch.setenv("FAKE_LOOM", "1")
    F.share_detect(pd, force=True)
    assert [d["id"] for d in F.snapshot(pd)["share"]["destinations"]] == ["artifacts", "loom"]
    monkeypatch.setenv("PROMO_TWG", "/nowhere/twg")
    F.share_detect(pd, force=True)
    assert F.snapshot(pd)["share"]["destinations"] == []


def test_an_edited_draft_is_refreshed_in_place_under_its_own_name(pd, twg):
    f1, f2 = video(pd, "d1.mp4", b"one"), video(pd, "d2.mp4", b"two")
    register(pd, drafts=[(f1, ""), (f2, "Hook shortened.")])
    n, rec, what = F.share_upload(pd, "draft", 2, "artifacts", "Sam")
    create = twg("artifacts", "file", "create")[0]
    assert (n, what, rec["name"]) == (2, "created", "acme-promo_draft_2")
    assert create[create.index("--name") + 1] == "acme-promo_draft_2.mp4"
    assert create[create.index("--type") + 1] == "video/mp4" and create[create.index("--access") + 1] == "private"
    assert "Hook shortened." in create[create.index("--description") + 1]
    shared = F.snapshot(pd)["drafts"][1]["shared"]["artifacts"]
    assert shared["url"] == "https://site.example/artifacts/art-1" and not shared["edited"]

    open(f2, "wb").write(b"two, edited")
    assert F.snapshot(pd)["drafts"][1]["shared"]["artifacts"]["edited"]
    _, rec, what = F.share_upload(pd, "draft", 2, "artifacts", "Sam")
    update = twg("artifacts", "file", "update")[0]
    assert what == "updated" and rec["url"] == shared["url"] and update[3] == "art-1" and update[4] == f2
    assert update[update.index("--name") + 1] == "acme-promo_draft_2.mp4" and "--access" not in update
    assert len(twg("artifacts", "file", "create")) == 1 and not F.snapshot(pd)["drafts"][1]["shared"]["artifacts"]["edited"]

    assert F.share_upload(pd, "draft", 2, "artifacts", "Sam")[2] == "unchanged"
    assert len(twg("artifacts", "file", "update")) == 1
    assert F.snapshot(pd)["drafts"][0]["shared"] == {}


def test_every_final_is_the_next_version_and_never_overwritten(pd, twg):
    f1, f2 = video(pd, "final-a.mp4", b"first"), video(pd, "final-b.mp4", b"second")
    register(pd, finals=[f1, f2])
    assert F.share_upload(pd, "final", 1, "artifacts", "Sam")[1]["name"] == "acme-promo_final_v1"
    assert F.share_upload(pd, "final", None, "artifacts", "Sam")[1]["name"] == "acme-promo_final_v2"
    assert [x["share_as"] for x in F.snapshot(pd)["finals"]] == ["acme-promo_final_v1", "acme-promo_final_v2"]
    open(f1, "wb").write(b"first, edited")
    with pytest.raises(SH.ShareError, match="final add"):
        F.share_upload(pd, "final", 1, "artifacts", "Sam")
    assert twg("artifacts", "file", "update") == []


def test_loom_cannot_replace_so_it_keeps_the_older_links(pd, twg, monkeypatch):
    monkeypatch.setenv("FAKE_LOOM", "1")
    f = video(pd, "d1.mp4", b"one")
    register(pd, drafts=[(f, "")])
    F.share_upload(pd, "draft", 1, "loom", "Sam")
    open(f, "wb").write(b"one, edited")
    _, rec, what = F.share_upload(pd, "draft", 1, "loom", "Sam")
    assert what == "updated" and rec["url"] == "https://www.loom.com/share/loom2" and rec["previous"] == ["https://www.loom.com/share/loom1"]
    assert twg("loom", "video", "upload")[0][-2:] == ["--title", "acme-promo_draft_1"]


def test_only_a_person_starts_an_upload_and_a_failed_one_is_not_recorded(pd, twg, monkeypatch):
    register(pd, drafts=[(video(pd, "d1.mp4", b"one"), "")])
    with pytest.raises(F.FlowError, match="agent"):
        F.share_upload(pd, "draft", 1, "artifacts", "Claude")
    assert twg("artifacts", "file", "create") == []
    monkeypatch.setenv("FAKE_UPLOAD_FAILS", "1")
    with pytest.raises(SH.ShareError, match="storage refused the file"):
        F.share_upload(pd, "draft", 1, "artifacts", "Sam")
    assert not F.load(pd).get("shares", {}).get("draft-1")
    assert F.main(["--project", pd, "share", "draft", "--to", "artifacts", "--by", "Sam"]) == 1
