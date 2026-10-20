import base64
import io
import json
import os
import urllib.error

import numpy as np
import pytest

from promo import assetplan as AP
from promo import flow as F
from promo import genvideo as G
from promo import openrouter as OR
from promo import previews as PV
from promo import studio as STU

from test_flow import INTENT, board

REAL_REQUEST = OR._request
KEY = "sk-or-v1-test-secret"
PRO = dict(id="bytedance/seedance-1-5-pro", name="ByteDance: Seedance 1.5 Pro", supported_resolutions=["480p", "720p", "1080p"],
           supported_aspect_ratios=["1:1", "16:9", "9:16"], supported_sizes=["480x480", "854x480", "480x854", "720x720", "1280x720", "720x1280", "1920x1080"],
           supported_durations=[4, 5, 6, 7, 8, 9, 10, 11, 12], supported_frame_images=["first_frame", "last_frame"], generate_audio=True, seed=True,
           pricing_skus={"video_tokens": "0.0000024", "video_tokens_without_audio": "0.0000012"})
V25 = dict(id="bytedance/seedance-2.5", name="ByteDance: Seedance 2.5", supported_resolutions=["480p", "720p"], supported_aspect_ratios=["16:9", "4:3"],
           supported_sizes=["854x480", "752x560", "1280x720", "1112x834"], supported_durations=list(range(4, 31)), supported_frame_images=["first_frame"],
           generate_audio=True, seed=True, pricing_skus={"video_tokens": "0.0000107", "video_tokens_without_audio": "0.0000107",
                                                         "video_tokens_with_video_input": "0.0000064"})
GROK = dict(id="x-ai/grok-imagine-video-1.5-lite", name="SpaceXAI: Grok Imagine Video 1.5 Lite", supported_resolutions=["480p", "720p"],
            supported_aspect_ratios=["16:9"], supported_sizes=None, supported_durations=list(range(1, 16)), supported_frame_images=["first_frame"],
            generate_audio=None, seed=None, pricing_skus={"cents_per_image_input": "1", "cents_per_video_output_second_480p": "2", "cents_per_video_output_second_720p": "3"})
EDIT = dict(id="black-forest-labs/flux-video-edit", name="Black Forest Labs: FLUX Video Edit", supported_resolutions=None, supported_aspect_ratios=None,
            supported_sizes=None, supported_durations=None, supported_frame_images=None, generate_audio=False, seed=False,
            pricing_skus={"cents_per_second_output": "3"})
VEO = dict(id="google/veo-3.1", name="Veo", supported_resolutions=["720p"], supported_aspect_ratios=["16:9"], supported_sizes=["1280x720"],
           supported_durations=[4], pricing_skus={"duration_seconds_without_audio": "0.20"})


class FakeOpenRouter:
    """OpenRouter's video API as the docs describe it: submit -> polling statuses -> content; records what was sent."""

    def __init__(self, statuses=("pending", "in_progress", "completed"), cost=0.05, error=None):
        self.statuses, self.cost, self.error, self.sent = list(statuses), cost, error, []

    def __call__(self, method, path, body=None, auth=True, raw=False, timeout=60):
        assert not auth or os.environ.get("OPENROUTER_API_KEY") == KEY
        if path == "/videos/models":
            return {"data": [PRO, V25, GROK, EDIT, VEO]}
        if method == "POST":
            self.sent.append(body)
            return {"id": "job1", "status": "pending", "polling_url": "x"}
        if path.endswith("/content?index=0"):
            return b"MP4DATA"
        status = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        out = {"id": "job1", "status": status}
        if status in ("completed", "failed"):
            out["usage"] = {"cost": self.cost}
        if status == "failed":
            out["error"] = self.error
        return out


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setattr(OR, "POLL_S", 0)
    monkeypatch.setattr(G, "HOME", tmp_path / "home")
    monkeypatch.setattr(G, "_file", lambda p: False)            # no grok / codex login, whatever this machine has
    monkeypatch.setattr(STU.D, "available", lambda: False)      # nor the local depth model
    monkeypatch.setattr(G, "probe_media", lambda p: {"width": 854, "height": 480, "duration": 4.0})
    monkeypatch.setattr(STU.P, "prepare", lambda src, dst, mode, on_progress=None, **k: (open(dst, "wb").write(open(src, "rb").read() or b"PREP"), dst)[1])
    monkeypatch.setattr(STU.P, "restore_audio", lambda g, o, out: out)
    fake = FakeOpenRouter()
    monkeypatch.setattr(OR, "_request", fake)
    return fake


