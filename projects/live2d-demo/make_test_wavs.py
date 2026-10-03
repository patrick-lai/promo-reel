# Test-only dialogue WAVs for the Live2D demo (Kokoro-82M, Apache-2.0; same model files the promo repo fetches).
import os
import numpy as np, soundfile as sf
from kokoro_onnx import Kokoro
M = os.environ.get("KOKORO_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "commission-ai-hero", "media", "models")) + "/"
OUT = os.environ.get("LIVE2D_DEMO_WAVS", "/workspace/promo-reel-evals/live2d")
os.makedirs(OUT, exist_ok=True)
k = Kokoro(M + "kokoro-v1.0.onnx", M + "voices-v1.0.bin")
SR = 24000
lines = [("a", 0.30, "af_bella", "Hey everyone, welcome back to the stream!"),
         ("b", 3.10, "bf_emma", "Today we are trying something new on the big screen."),
         ("a", 6.00, "af_bella", "Let's jump right in and take a look."),
         ("b", 8.10, "bf_emma", "Sounds good to me.")]
T = 10.0
tracks = {h: np.zeros(int(T * SR), np.float32) for h in "ab"}
for h, at, voice, text in lines:
    s, sr = k.create(text, voice=voice, speed=1.05, lang="en-us")
    s = np.asarray(s, np.float32)
    idx = np.where(np.abs(s) > 0.01)[0]
    s = s[max(0, idx[0] - 240): idx[-1] + 2400]
    a = int(at * SR)
    s = s[: len(tracks[h]) - a]
    tracks[h][a:a + len(s)] += s
    print(h, at, round(len(s) / SR, 2), text)
for h in "ab":
    sf.write(os.path.join(OUT, f"host_{h}.wav"), tracks[h], SR)
