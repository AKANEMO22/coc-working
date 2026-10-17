"""Local VieNeu TTS route and model-call regression tests."""
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.domains.speech import api as speech_api
from app.main import create_app


def _settings():
    return SimpleNamespace(vieneu_model_id="vieneu-v3-turbo", vieneu_voice="Hải Đăng",
                           vieneu_temperature=0.8, vieneu_top_k=25, vieneu_top_p=0.95)


def test_vieneu_model_receives_voice_as_keyword(monkeypatch):
    captured = {}

    class Model:
        sample_rate = 48000

        def infer(self, text, ref_audio=None, voice=None, **kwargs):
            captured.update(text=text, ref_audio=ref_audio, voice=voice, kwargs=kwargs)
            return [0.0] * 4800

    monkeypatch.setattr(speech_api, "_get_vieneu_tts_model", lambda: Model())
    monkeypatch.setattr(speech_api, "get_settings", _settings)
    audio, duration = asyncio.run(speech_api._synthesize_vieneu("Xin chào", "Hải Đăng"))
    assert audio[:4] == b"RIFF"
    assert duration == 0.1
    assert captured["ref_audio"] is None
    assert captured["voice"] == "Hải Đăng"
    assert captured["kwargs"]["temperature"] == 0.8


def test_local_tts_route_returns_wav_and_no_provider_fallback(monkeypatch):
    async def fake_synthesize(text, voice):
        assert (text, voice) == ("Chào em", "Hải Đăng")
        return b"RIFFlocal-wave", 1.0

    monkeypatch.setattr(speech_api, "get_settings", _settings)
    monkeypatch.setattr(speech_api, "_synthesize_vieneu", fake_synthesize)
    speech_api._AUDIO_CACHE.clear()
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tts/synthesize", params={"text": "Chào em"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.headers["x-tts-provider"] == "vieneu"
    assert response.content == b"RIFFlocal-wave"


def test_vieneu_failure_is_reported_without_remote_provider(monkeypatch):
    async def fail(*_args):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(speech_api, "get_settings", _settings)
    monkeypatch.setattr(speech_api, "_synthesize_vieneu", fail)
    speech_api._AUDIO_CACHE.clear()
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/tts/synthesize", params={"text": "Lỗi local"})
    assert response.status_code == 503
    assert "VieNeu" in response.json()["detail"]
    assert "ElevenLabs" not in response.text