def test_price_comes_from_the_catalogue_size_and_audio_choice():
    assert OR.estimate(PRO, 4, "480p", "16:9") == pytest.approx(854 * 480 * 24 * 4 / 1024 * 0.0000012, abs=1e-4)
    assert OR.estimate(PRO, 4, "480p", "16:9", audio=True) == pytest.approx(2 * OR.estimate(PRO, 4, "480p", "16:9"), abs=1e-4)
    assert OR.size_for(V25, "480p", "4:3") == (752, 560)
    assert OR.estimate(V25, 4, "480p", "16:9", video_input=True) < OR.estimate(V25, 4, "480p", "16:9")
    rows = OR.price_table([V25, PRO])
    assert [r["id"] for r in rows] == [PRO["id"], V25["id"]]
    assert rows[0]["price_4s"]["480p"] < 0.06


def test_a_job_runs_to_a_file_and_the_ledger_keeps_estimate_and_real_cost(api, tmp_path):
    out = tmp_path / "plate.mp4"
    meta = G.generate_openrouter("ink drifting in water", str(out), 4, "16:9")
    assert out.read_bytes() == b"MP4DATA"
    sent = api.sent[0]
    assert sent["model"] == OR.DEFAULT_MODEL and sent["resolution"] == "480p" and sent["duration"] == 4 and sent["generate_audio"] is False
    assert sent["prompt"].startswith(G.NEG)
    assert meta["provider"] == f"openrouter:{OR.DEFAULT_MODEL}" and meta["cost_usd"] == 0.05 and meta["estimate_usd"] > 0
    assert json.loads((tmp_path / "plate.mp4.gen.json").read_text())["job_id"] == "job1"
    sp = OR.spend()
    assert sp["total"] == 0.05 and len(sp["jobs"]) == 1
    assert KEY not in OR.ledger_path().read_text()


def test_grok_imagine_is_priced_per_second_and_gets_no_seed_or_sound(api, tmp_path):
    assert OR.estimate(GROK, 2, "480p", "16:9") == 0.04
    assert OR.estimate(GROK, 2, "480p", "16:9", first_frame=True) == 0.05
    OR.run(GROK["id"], "ink", tmp_path / "g.mp4", seconds=1, seed=5, audio=True)
    assert api.sent[0]["duration"] == 1 and "seed" not in api.sent[0] and "generate_audio" not in api.sent[0]
    assert OR.price_table([PRO, GROK])[1]["image_input"] == 0.01


def test_jobs_over_the_job_limit_or_the_daily_cap_are_refused_before_submitting(api, tmp_path, monkeypatch):
    with pytest.raises(OR.OpenRouterError, match="over the \\$0.01 limit"):
        OR.run(PRO["id"], "x", tmp_path / "a.mp4", max_usd=0.01)
    monkeypatch.setenv("PROMO_GEN_DAILY_USD", "0.02")
    with pytest.raises(OR.OpenRouterError, match="daily cap"):
        OR.run(PRO["id"], "x", tmp_path / "a.mp4")
    with pytest.raises(OR.OpenRouterError, match="4-12 s"):
        OR.run(PRO["id"], "x", tmp_path / "a.mp4", seconds=20)
    with pytest.raises(OR.OpenRouterError, match="not one of the video models"):
        OR.run(VEO["id"], "x", tmp_path / "a.mp4")
    assert api.sent == []


def test_a_failed_job_says_why_and_counts_only_what_was_billed(api, tmp_path):
    api.statuses, api.error, api.cost = ["pending", "failed"], "content policy", 0
    with pytest.raises(OR.OpenRouterError, match="content policy"):
        OR.run(PRO["id"], "x", tmp_path / "a.mp4")
    assert not (tmp_path / "a.mp4").exists()
    assert OR.spend()["total"] == 0


