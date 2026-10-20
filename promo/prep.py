"""Local prep of a clip before Seedance recasts it (on this Mac; Higgsfield is not used).

    promo prep CLIP --out PREP.mp4 [--mode face_mesh|depth|depth_mesh]

Modes:
  face_mesh    MediaPipe Face Landmarker: a white wireframe on every face (talking head, fast)
  depth        Depth Anything people composited over the real background (full-body motion)
  depth_mesh   both

Vocals are isolated when Demucs is installed, then pitched +3 semitones (duration kept) so Seedance can hear lip-sync
without the original mix. `restore_audio` copies the source soundtrack onto the finished take.

Nothing is sent anywhere during prep. Product screen recordings are refused by the Studio, not here.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from .lock import heavy_lock

MODES = ("face_mesh", "depth", "depth_mesh")
MAX_SIDE = 960
FPS = 24
PITCH = 3
FACE_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
# oval + eyes + lips when mediapipe is not imported (tests)
_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
_landmarker = None


class PrepError(RuntimeError):
    """Prep cannot run as asked; the message says why."""


def _tools():
    from .openrouter import _tools_dir
    return _tools_dir() / "models"


def _model(name, url):
    path = _tools() / name
    if path.exists():
        return str(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        import urllib.request
        urllib.request.urlretrieve(url, tmp)
        os.replace(tmp, path)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise PrepError(f"could not download {name}: {e}") from e
    return str(path)


def available_mesh():
    try:
        importlib.import_module("mediapipe.tasks.python.vision").FaceLandmarker
        return True
    except (ImportError, AttributeError):
        return False


def _edges():
    try:
        from mediapipe.tasks.python.vision import FaceLandmarksConnections
        return [(c.start, c.end) for c in FaceLandmarksConnections.FACE_LANDMARKS_TESSELATION]
    except ImportError:
        return list(zip(_OVAL, _OVAL[1:] + _OVAL[:1]))


def _landmarker_obj():
    global _landmarker
    if _landmarker is None:
        try:
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import FaceLandmarker, FaceLandmarkerOptions
        except ImportError as e:
            raise PrepError("face mesh needs mediapipe (`pip install -e .[prep]`)") from e
        _landmarker = FaceLandmarker.create_from_options(FaceLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=_model("face_landmarker.task", FACE_URL)), num_faces=4,
            min_face_detection_confidence=0.4))
    return _landmarker


def detect_faces(rgb):
    """List of (N, 2) float arrays, pixel xy, one per face. Overridable in tests."""
    import mediapipe as mp
    h, w = rgb.shape[:2]
    img = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
    res = _landmarker_obj().detect(img)
    out = []
    for face in res.face_landmarks or []:
        out.append(np.array([(lm.x * w, lm.y * h) for lm in face], np.float32))
    return out


def draw_mesh(rgb, faces, color=(255, 255, 255)):
    """White wireframe on a copy of `rgb` (HxWx3 uint8)."""
    out = np.ascontiguousarray(rgb.copy())
    try:
        import cv2
        def stroke(p, q):
            cv2.line(out, (int(p[0]), int(p[1])), (int(q[0]), int(q[1])), color, 1, cv2.LINE_AA)
    except ImportError:
        def stroke(p, q):
            _plot(out, p, q, color)
    tess = _edges()
    for pts in faces:
        n = len(pts)
        pairs = [(a, b) for a, b in tess if a < n and b < n]
        if not pairs:
            # tessellation indexes a 478-point face; a short list of points has none of those edges
            pairs = list(zip(range(n), list(range(1, n)) + [0]))
        for a, b in pairs:
            stroke(pts[a], pts[b])
    return out


def _plot(img, p, q, color):
    h, w = img.shape[:2]
    n = max(int(np.hypot(*(q - p))), 1)
    for t in np.linspace(0, 1, n):
        x, y = (p * (1 - t) + q * t).astype(int)
        if 0 <= x < w and 0 <= y < h:
            img[y, x] = color


def color_depth(depth):
    """HxW in [0, 1] (1 = near) to an HxWx3 heat map."""
    t = np.clip(depth, 0, 1)
    r = np.clip(1.7 * t, 0, 1)
    g = np.clip(1.7 * t - 0.5, 0, 1)
    b = np.clip(1.1 - t, 0, 1)
    return (np.stack([r, g, b], -1) * 255).astype(np.uint8)


def person_mask(depth):
    """Largest near blob: the person against a farther background."""
    from scipy import ndimage
    cut = np.percentile(depth, 55)
    m = depth > cut
    if not m.any():
        m = depth >= cut                     # a flat map: treat the whole frame as the figure
    lab, n = ndimage.label(m)
    if n == 0:
        return m
    sizes = ndimage.sum(m, lab, range(1, n + 1))
    return ndimage.binary_closing(lab == (1 + int(np.argmax(sizes))), iterations=2)


def composite(rgb, depth, mask):
    col = color_depth(depth)
    return np.where(mask[..., None], col, rgb)


def pitch_samples(y, sr, semitones=PITCH):
    """Stereo or mono float array, same duration, shifted by `semitones`."""
    import librosa
    y = np.asarray(y, np.float32)
    if y.ndim == 1:
        out = librosa.effects.pitch_shift(y, sr=sr, n_steps=semitones)
        return out[:len(y)]
    chans = [librosa.effects.pitch_shift(y[:, c], sr=sr, n_steps=semitones) for c in range(y.shape[1])]
    out = np.stack(chans, 1)
    return out[:len(y)]


def _probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate,duration",
                        "-of", "json", str(path)], capture_output=True, text=True)
    try:
        s = json.loads(r.stdout)["streams"][0]
    except (ValueError, KeyError, IndexError) as e:
        raise PrepError(f"{path} is not a readable video") from e
    a, b = (s.get("r_frame_rate") or "24/1").split("/")
    return int(s["width"]), int(s["height"]), float(a) / float(b or 1), float(s.get("duration") or 0)


def _has_audio(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def _extract_audio(src, wav):
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "2", "-ar", "44100", str(wav)], capture_output=True)
    return r.returncode == 0 and Path(wav).exists() and Path(wav).stat().st_size > 64


def _vocals(src, wav):
    try:
        from .lyrics import LyricsError, separate_vocals
    except ImportError:
        return _extract_audio(src, wav)
    try:
        separate_vocals(src, 0, None, wav)
        return True
    except LyricsError:
        return _extract_audio(src, wav)


def _pitch_file(wav_in, wav_out, semitones=PITCH):
    import soundfile as sf
    y, sr = sf.read(str(wav_in), dtype="float32", always_2d=True)
    sf.write(str(wav_out), pitch_samples(y, sr, semitones), sr)


def restore_audio(generated, original, out):
    """Put `original`'s soundtrack on `generated`'s picture. No audio on the source leaves the generated clip as it is."""
    import shutil
    out_p = Path(out)
    if not _has_audio(original):
        if os.path.realpath(generated) != os.path.realpath(out_p):
            shutil.copyfile(generated, out_p)
        return str(out_p)
    tmp = str(out_p) + ".restoring.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(generated), "-i", str(original), "-c:v", "copy", "-map", "0:v:0",
                        "-map", "1:a:0", "-c:a", "aac", "-shortest", "-movflags", "+faststart", tmp], capture_output=True, text=True)
    if r.returncode != 0:
        Path(tmp).unlink(missing_ok=True)
        raise PrepError(f"could not restore the original soundtrack: {r.stderr[-300:]}")
    os.replace(tmp, out_p)
    return str(out_p)


def _work_size(w, h):
    if max(w, h) > MAX_SIDE:
        s = MAX_SIDE / max(w, h)
        w, h = int(w * s), int(h * s)
    return w // 2 * 2, h // 2 * 2


def prepare(src, out, mode="face_mesh", on_progress=None, detect=None, depth_of=None):
    """Write the prepared clip to `out`. `detect(rgb) -> faces` and `depth_of(PIL.Image) -> HxW` override the models (tests)."""
    if mode not in MODES:
        raise PrepError(f"no prep mode {mode!r}; one of {', '.join(MODES)}")
    if not os.path.isfile(src):
        raise PrepError(f"no clip {src}")
    w0, h0, _fps, dur = _probe(src)
    w, h = _work_size(w0, h0)
    n_est = max(1, round(dur * FPS))
    out_p = Path(out).expanduser().resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    detect = detect or detect_faces
    if mode in ("depth", "depth_mesh") and depth_of is None:
        from . import depth as D
        if not D.available():
            raise PrepError("depth prep needs onnxruntime (`pip install -e .[depth]`)")
        depth_of = D.estimate
    from PIL import Image
    with heavy_lock("promo prep"), tempfile.TemporaryDirectory() as td:
        silent = os.path.join(td, "silent.mp4")
        enc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-",
                                "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", "-threads", "2", silent],
                               stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", str(src), "-vf", f"scale={w}:{h},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-an", "-"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        nbytes, i, faces_n = w * h * 3, 0, 0
        try:
            while True:
                buf = dec.stdout.read(nbytes)
                if len(buf) < nbytes:
                    break
                rgb = np.frombuffer(buf, np.uint8).reshape(h, w, 3).copy()
                if mode in ("depth", "depth_mesh"):
                    d = depth_of(Image.fromarray(rgb))
                    rgb = composite(rgb, d, person_mask(d))
                if mode in ("face_mesh", "depth_mesh"):
                    faces = detect(rgb)
                    faces_n += len(faces)
                    rgb = draw_mesh(rgb, faces)
                enc.stdin.write(rgb.tobytes())
                i += 1
                if on_progress and (i % 8 == 0 or i >= n_est):
                    on_progress(i, max(n_est, i))
        except BrokenPipeError:
            enc.wait()
            raise PrepError(f"ffmpeg stopped reading frames: {enc.stderr.read().decode(errors='replace')[-300:]}") from None
        finally:
            dec.stdout.close()
            dec.wait()
        enc.stdin.close()
        if enc.wait() != 0:
            raise PrepError(f"ffmpeg could not write the prepared clip: {enc.stderr.read().decode(errors='replace')[-300:]}")
        wav, pitched = os.path.join(td, "v.wav"), os.path.join(td, "p.wav")
        if _has_audio(src) and _vocals(src, wav):
            _pitch_file(wav, pitched)
            r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", pitched, "-c:v", "copy", "-c:a", "aac", "-map", "0:v:0",
                                "-map", "1:a:0", "-shortest", "-movflags", "+faststart", str(out_p)], capture_output=True, text=True)
            if r.returncode != 0:
                raise PrepError(f"ffmpeg could not mux pitched vocals: {r.stderr[-300:]}")
        else:
            os.replace(silent, out_p)
        Path(str(out_p) + ".prep.json").write_text(json.dumps(dict(mode=mode, source=str(Path(src).resolve()), faces=faces_n, frames=i, pitched=_has_audio(src)), indent=1))
        if on_progress:
            on_progress(i, i)
    return str(out_p)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="promo prep", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=MODES, default="face_mesh")
    a = ap.parse_args(argv)
    try:
        print(prepare(a.src, a.out, a.mode, on_progress=lambda i, n: print(f"  frame {i}/{n}", file=sys.stderr)))
    except PrepError as e:
        raise SystemExit(f"promo prep: {e}") from None
    return 0
