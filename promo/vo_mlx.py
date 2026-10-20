"""Local voices on Apple Silicon (VO engine `mlx`): Ming-3.0-tts-0.5B (MIT, 44.1 kHz) through mlx-audio, in a venv of its own.

    promo vo setup            one time: the venv (exact versions: promo/vo_mlx_requirements.txt), the model at a pinned revision, a test line
    promo vo voices --local   the built-in voices

The venv is ~/.promo-tools/venv-mlx-tts-<pin>, named after what is in it, so worktrees on another pin never share one; its stamp.json
is written last, so a half-finished setup is never used. mlx-audio is not in promo's own venv because it needs a git build of
mlx-audio, transformers and Apple Silicon. promo starts one worker per process on first use (promo/vo_mlx_worker.py) and keeps it,
so the model loads once (~4 s) however many lines, hosts or previews ask for a take.
"""
from __future__ import annotations

import atexit
import datetime
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import soundfile as sf

MODEL_REPO = "mlx-community/Ming-3.0-tts-0.5B-bf16"
MODEL_REV = "affb903e61b8199381cf66d3955fbcbd79ce7f2b"
MODEL_URL = "https://huggingface.co/inclusionAI/Ming-3.0-tts-0.5B"
# the five English voices of Ming-3.0-tts (cookbooks/instruction_en.md); the model takes any UK_/US_ name without complaint
VOICES = {"UK_Charlotte": "female, British: audiobooks, measured narration",
          "UK_George": "male, British: audiobooks, formal announcements",
          "US_Emma": "female, American: assistants, narration, a conversational product voice",
          "US_James": "male, American: narration, explainer and documentary reads",
          "US_Stella": "female, American: narration, conversational, warm, youthful"}
DEFAULT_VOICE = "UK_Charlotte"
HOME = Path.home()
WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vo_mlx_worker.py")
REQUIREMENTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vo_mlx_requirements.txt")


def pin():
    return hashlib.sha256(open(REQUIREMENTS, "rb").read() + MODEL_REV.encode()).hexdigest()[:10]


def venv_dir():
    return HOME / ".promo-tools" / f"venv-mlx-tts-{pin()}"


def stamp():
    """What the local voice is made of ({pin, model_dir, mlx, ...}), or None until `promo vo setup` has finished."""
    p = venv_dir() / "stamp.json"
    return json.loads(p.read_text()) if p.exists() else None


def ready():
    return stamp() is not None


def signature():
    """The part of the stamp a take depends on (in the VO cache key): a new pin or model revision makes new takes."""
    st = stamp()
    return st and [st["pin"], st["model_rev"], st["mlx"]]


def _worker_cmd(python):
    """How to start the worker; PROMO_MLX_WORKER (a command line) replaces it, for tests that must not need the model."""
    return shlex.split(os.environ["PROMO_MLX_WORKER"]) if os.environ.get("PROMO_MLX_WORKER") else [str(python), WORKER]