def test_http_errors_carry_openrouters_words_and_never_the_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    monkeypatch.setattr(OR, "_request", REAL_REQUEST)

    def refuse(req, timeout):
        assert req.get_header("Authorization") == "Bearer " + KEY
        raise urllib.error.HTTPError(req.full_url, 402, "Payment Required", {}, io.BytesIO(b'{"error": {"message": "Insufficient credits"}}'))
    monkeypatch.setattr(OR.urllib.request, "urlopen", refuse)
    with pytest.raises(OR.OpenRouterError) as e:
        OR._request("POST", "/videos", {"model": "m"})
    assert str(e.value) == "OpenRouter said 402: Insufficient credits"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    with pytest.raises(OR.OpenRouterError, match="secret exec"):
        OR._request("POST", "/videos", {})


def test_auto_never_picks_the_paid_provider(api, monkeypatch):
    found = G.detect()
    assert next(p for p in found if p["id"] == "openrouter")["available"]
    monkeypatch.setattr(G, "detect", lambda: [p for p in found if p["id"] == "openrouter"])
    with pytest.raises(SystemExit, match="no available provider"):
        G.providers("video", "auto")
    assert [p["id"] for p in G.providers("video", "openrouter")] == ["openrouter"]


@pytest.fixture
def proj(tmp_path):
    d = str(tmp_path / "proj")
    F.init(d, INTENT)
    bp = os.path.join(board(d, "A"), "board.json")
    b = json.load(open(bp))
    b["scenes"][0]["source"] = "generated"
    json.dump(b, open(bp, "w"))
    st = F.load(d)
    st["picks"] = ["A"]
    F.save(d, st)
    AP.save(os.path.join(d, "flow"), [dict(id="dusk", kind="video", source="generated", scenes=["01"], how="seedance plate"),
                                      dict(id="tour", kind="recording", source="real", scenes=["02"], how="screen recording")])
    return d


def test_studio_take_animates_a_storyboard_frame_and_shows_in_the_stage(api, proj):
    assert F.main(["--project", proj, "studio", "run", "--prompt", "dusk over a city", "--preset", "push", "--start", "A/01/start"]) == 0
    sent = api.sent[0]
    assert sent["prompt"].endswith(STU.SENTENCE["push"])
    assert sent["frame_images"][0]["frame_type"] == "first_frame"
    assert base64.b64decode(sent["frame_images"][0]["image_url"]["url"].split(",", 1)[1])[:4] == b"\x89PNG"
    studio = F.snapshot(proj)["studio"]
    take = studio["takes"][0]
    assert take["status"] == "done" and take["cost"] == 0.05 and take["video"]["$file"].endswith("flow/studio/t1.mp4")
    assert take["start_label"] == "TA, scene 01 start" and take["start_ref"] == "A/01/start"
    assert take["seed"] == sent["seed"]
    F.main(["--project", proj, "studio", "run", "--prompt", "dusk over a city", "--res", "720p", "--seed", str(take["seed"]), "--model", PRO["id"]])
    assert api.sent[1]["seed"] == take["seed"] and api.sent[1]["resolution"] == "720p"
    assert [f["id"] for f in studio["frames"]] == ["A/01/start", "A/01/end"]          # scene 02 is real: its frames would be made-up UI
    assert F.main(["--project", proj, "studio", "run", "--prompt", "x", "--start", "A/02/start"]) == 1
    assert [p["id"] for p in studio["plates"]] == ["dusk"]
    assert studio["models"][0]["id"] == PRO["id"] and studio["spend"]["total"] == 0.05 and studio["account"] == "ready"


def test_a_refused_take_stays_in_the_gallery_with_the_reason(api, proj, monkeypatch, capsys):
    monkeypatch.setenv("PROMO_GEN_DAILY_USD", "0.01")
    assert F.main(["--project", proj, "studio", "run", "--prompt", "dusk"]) == 1
    assert "daily cap" in capsys.readouterr().err
    take = F.snapshot(proj)["studio"]["takes"][0]
    assert take["status"] == "failed" and "daily cap" in take["error"] and api.sent == []


