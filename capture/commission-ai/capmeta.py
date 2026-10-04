"""Shared paths + per-clip capture facts for mk_manifest.py / register.py.

Injected capture CSS and the cursor overlay come from <footage>/<clip>.meta.json (written by rec.mjs / enc.sh for every take),
falling back to the clip's "inject" entry in notes.json (takes recorded before meta.json existed).
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))          # capture/commission-ai -> repo root
DEFAULT_COMMIT = "4a427fc05f829d7b2e4ed7ea642d77340554f7f8"
CSS_DESC = {
    "NO_TOASTS": "NO_TOASTS ([data-sonner-toaster]{display:none} - Sonner toasts hidden)",
    "HIDE_MONEY": "HIDE_MONEY (wallet/mora + cost figures visibility:hidden)",
    "CUSTOM": "custom capture CSS (see the script)",
}


def footage_dir(cli=None):
    """--footage-dir > $FOOTAGE_DIR > <repo>/../videos/commission-ai-promo/footage/v1-1080 (same default as rec.mjs / enc.sh)."""
    d = cli or os.environ.get("FOOTAGE_DIR") or os.path.join(REPO, "..", "videos", "commission-ai-promo", "footage", "v1-1080")
    return os.path.abspath(d)


def load_notes(path=None):
    return json.load(open(path or os.path.join(HERE, "notes.json")))


def clip_flags(note, fdir):
    """{'css': [...], 'cursor_overlay': bool, 'source': 'meta.json'|'notes.json'} for one notes.json clip."""
    mf = os.path.join(fdir, note["file"] + ".meta.json")
    if os.path.exists(mf):
        p = json.load(open(mf)).get("params", {})
        return dict(css=list(p.get("css", [])), cursor_overlay=bool(p.get("cursorOverlay")), source="meta.json")
    inj = note.get("inject")
    if inj is None:
        raise KeyError(f"{note['file']}: no {note['file']}.meta.json and no 'inject' in notes.json; cannot record injected CSS / cursor overlay")
    return dict(css=list(inj.get("css", [])), cursor_overlay=bool(inj.get("cursor_overlay")), source="notes.json")


def capture_text(flags):
    css = ", ".join(["cursor:none (all takes)"] + [CSS_DESC.get(c, c) for c in flags["css"]])
    cur = "capture-overlay arrow following the real pointer" if flags["cursor_overlay"] else "none"
    return f"injected CSS: {css}; cursor overlay: {cur}"


def framing_text(flags):
    """Framing-relevant capture facts (things the edit sees in frame)."""
    out = []
    if "HIDE_MONEY" in flags["css"]:
        out.append("HIDE_MONEY capture CSS: money figures blanked (visibility:hidden)")
    if flags["cursor_overlay"]:
        out.append("capture-overlay cursor in frame")
    return "; ".join(out)
