"""Qwen3-ASR upload route, local-only behavior and error handling."""
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.domains.speech import api as speech_api
from app.main import create_app


def test_qwen_transcribes_uploaded_audio_and_cleans_temp_file(monkeypatch):
    captured = {}

    class Model:
        def transcribe(self, *, audio, language):
            captured.update(path=audio, language=language, bytes=Path(audio).read_bytes())
            return [SimpleNamespace(text="Xin chào em.")]

    monkeypatch.setattr(speech_api, "_get_qwen_asr_model", lambda: Model())
    monkeypatch.setattr(speech_api, "get_settings", lambda: SimpleNamespace(stt_model_id="Qwen3-ASR-1.7B"))
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/stt/transcribe?language=vi",
                               files={"file": ("answer.wav", b"RIFFtest-audio", "audio/wav")})
        token = client.post("/api/v1/stt/token/ses_old")
    assert response.status_code == 200
    assert response.json() == {"text": "Xin chào em.", "model_id": "Qwen3-ASR-1.7B", "language": "vi"}
    assert captured["language"] == "Vietnamese"
    assert captured["bytes"] == b"RIFFtest-audio"
    assert not Path(captured["path"]).exists()
    assert token.status_code == 404


def test_qwen_unavailable_is_explicit_503(monkeypatch):
    monkeypatch.setattr(speech_api, "_get_qwen_asr_model", lambda: (_ for _ in ()).throw(RuntimeError("model missing")))
    with TestClient(create_app()) as client:
        response = client.post("/api/v1/stt/transcribe",
                               files={"file": ("answer.wav", b"RIFF", "audio/wav")})
    assert response.status_code == 503
    assert "Qwen3-ASR" in response.json()["detail"]