def test_a_take_becomes_the_sample_of_a_generated_plate_only(api, proj):
    F.main(["--project", proj, "studio", "run", "--prompt", "dusk"])
    assert F.main(["--project", proj, "studio", "use", "--take", "t1", "--asset", "dusk"]) == 0
    s = PV.load_samples(os.path.join(proj, "flow"))["dusk"]
    assert s["path"] == os.path.join("flow", "studio", "t1.mp4") and "$0.05" in s["note"]
    assert F.snapshot(proj)["studio"]["takes"][0]["used_for"] == ["dusk"]
    assert F.main(["--project", proj, "studio", "use", "--take", "t1", "--asset", "tour"]) == 1


def test_a_grok_subscription_take_runs_on_the_cli_and_bills_nothing(api, proj, monkeypatch):
    monkeypatch.setattr(G, "detect", lambda: [dict(id="grok", kind=["image", "video"], available=True, verified=[]),
                                              dict(id="openrouter", kind=["video"], available=True, verified=[])])
    asked = {}

    def cli(kind, prompt, out, seconds, aspect, provider, first_frame=None, resolution=None, **kw):
        asked.update(provider=provider, first_frame=first_frame, seconds=seconds)
        open(out, "wb").write(b"MP4")
    monkeypatch.setattr(G, "generate", cli)
    studio = F.snapshot(proj)["studio"]
    assert studio["default_model"] == STU.GROK and studio["models"][0]["subscription"]
    assert F.main(["--project", proj, "studio", "run", "--prompt", "dusk", "--model", STU.GROK, "--seconds", "2", "--start", "A/01/start"]) == 0
    take = F.snapshot(proj)["studio"]["takes"][0]
    assert take["status"] == "done" and take["cost"] == 0 and asked["provider"] == "grok" and asked["first_frame"].endswith("01-s.png")
    assert api.sent == [] and OR.spend()["total"] == 0


def test_a_final_resends_the_takes_stored_request_with_only_the_resolution_changed(api, proj):
    F.main(["--project", proj, "studio", "run", "--prompt", "dusk", "--model", PRO["id"], "--start", "A/01/start", "--end", "A/01/end", "--preset", "orbit"])
    draft = STU.load(proj)[0]
    assert draft["request"]["frame_images"][1]["image_url"]["url"].startswith(OR.FILE)       # kept by path, never the bytes
    assert [f["frame_type"] for f in api.sent[0]["frame_images"]] == ["first_frame", "last_frame"]
    assert F.main(["--project", proj, "studio", "rerun", "--take", "t1", "--res", "720p"]) == 0
    first, final = api.sent
    assert final == dict(first, resolution="720p")
    t2 = STU.load(proj)[1]
    assert t2["kind"] == "rerun" and t2["from"] == "t1" and t2["seed"] == draft["seed"] and t2["end_ref"] == "A/01/end"
    view = F.snapshot(proj)["studio"]["takes"]
    assert "request" not in view[0] and view[1]["end_label"] == "TA, scene 01 end"
    assert F.main(["--project", proj, "studio", "rerun", "--take", "t1", "--res", "4K"]) == 1            # the model has no 4K
    assert len(api.sent) == 2


def test_an_end_frame_goes_only_to_a_model_that_lists_one(api, proj):
    assert F.main(["--project", proj, "studio", "run", "--prompt", "dusk", "--model", V25["id"], "--end", "A/01/end"]) == 1
    assert "takes no last frame" in STU.load(proj)[0]["error"] and api.sent == []
    assert next(m for m in F.snapshot(proj)["studio"]["models"] if m["id"] == PRO["id"])["last_frame"]