class _Worker:
    def __init__(self, model_dir, python):
        self.p = subprocess.Popen(_worker_cmd(python) + [model_dir], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        if not self.read().get("ready"):
            raise RuntimeError("the local voice did not start; its log is above")

    def read(self):
        line = self.p.stdout.readline()
        if not line:
            raise RuntimeError(f"the local voice stopped (exit {self.p.wait()}); its log is above. `promo vo setup` checks the install")
        return json.loads(line)

    def take(self, job):
        self.p.stdin.write(json.dumps(job) + "\n")
        self.p.stdin.flush()
        return self.read()

    def close(self):
        if self.p.poll() is None:
            self.p.stdin.close()
            self.p.wait(timeout=30)


_LOCK = threading.Lock()                  # previews make samples in threads; the one worker answers one request at a time
_WORKER = {}


def _close():
    for w in _WORKER.values():
        w.close()


atexit.register(_close)


def synth(v, text):
    """(mono float32, sr) of one raw take in local voice `v` (voice or instructions, seed, speed)."""
    st = stamp()
    if not st:
        raise RuntimeError("the local voice is not set up on this Mac: run `promo vo setup` once (~1 GB venv; the model is ~3 GB)")
    with _LOCK:
        w = _WORKER.get("w")
        if w is None or w.p.poll() is not None:
            w = _WORKER["w"] = _Worker(st["model_dir"], venv_dir() / "bin" / "python")
        with tempfile.TemporaryDirectory(prefix="vo-mlx-") as d:
            out = os.path.join(d, "take.wav")
            r = w.take(dict(text=text, out=out, seed=int(v.get("seed", 1)), voice=v.get("voice"), instruct=v.get("instructions"),
                            speed=float(v["speed"]) if v.get("speed") is not None else None))
            if not r["ok"]:
                raise RuntimeError(f"the local voice could not read {text[:40]!r}: {r['error']}")
            x, sr = sf.read(out, dtype="float32")
    return x, sr


def check_voice(v):
    """A Ming built-in voice name, or `instructions` (a voice designed from words), never both: the model would take a typo silently."""
    if v.get("instructions"):
        if v.get("voice"):
            raise RuntimeError("engine mlx: give a built-in `voice` or `instructions` (a designed voice), not both")
        return
    if v.get("voice") not in VOICES:
        raise RuntimeError(f"engine mlx has no voice {v.get('voice')!r}; it has {', '.join(VOICES)} (`promo vo voices --local`)")


def _run(cmd, log):
    log("  $ " + " ".join(str(c) for c in cmd))
    subprocess.run(cmd, check=True)


def setup(log=print):
    """Make the venv, fetch the model, read one test line, then write the stamp. Safe to run again: a finished setup is left alone."""
    if ready():
        log(f"local voice ready: {venv_dir()} (model {MODEL_REPO}@{MODEL_REV[:8]})")
        return stamp()
    d = venv_dir()
    python = d / "bin" / "python"
    uv = shutil.which("uv")
    log(f"setting up the local voice in {d}")
    if not python.exists():
        _run([uv, "venv", "-q", "-p", "3.12", str(d)] if uv else [sys.executable, "-m", "venv", str(d)], log)
    _run([uv, "pip", "install", "-q", "--python", str(python), "-r", REQUIREMENTS] if uv else
         [str(python), "-m", "pip", "install", "-q", "-r", REQUIREMENTS], log)
    log(f"fetching {MODEL_REPO} at {MODEL_REV[:8]} (about 3 GB the first time; progress below)")
    model_dir = subprocess.run([str(python), "-c", "from huggingface_hub import snapshot_download; "
                                f"print(snapshot_download({MODEL_REPO!r}, revision={MODEL_REV!r}))"],
                               check=True, stdout=subprocess.PIPE, text=True).stdout.strip().splitlines()[-1]
    mlx = subprocess.run([str(python), "-c", "import importlib.metadata as m; print(m.version('mlx'))"], check=True, stdout=subprocess.PIPE,
                         text=True).stdout.strip()
    log("reading a test line")
    w = _Worker(model_dir, python)
    with tempfile.TemporaryDirectory(prefix="vo-mlx-") as tmp:
        r = w.take(dict(text="Hello from promo reel.", out=os.path.join(tmp, "t.wav"), seed=1, voice=DEFAULT_VOICE))
    w.close()
    if not r["ok"] or not r.get("frames"):
        raise RuntimeError(f"the local voice installed but could not read a test line: {r.get('error')}")
    st = dict(pin=pin(), model_repo=MODEL_REPO, model_rev=MODEL_REV, model_dir=model_dir, mlx=mlx,
              made_at=datetime.datetime.now().astimezone().isoformat(timespec="seconds"))
    (d / "stamp.json").write_text(json.dumps(st, indent=1))
    log(f"local voice ready: test line {r['frames'] / r['sr']:.1f} s at {r['sr']} Hz")
    return st
