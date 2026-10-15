"""Opt-in X (Twitter) platform gates for `promo check`, enabled by `platform: x` in promo.yaml.

x-muted-hook  text on screen within the first 2.0 s (autoplay is muted)       WARN
x-safe-zone   no caption / text box in the bottom 15 % of the frame (player UI) FAIL
x-export      16:9/1:1/4:5, H.264 + AAC, 1080p for a final; -14 LUFS +/-1.5           FAIL format / WARN loudness
x-soft-open   music 0-2 s at least 3 LU under 2-4 s (fade-in under the hook)    WARN
"""
import os
import re
import subprocess

HOOK_S, SAFE_BOTTOM, LUFS, LUFS_TOL, SOFT_LU = 2.0, 0.15, -14.0, 1.5, 3.0


def enabled(spec):
    p = spec.raw.get("platform")
    return "x" in ([p] if isinstance(p, str) else (p or []))


def _boxes(spec, ctx):
    """(shot, text, global t0, box in 1920x1080 px or None) for every caption / label / kinetic line."""
    from .shots import get_type
    from .shots import cinema as CI
    for s in spec.shots:
        kin = {CI.kinetic_text(it): it for it in CI.kinetic_items(s)} if s.type == "cinema" else {}
        for c in get_type(s.type).captions(ctx, s):
            b = c.get("box")
            if b is None and c["text"] in kin:
                b = CI.kinetic_box(spec, s, kin[c["text"]])
            if c["t0"] < s.dur:
                yield s, c["text"], s.t0 + c["t0"], b


def mean_lufs(path, t0, dur, stream="-vn"):
    """Integrated loudness of a time window (ebur128); None if silent / unmeasurable."""
    r = subprocess.run(["ffmpeg", "-nostats", "-ss", str(t0), "-t", str(dur), "-i", path, stream, "-af", "ebur128", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = re.search(r"I:\s+(-?[\d.]+) LUFS", r.stderr[r.stderr.rfind("Summary:"):])
    v = float(m.group(1)) if m else None
    return None if v is None or v <= -69 else v


def gates(spec, ctx):
    if not enabled(spec):
        return []
    from .check import ffprobe_json, loudness
    rows, items = [], list(_boxes(spec, ctx))
    first = min((t for _s, _t, t, _b in items), default=None)
    rows.append(("x-muted-hook", "PASS" if first is not None and first <= HOOK_S + 1e-9 else "WARN",
                 f"first on-screen text at {first:.2f}s (X autoplays muted: want <= {HOOK_S}s)" if first is not None else "no on-screen text at all"))
    lim = (1 - SAFE_BOTTOM) * 1080
    bad = [f"shot {s.id} {t!r} bottom {b[3]:.0f}px > {lim:.0f}px" for s, t, _t0, b in items if b and b[3] > lim + 0.5]
    rows.append(("x-safe-zone", "FAIL" if bad else "PASS", "; ".join(bad) if bad else f"all text above the bottom {SAFE_BOTTOM:.0%} (X player controls)"))
    out = spec.output_path(spec.masters[0].get("suffix", ""))
    if not os.path.exists(out):
        rows.append(("x-export", "FAIL", f"{os.path.basename(out)}: output missing"))
        return rows
    j = ffprobe_json(out, "-show_streams")
    v = next((x for x in j["streams"] if x["codec_type"] == "video"), {})
    a = next((x for x in j["streams"] if x["codec_type"] == "audio"), {})
    w, h = v.get("width", 0), v.get("height", 0)
    probs = []
    if not h or not any(abs(w / h - r) <= 0.01 for r in (16 / 9, 1.0, 4 / 5)):
        probs.append(f"{w}x{h} is not 16:9, 1:1 or 4:5")
    if v.get("pix_fmt") != "yuv420p":
        probs.append(f"pix_fmt {v.get('pix_fmt')} (want yuv420p)")
    if w % 2 or h % 2:
        probs.append(f"{w}x{h} has an odd dimension")
    if v.get("codec_name") != "h264":
        probs.append(f"video {v.get('codec_name')} (want h264)")
    if a.get("codec_name") != "aac":
        probs.append(f"audio {a.get('codec_name')} (want aac)")
    if spec.scale >= 1 and min(w, h) != 1080:
        probs.append(f"final short side is {min(w, h)}px (want 1080)")
    L, _tp = loudness(out)
    lw = L is None or abs(L - LUFS) > LUFS_TOL
    msg = f"{w}x{h} {v.get('codec_name')}/{a.get('codec_name')}, {L} LUFS (want {LUFS}±{LUFS_TOL})"
    rows.append(("x-export", "FAIL" if probs else ("WARN" if lw else "PASS"), "; ".join(probs + ([msg] if lw or probs else [])) or msg))
    music = os.path.join(spec.audio_dir, "music-edit.wav")
    src = music if os.path.exists(music) else out
    a0, a1 = mean_lufs(src, 0, HOOK_S), mean_lufs(src, HOOK_S, HOOK_S)
    ok = a1 is not None and (a0 is None or a1 - a0 >= SOFT_LU)
    rows.append(("x-soft-open", "PASS" if ok else "WARN",
                 f"{os.path.basename(src)}: 0-2s {a0} LUFS vs 2-4s {a1} LUFS (want the open >= {SOFT_LU} LU quieter)"))
    return rows