def test_a_take_is_restyled_by_flux_video_edit_and_a_screen_recording_is_refused(api, proj, tmp_path):
    F.main(["--project", proj, "studio", "run", "--prompt", "dusk", "--model", PRO["id"]])
    assert F.main(["--project", proj, "studio", "restyle", "--take", "t1", "--prompt", "make it blue hour"]) == 0
    sent = api.sent[1]
    assert set(sent) == {"model", "prompt", "input_references"} and sent["model"] == EDIT["id"] and sent["prompt"] == G.NEG + "make it blue hour"
    ref = sent["input_references"][0]
    assert ref["type"] == "video_url" and base64.b64decode(ref["video_url"]["url"].split(",", 1)[1]) == b"MP4DATA"
    t2 = STU.load(proj)[1]
    assert t2["kind"] == "restyle" and t2["from"] == "t1" and t2["estimate"] == 0.12        # 3 cents a second, 4 s source
    studio = F.snapshot(proj)["studio"]
    assert studio["edit"] == dict(id=EDIT["id"], name="FLUX Video Edit", per_second=0.03, minimum=0)
    assert EDIT["id"] not in [m["id"] for m in studio["models"]]                              # not a prompt-to-clip model
    rec = tmp_path / "screen.mp4"
    rec.write_bytes(b"REC")
    assert F.main(["--project", proj, "studio", "restyle", "--take", str(rec), "--prompt", "x"]) == 1
    (tmp_path / "screen.mp4.gen.json").write_text(json.dumps(dict(generated=True)))
    assert F.main(["--project", proj, "studio", "restyle", "--take", str(rec), "--prompt", "x"]) == 0
    assert len(api.sent) == 3
    with pytest.raises(OR.OpenRouterError, match="edits a clip"):
        OR.run(EDIT["id"], "x", tmp_path / "e.mp4")


def test_a_frame_description_is_the_setting_only_and_shows_in_the_composer(api, proj, capsys):
    assert F.main(["--project", proj, "studio", "frame", "--frame", "A/01/start"]) == 0
    assert capsys.readouterr().out.strip().endswith("01-s.png")
    assert F.main(["--project", proj, "studio", "suggest", "--frame", "A/01/start", "--prompt", "a dashboard glowing on a desk"]) == 1
    assert F.main(["--project", proj, "studio", "suggest", "--frame", "A/01/start", "--prompt", "Low dusk light over  wet rooftops, 35 mm, calm"]) == 0
    sug = F.snapshot(proj)["studio"]["suggestion"]
    assert sug["frame"] == "A/01/start" and sug["prompt"] == "Low dusk light over wet rooftops, 35 mm, calm"
    assert api.sent == []


def test_a_character_swap_preps_locally_and_sends_seedance_a_video_reference(api, proj, tmp_path):
    F.main(["--project", proj, "studio", "run", "--prompt", "dusk", "--model", PRO["id"]])
    assert F.main(["--project", proj, "studio", "swap", "--take", "t1", "--prompt", "a courier in a yellow raincoat"]) == 0
    sent = api.sent[1]
    assert sent["model"] == V25["id"] and sent["duration"] == 4 and sent["generate_audio"] is False
    assert sent["input_references"][0]["type"] == "video_url" and "wireframe" in sent["prompt"]
    t2 = STU.load(proj)[1]
    assert t2["kind"] == "swap" and t2["from"] == "t1" and t2["prep"] == "face_mesh" and t2["prompt"] == "a courier in a yellow raincoat"
    studio = F.snapshot(proj)["studio"]
    assert studio["swap"]["id"] == V25["id"] and studio["preps"][0] == "face_mesh"
    own = tmp_path / "my-street-clip.mp4"                     # the person's own footage: no sidecar needed
    own.write_bytes(b"STREET")
    assert F.main(["--project", proj, "studio", "swap", "--take", str(own), "--prompt", "an astronaut", "--prep", "none"]) == 0
    assert "Replace the person in this clip" in api.sent[2]["prompt"]
    rec = os.path.join(proj, "footage", "board.mp4")
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    open(rec, "wb").write(b"SCREEN")
    with open(os.path.join(proj, "footage", "manifest.yaml"), "w") as f:
        json.dump({"clips": [dict(id="rec-board", path=rec, sha256=G.sha256(rec), capture="?view=board")]}, f)
    assert F.main(["--project", proj, "studio", "swap", "--take", rec, "--prompt", "an astronaut"]) == 1
    assert len(api.sent) == 3


GEMINI_TTS = dict(id="google/gemini-3.8-flash-tts", name="Google: Gemini 3.8 Flash TTS", pricing={"prompt": "0.0000005", "completion": "0.000009"},
                  supported_voices=["Kore", "Puck"])
ELEVEN = dict(id="elevenlabs/eleven-v4", name="ElevenLabs: Eleven v4", pricing={"prompt": "0.00008", "completion": "0"}, supported_voices=[])


