"""VieNeu WAV and estimated-caption response contract."""
import base64
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.domains.speech import api as speech_api
from app.main import create_app


def test_aligned_vieneu_response_is_wav_and_marks_estimated_timing(monkeypatch):
    calls = []

    async def fake_synthesize(text, voice):
        calls.append((text, voice))
        return b"RIFFwav-data", 1.0

    monkeypatch.setattr(speech_api, "get_settings", lambda: SimpleNamespace(
        vieneu_model_id="vieneu-v3-turbo", vieneu_voice="Mai Anh"))
    monkeypatch.setattr(speech_api, "_synthesize_vieneu", fake_synthesize)
    speech_api._ALIGNED_TTS_CACHE.clear()
    with TestClient(create_app()) as client:
        first = client.post("/api/v1/tts/synthesize-aligned", json={"text": "Chào em"})
        second = client.post("/api/v1/tts/synthesize-aligned", json={"text": "Chào em"})
    assert first.status_code == second.status_code == 200
    body = first.json()
    assert body == second.json()
    assert base64.b64decode(body["audio_base64"]) == b"RIFFwav-data"
    assert body["audio_mime_type"] == "audio/wav"
    assert body["alignment_kind"] == "estimated"
    assert body["provider"] == "vieneu"
    assert body["model"] == "vieneu-v3-turbo"
    assert body["alignment"]["characters"] == list("Chào em")
    assert calls == [("Chào em", "Mai Anh")]
