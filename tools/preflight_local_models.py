"""Readiness check for the actual local interview speech/decision model stack."""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import create_app  # noqa: E402
from app.shared.config import get_settings  # noqa: E402


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    settings = get_settings()
    print("CONFIG", json.dumps({
        "tts_provider": settings.tts_provider,
        "tts_model": settings.vieneu_model_id,
        "tts_voice": settings.vieneu_voice,
        "tts_device": settings.vieneu_device,
        "stt_model": settings.stt_model_path,
        "stt_device": settings.stt_device,
        "decision_model": settings.laya_model_path,
        "decision_device": settings.laya_device,
        "decision_fast": settings.laya_fast,
        "question_model": settings.gemini_flash_model,
    }, ensure_ascii=False), flush=True)
    started = time.perf_counter()
    with TestClient(create_app()) as client:
        health = client.get("/health").json()
        print("HEALTH", json.dumps({"laya_loaded": health.get("laya_model_loaded"),
                                     "laya_backend": health.get("laya_backend"),
                                     "controller": health.get("controller"),
                                     "startup_sec": round(time.perf_counter() - started, 2)}), flush=True)
        tts_started = time.perf_counter()
        tts = client.post("/api/v1/tts/synthesize-aligned", json={"text": "Xin chào em. Đây là buổi phỏng vấn thử."})
        print("TTS", json.dumps({"http": tts.status_code,
                                  "latency_sec": round(time.perf_counter() - tts_started, 2),
                                  "provider": tts.json().get("provider") if tts.status_code == 200 else None,
                                  "model": tts.json().get("model") if tts.status_code == 200 else None,
                                  "error": tts.json().get("detail") if tts.status_code != 200 else None}), flush=True)
        if tts.status_code != 200:
            return 1
        payload = tts.json()
        audio = base64.b64decode(payload["audio_base64"])
        print("AUDIO", json.dumps({"wav_magic": audio[:4].decode("ascii", "replace"),
                                    "bytes": len(audio), "alignment_kind": payload.get("alignment_kind")}), flush=True)
        stt_started = time.perf_counter()
        stt = client.post("/api/v1/stt/transcribe?language=vi",
                          files={"file": ("synthetic.wav", audio, "audio/wav")})
        print("STT", json.dumps({"http": stt.status_code,
                                  "latency_sec": round(time.perf_counter() - stt_started, 2),
                                  "result": stt.json() if stt.status_code == 200 else {"detail": stt.json().get("detail")}},
                                 ensure_ascii=False), flush=True)
        return 0 if health.get("laya_model_loaded") and stt.status_code == 200 and stt.json().get("text") else 1


if __name__ == "__main__":
    raise SystemExit(main())
