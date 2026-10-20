"""Runs inside the local voice venv (promo/vo_mlx.py starts it): loads one mlx-audio model, then makes one take per request.

    python vo_mlx_worker.py MODEL_DIR

One JSON request per stdin line: {text, out, seed, voice?, instruct?, speed?}. The take is written as a FLOAT WAV to `out`; one JSON
reply per line on the protocol stream: {ok: true, sr, frames} or {ok: false, error}. Imports only what the venv has (never promo).
"""
import json
import os
import sys

# mlx-audio, transformers and tqdm print to stdout; replies go to a private copy of it, everything else to stderr
proto = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
os.environ["HF_HUB_OFFLINE"] = "1"          # the model is already on disk (`promo vo setup`); online checks cost ~60 s a load

import mlx.core as mx                         # noqa: E402
import numpy as np                            # noqa: E402
import soundfile as sf                        # noqa: E402
from mlx_audio.tts.utils import load_model    # noqa: E402


def reply(**kw):
    proto.write(json.dumps(kw) + "\n")


def take(model, job):
    mx.random.seed(int(job["seed"]))
    np.random.seed(int(job["seed"]))
    kw = {k: job[k] for k in ("voice", "instruct", "speed") if job.get(k) is not None}
    if job.get("instruct"):
        kw["use_zero_spk_emb"] = True              # a voice designed from the words alone, not a reference speaker
    parts = list(model.generate(text=job["text"], **kw))
    x = np.concatenate([np.array(p.audio, dtype=np.float32).reshape(-1) for p in parts])
    sf.write(job["out"], x, parts[0].sample_rate, subtype="FLOAT")
    return parts[0].sample_rate, len(x)


def main():
    model = load_model(sys.argv[1])
    reply(ok=True, ready=True)
    for line in sys.stdin:
        job = json.loads(line)
        try:
            sr, n = take(model, job)
        except Exception as e:                      # report it and keep serving: one bad line must not end the batch
            reply(ok=False, error=f"{type(e).__name__}: {e}")
            continue
        reply(ok=True, sr=sr, frames=n)


if __name__ == "__main__":
    main()
