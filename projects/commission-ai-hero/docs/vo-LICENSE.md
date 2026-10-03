# Voiceover licence log (hero v1)

- Script: /workspace/promo/marketing/vo-script-v1.md ("locked 4 Oct 2026 against main 4a427fc0"), all 9 lines, verbatim. TTS-only respellings: "PRs" -> "P R's", "commission-ai" -> "Commission AI" (so it isn't read as "Commissioner"), commas added for phrasing.
- Engine: **Kokoro-82M v1.0** (hexgrad), offline on the box, CPU, via the `kokoro-onnx` Python package (ONNX export of the same v1.0 weights + voices pack).
  - Model card / source: https://huggingface.co/hexgrad/Kokoro-82M (code https://github.com/hexgrad/kokoro)
  - ONNX files used: https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.0 (`kokoro-v1.0.onnx`, `voices-v1.0.bin`), stored in audio/vo/model/
  - Weights licence: **Apache-2.0** (model card: "Apache-licensed model ... deployed in numerous projects and commercial APIs"). kokoro-onnx package: MIT. Commercial use allowed; Apache-2.0 asks for licence notice if the *model* is redistributed, not for generated audio.
  - Training data (model card): permissive/non-copyrighted audio only (public domain, Apache/MIT-licensed audio, synthetic audio from closed TTS providers); CC BY sets Koniwa (CC BY 3.0) and SIWIS (CC BY 4.0) credited on the model card. No voice clone of a real person.
- Voice: **bf_emma** (British English female, `lang=en-gb`, speed 0.95). Chosen as the closest en-GB/AU-neutral voice (Kokoro has no en-AU voice); warm, even delivery.
- Phonemiser: espeak-ng via `espeakng-loader` (GPL-3 tool; it only converts text to phonemes, the output audio is not covered by it).
- QA: each line transcribed back with faster-whisper small.en; all 9 lines read back word-correct ("commission-ai" -> "Commission AI"). Pitch movement p10-p90 4-6.5 semitones per line (not monotone).
- Stems: audio/vo/stems/vo-<shot>-bf_emma.wav (24 kHz mono), placement in audio/mix/vo-placement.json. Render script: audio/vo/make_vo.py.

- Stems: script line 5 is rendered as two stems so each half lands on its own shot: `vo-05` "...and a crew of agents picks it up." (shot 05) and `vo-06` "Each in its own worktree." (shot 06). Wording unchanged. 10 stems in total, no VO over shots 11 and 16.
