import numpy as np
from PIL import Image

from promo.shots import brand as B


def test_mark_tile_has_lit_shade_and_ring_pixels():
    t = B.mark_tile(60)
    a = np.asarray(t)
    cols = {tuple(p[:3]) for p in a.reshape(-1, 4)[::97] if p[3] > 250}
    g = B.GLYPH_COLS
    assert g["lit"] in cols and g["shade"] in cols and g["ring"] in cols


def test_mark_tile_colours_are_overridable():
    a = np.asarray(B.mark_tile(60, cols=dict(ring=(10, 200, 30))))
    cols = {tuple(p[:3]) for p in a.reshape(-1, 4)[::97] if p[3] > 250}
    assert (10, 200, 30) in cols and B.GLYPH_COLS["ring"] not in cols


def test_lockup_animates_and_is_resolution_independent():
    for W, H in ((480, 270), (960, 540)):
        early = B.lockup(W, H, 0.5, "Acme Tasks", [], dict(mark="builtin"))
        late = B.lockup(W, H, 3.3, "Acme Tasks", [], dict(mark="builtin"))
        assert early.size == (W, H) == late.size
        ea, la = np.asarray(early.split()[3]).sum(), np.asarray(late.split()[3]).sum()
        assert la > ea > 0                                  # mark first, then the letters, aura and rule fill in
    # the settled name sits centred horizontally (within 3% of the width)
    a = np.asarray(late.split()[3]).astype(float)
    cols = np.where(a[int(0.45 * H):int(0.58 * H)].sum(axis=0) > 40)[0]
    assert abs((cols.min() + cols.max()) / 2 / W - 0.5) < 0.03


def test_lockup_is_deterministic():
    a = np.asarray(B.lockup(480, 270, 1.4, "Acme Tasks", []))
    b = np.asarray(B.lockup(480, 270, 1.4, "Acme Tasks", []))
    assert (a == b).all()


def _name_band(img, H):
    return np.asarray(img)[int(0.44 * H):int(0.58 * H)]


def test_multi_part_wordmark_uses_per_part_colour():
    W, H = 640, 360
    wm = [dict(text="Acme", color=[255, 0, 0]), dict(text="-", color="#00ff00"), dict(text="Tasks", color=[0, 0, 255], weight=480)]
    img = B.lockup(W, H, 3.3, None, [], dict(wordmark=wm, sparkles=0, aura=0, rule=False))
    band = _name_band(img, H).reshape(-1, 4)
    solid = band[band[:, 3] > 250]
    assert (solid[:, 0] > 200).sum() > 20 and (solid[:, 2] > 200).sum() > 20      # red part and blue part both rendered
    cols = np.where(_name_band(img, H)[..., 3].sum(axis=0) > 40)[0]
    assert abs((cols.min() + cols.max()) / 2 / W - 0.5) < 0.03                    # still centred as one line
    # red is left of blue: the parts keep their order
    full = _name_band(img, H)
    xr = np.where(((full[..., 0] > 200) & (full[..., 3] > 250)).any(axis=0))[0]
    xb = np.where(((full[..., 2] > 200) & (full[..., 0] < 60) & (full[..., 3] > 250)).any(axis=0))[0]
    assert xr.mean() < xb.mean()


def test_wordmark_parts_default_to_name_and_accept_strings():
    c = {**B.DEFAULTS}
    assert B._parts("Acme", c) == [("Acme", tuple(B.DEFAULTS["col_name"]), B.DEFAULTS["weight"])]
    assert [t for t, *_ in B._parts(None, {**c, "wordmark": ["A", {"text": "b"}, {"text": ""}]})] == ["A", "b"]


def test_no_mark_by_default_and_builtin_mark_on_request():
    W, H = 480, 270
    kw = dict(sparkles=0, aura=0, rule=False)
    plain = np.asarray(B.lockup(W, H, 3.3, "Acme", [], kw))[..., 3]
    glyph = np.asarray(B.lockup(W, H, 3.3, "Acme", [], dict(kw, mark="builtin")))[..., 3]
    top = slice(0, int(0.40 * H))                             # the mark lives above the name
    assert plain[top].max() < 8 and glyph[top].max() > 200     # (the name's own glow may leak a faint fringe upward)


def test_emblem_path_shows_a_mark_and_reads_centre_json(tmp_path):
    em = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    em.paste((250, 100, 100, 255), (10, 10, 60, 60))
    p = tmp_path / "emblem.png"
    em.save(p)
    (tmp_path / "emblem.json").write_text('{"centre": [0.35, 0.35]}')
    W, H = 480, 270
    img = np.asarray(B.lockup(W, H, 3.3, "Acme", [], dict(emblem_path=str(p), sparkles=0, aura=0, rule=False)))
    top = img[:int(0.40 * H)]
    assert top[..., 3].sum() > 0
    xs = np.where((top[..., 3] > 250).any(axis=0))[0]
    assert abs((xs.min() + xs.max()) / 2 / W - 0.5) < 0.05     # centred on the json centre (the square's middle)
