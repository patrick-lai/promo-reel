import json
import os

import pytest
from PIL import Image

from promo import flow as F
from promo import widgets as WG

BLOCKS = json.dumps({"blocks": [
    {"type": "stats", "items": [{"label": "Frames", "value": 240}]},
    {"type": "table", "columns": ["Shot", "Status"], "rows": [["01", "done"], ["02", "queued"]]},
    {"type": "image", "file": "turntable.png", "caption": "Frame 120"},
]})


@pytest.fixture
def pd(tmp_path):
    d = str(tmp_path / "proj")
    F.init(d, "Make a promo for a Blender add-on.")
    return d


@pytest.fixture
def png(tmp_path):
    p = tmp_path / "turntable.png"
    Image.new("RGB", (32, 18), (10, 20, 30)).save(p)
    return str(p)


def widgets(pd):
    return {w["id"]: w for w in F.snapshot(pd)["widgets"]}


def test_a_blocks_widget_reaches_the_stage_with_its_attached_image_as_a_host_file(pd, png):
    F.widget_put(pd, "queue", "Render queue", text=BLOCKS, attach=[png], span=6, height="l")
    w = widgets(pd)["queue"]
    assert (w["kind"], w["place"], w["span"], w["height"]) == ("blocks", "workbench", 6, "l")
    image = w["blocks"][2]
    assert image["file"] == {"$file": os.path.abspath(os.path.join(pd, "flow", "widgets", "queue", "files", "turntable.png"))}
    assert w["blocks"][0]["items"][0]["value"] == "240"        # numbers are drawn as text


def test_an_html_widget_arrives_with_its_text_files_inline_and_media_as_files(pd, png, tmp_path):
    mesh = tmp_path / "cube.obj"
    mesh.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    F.widget_put(pd, "viewer", "Mesh", text="<canvas id=c></canvas><script>promo.ready(() => {})</script>", attach=[f"mesh.obj={mesh}", png])
    w = widgets(pd)["viewer"]
    assert w["kind"] == "html" and "promo.ready" in w["html"] and w["blocks"] is None
    assert w["data"] == {"mesh.obj": "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"}
    assert list(w["files"]) == ["turntable.png"]


@pytest.mark.parametrize("raw, why", [
    ("not json", "not valid JSON"),
    ('{"blocks": []}', "non-empty list"),
    ('[{"type": "chart"}]', "unknown block type"),
    ('[{"type": "image", "file": "missing.png"}]', "not an attached file"),
    ('[{"type": "progress", "label": "x", "value": 4}]', "fraction"),
    ('[{"type": "table", "columns": ["a"], "rows": [["1", "2"]]}]', "at most 1 cells"),
])
def test_blocks_the_stage_cannot_draw_are_refused_with_the_reason_and_nothing_is_stored(pd, raw, why):
    with pytest.raises(WG.WidgetError, match=why):
        F.widget_put(pd, "bad", "Bad", kind="blocks", text=raw)
    assert F.snapshot(pd)["widgets"] == [] and not os.path.exists(os.path.join(pd, "flow", "widgets", "bad", "content.json"))


def test_html_that_needs_the_network_or_is_too_big_is_refused(pd):
    with pytest.raises(WG.WidgetError, match="without network"):
        F.widget_put(pd, "cdn", "CDN", text='<script src="https://cdn.example.com/three.js"></script>')
    with pytest.raises(WG.WidgetError, match="over 400 KB"):
        F.widget_put(pd, "big", "Big", text="<p>" + "x" * (WG.MAX_HTML_BYTES + 1))


def test_layout_moves_a_widget_without_touching_its_content_and_rejects_nonsense(pd):
    F.widget_put(pd, "notes", "Notes", text=json.dumps([{"type": "text", "text": "Hello **there**"}]))
    F.widget_layout(pd, "notes", place="assets", span=4, height="auto", order=-1)
    w = widgets(pd)["notes"]
    assert (w["place"], w["span"], w["height"], w["order"]) == ("assets", 4, "auto", -1)
    assert w["blocks"][0]["text"] == "Hello **there**"
    for bad in (dict(span=13), dict(height="huge"), dict(place="nowhere")):
        with pytest.raises(WG.WidgetError):
            F.widget_layout(pd, "notes", **bad)
    with pytest.raises(F.FlowError, match="at least one"):
        F.widget_layout(pd, "notes")


def test_replacing_needs_force_and_keeps_the_layout_while_removing_deletes_the_files(pd, png):
    F.widget_put(pd, "queue", "Render queue", text=BLOCKS, attach=[png], span=6)
    with pytest.raises(F.FlowError, match="--force"):
        F.widget_put(pd, "queue", text=BLOCKS)
    F.widget_put(pd, "queue", text=json.dumps([{"type": "text", "text": "Done"}]), force=True)
    assert widgets(pd)["queue"]["span"] == 6 and widgets(pd)["queue"]["title"] == "Render queue"
    F.widget_rm(pd, "queue")
    assert F.snapshot(pd)["widgets"] == [] and not os.path.exists(os.path.join(pd, "flow", "widgets", "queue"))


def test_widgets_sort_by_place_then_order_and_a_missing_content_file_is_a_note_not_a_crash(pd):
    F.widget_put(pd, "b", "B", text=json.dumps([{"type": "text", "text": "b"}]), order=2)
    F.widget_put(pd, "a", "A", text=json.dumps([{"type": "text", "text": "a"}]), order=1)
    F.widget_put(pd, "c", "C", text=json.dumps([{"type": "text", "text": "c"}]), place="assets")
    assert [w["id"] for w in F.snapshot(pd)["widgets"]] == ["c", "a", "b"]
    os.remove(os.path.join(pd, "flow", "widgets", "a", "content.json"))
    assert "missing" in widgets(pd)["a"]["note"]


def test_the_state_stays_inside_the_mod_limit_when_widgets_are_huge(pd):
    for i in range(4):
        F.widget_put(pd, f"w{i}", f"W{i}", text="<p>" + "y" * (WG.MAX_HTML_BYTES - 100))
    snap = F.snapshot(pd)
    assert len(json.dumps(snap).encode()) <= F.state_budget()
    assert any(w["html"] is None and "Too big" in w["note"] for w in snap["widgets"])