class FakeSpeech:
    """OpenRouter's speech API as documented: the public catalogue, raw pcm back with an X-Generation-Id, the generation's billed cost."""

    def __init__(self, cost=0.0021):
        self.cost, self.sent = cost, []

    def __call__(self, method, path, body=None, auth=True, raw=False, timeout=60, headers_out=None):
        if path == "/models?output_modalities=speech":
            return {"data": [GEMINI_TTS, ELEVEN]}
        assert os.environ.get("OPENROUTER_API_KEY") == KEY
        if path == "/audio/speech":
            self.sent.append(body)
            headers_out.update({"x-generation-id": "gen-1", "content-type": "audio/pcm;rate=24000;channels=1"})
            return (np.full(24000, 0.25) * 32767).astype("<i2").tobytes()
        if path == "/generation?id=gen-1":
            return {"data": {"total_cost": self.cost}}
        raise AssertionError(path)


@pytest.fixture
def speech_api(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    fake = FakeSpeech()
    monkeypatch.setattr(OR, "_request", fake)
    return fake


def test_a_voice_is_priced_per_character_or_per_audio_token_from_the_catalogue():
    assert OR.speech_estimate(ELEVEN, "x" * 100) == pytest.approx(0.008)
    assert OR.speech_estimate(GEMINI_TTS, "x" * 120) == pytest.approx(120 * 5e-7 + 12 * 25 * 9e-6)


def test_a_take_comes_back_as_samples_and_the_ledger_keeps_its_billed_cost(speech_api):
    x, sr = OR.speech(OR.speech_body(dict(model=GEMINI_TTS["id"], voice="Kore", instructions="warm, unhurried"), "Hello there."))
    assert sr == 24000 and len(x) == 24000 and abs(float(x.max()) - 0.25) < 1e-3
    assert speech_api.sent == [dict(model=GEMINI_TTS["id"], input="Hello there.", voice="Kore", instructions="warm, unhurried", response_format="pcm")]
    row = json.loads(OR.ledger_path().read_text().splitlines()[-1])
    assert row["job_id"] == "gen-1" and row["kind"] == "speech" and row["cost"] is None and row["estimate"] > 0
    assert OR.spend()["today"] == pytest.approx(row["estimate"], abs=1e-4)      # until billed, the estimate counts
    assert OR.settle_costs() == (1, 0)
    assert OR.spend()["today"] == pytest.approx(0.0021) and KEY not in OR.ledger_path().read_text()
    assert OR.settle_costs() == (0, 0)                  # nothing left to settle


def test_a_wrong_model_or_voice_or_an_empty_budget_is_refused_before_anything_is_sent(speech_api, monkeypatch, tmp_path):
    with pytest.raises(OR.OpenRouterError, match="promo vo voices"):
        OR.speech(dict(model="elevenlabs/eleven-v9", input="Hi."))
    with pytest.raises(OR.OpenRouterError, match="no voice 'Nobody'"):
        OR.speech(dict(model=GEMINI_TTS["id"], input="Hi.", voice="Nobody"))
    monkeypatch.setenv("PROMO_GEN_DAILY_USD", "0")
    with pytest.raises(OR.OpenRouterError, match="daily cap"):
        OR.speech(dict(model=ELEVEN["id"], input="Hi.", voice="Rachel"))
    monkeypatch.delenv("PROMO_GEN_DAILY_USD")
    from promo import vo
    from promo.spec import load_spec
    lines = [dict(id=str(i), shot="01", text="A line of about forty characters, said.") for i in range(3)]
    (tmp_path / "promo.yaml").write_text(json.dumps({"output": {"name": "t", "resolution": 1080, "fps": 12, "duration": 4.0}, "timeline": {"bpm": 120, "beats": 8},
                                                     "shots": [{"id": "01", "beats": [0, 8], "type": "card", "text": "x"}],
                                                     "vo": {"engine": "openrouter", "model": ELEVEN["id"], "voice": "Rachel", "asset": "or", "lines": lines}}))
    (tmp_path / "assets.yaml").write_text("assets: []\n")
    with pytest.raises(OR.OpenRouterError, match=r"about \$0.01, over the"):
        vo.run(load_spec(str(tmp_path / "promo.yaml")), max_usd=0.005)     # each line ~ $0.003 on Eleven v4: only the whole run's price passes $0.005
    assert speech_api.sent == []
