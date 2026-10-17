"""Local Vietnamese speech: VieNeu TTS and Qwen3-ASR."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, Field

from app.shared.config import get_settings
from app.shared.observability.activity import interview_logger

logger = logging.getLogger(__name__)
router = APIRouter()
stt_router = APIRouter()

_QWEN_MODEL: Any = None
_VIENEU_MODEL: Any = None
_QWEN_LOCK = threading.Lock()
_VIENEU_LOCK = threading.Lock()
_QWEN_INFERENCE_LOCK = threading.Lock()
_VIENEU_INFERENCE_LOCK = threading.Lock()
_AUDIO_CACHE: dict[str, bytes] = {}
_ALIGNED_TTS_CACHE: dict[str, dict[str, Any]] = {}
_MAX_CACHE_ENTRIES = 200
_MAX_STT_BYTES = 16 * 1024 * 1024

VIENEU_PRESET_VOICES = [
    {"id": "Hải Đăng", "name": "Hải Đăng — Nam · Bắc", "locale": "vi"},
    {"id": "Mai Anh", "name": "Mai Anh — Nữ · Bắc", "locale": "vi"},
    {"id": "Trúc Ly", "name": "Trúc Ly — Nữ · Bắc", "locale": "vi"},
    {"id": "Thùy Dung", "name": "Thùy Dung — Nữ · Nam", "locale": "vi"},
    {"id": "Xuân Vĩnh", "name": "Xuân Vĩnh — Nam · Bắc", "locale": "vi"},
    {"id": "Thái Sơn", "name": "Thái Sơn — Nam · Nam", "locale": "vi"},
    {"id": "Ngọc Linh", "name": "Ngọc Linh — Nữ · Bắc", "locale": "vi"},
    {"id": "Quang Sơn", "name": "Quang Sơn — Nam · Trung", "locale": "vi"},
]


class AlignedSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    voice: str | None = None
    session_id: str | None = Field(default=None, max_length=80)


class TranscriptionResponse(BaseModel):
    text: str
    model_id: str
    language: str


def _get_qwen_asr_model() -> Any:
    global _QWEN_MODEL
    if _QWEN_MODEL is not None:
        return _QWEN_MODEL
    with _QWEN_LOCK:
        if _QWEN_MODEL is None:
            import torch
            from qwen_asr import Qwen3ASRModel

            settings = get_settings()
            device = settings.stt_device
            if device == "auto":
                device = "cuda:0" if torch.cuda.is_available() else "cpu"
            elif device == "cuda":
                if not torch.cuda.is_available():
                    raise RuntimeError("STT_DEVICE=cuda nhưng CUDA không khả dụng")
                device = "cuda:0"
            dtype = torch.bfloat16 if device.startswith("cuda") else torch.float32
            logger.info("Loading Qwen3-ASR from %s on %s", settings.stt_model_path, device)
            _QWEN_MODEL = Qwen3ASRModel.from_pretrained(
                settings.stt_model_path, dtype=dtype, device_map=device,
                max_inference_batch_size=1, max_new_tokens=256,
            )
    return _QWEN_MODEL


def _get_vieneu_tts_model() -> Any:
    global _VIENEU_MODEL
    if _VIENEU_MODEL is not None:
        return _VIENEU_MODEL
    with _VIENEU_LOCK:
        if _VIENEU_MODEL is None:
            from vieneu import Vieneu

            settings = get_settings()
            if settings.vieneu_model_id != "vieneu-v3-turbo":
                raise RuntimeError(f"VieNeu model không được hỗ trợ: {settings.vieneu_model_id}")
            os.environ.setdefault("VIENEU_FUSED_FRAME", "0")
            logger.info("Loading local VieNeu TTS %s", settings.vieneu_model_id)
            _VIENEU_MODEL = Vieneu(
                mode="v3turbo", device=settings.vieneu_device,
                max_batch_size=settings.vieneu_max_batch_size,
                max_streams=settings.vieneu_max_streams,
            )
    return _VIENEU_MODEL


async def _synthesize_vieneu(text: str, voice_id: str) -> tuple[bytes, float]:
    model = await asyncio.to_thread(_get_vieneu_tts_model)
    # VieNeu.infer(text, ref_audio=None, voice=None); voice must be keyword-only here.
    settings = get_settings()
    def infer():
        with _VIENEU_INFERENCE_LOCK:
            return model.infer(
                text, voice=voice_id,
                temperature=settings.vieneu_temperature,
                top_k=settings.vieneu_top_k,
                top_p=settings.vieneu_top_p,
            )
    waveform = await asyncio.to_thread(infer)
    sample_rate = int(getattr(model, "sample_rate", 48000))
    if sample_rate <= 0 or len(waveform) == 0:
        raise RuntimeError("VieNeu trả audio rỗng hoặc sample rate không hợp lệ")
    import numpy as np
    import soundfile as sf

    if hasattr(waveform, "cpu"):
        waveform = waveform.cpu().numpy()
    elif not isinstance(waveform, np.ndarray):
        waveform = np.asarray(waveform, dtype=np.float32)

    raw_duration = len(waveform) / sample_rate
    # 150ms leading silence + 80ms trailing silence padding
    # Prevents hardware DAC attack time / Bluetooth amp sleep ramp-up clipping the first syllable
    leading_pad = np.zeros(int(sample_rate * 0.15), dtype=waveform.dtype)
    trailing_pad = np.zeros(int(sample_rate * 0.08), dtype=waveform.dtype)
    padded = np.concatenate([leading_pad, waveform, trailing_pad])

    output = io.BytesIO()
    sf.write(output, padded, sample_rate, format="WAV")
    return output.getvalue(), raw_duration


def _voice(requested: str | None) -> str:
    return (requested or get_settings().vieneu_voice).strip()


def _cache_put(cache: dict, key: str, value: Any) -> None:
    if len(cache) >= _MAX_CACHE_ENTRIES:
        for old in list(cache)[:40]:
            cache.pop(old, None)
    cache[key] = value


@stt_router.post("/transcribe", response_model=TranscriptionResponse)
async def transcribe_audio(file: UploadFile = File(...), language: str = Query("vi"),
                           session_id: str | None = Query(default=None, max_length=80),
                           kind: str = Query("final", pattern="^(partial|final)$")):
    """Transcribe one microphone utterance with the configured local Qwen model."""
    content = await file.read(_MAX_STT_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="File âm thanh rỗng.")
    if len(content) > _MAX_STT_BYTES:
        raise HTTPException(status_code=413, detail="Audio vượt giới hạn 16 MB.")
    settings = get_settings()
    suffix = Path(file.filename or "speech.wav").suffix.lower()
    if suffix not in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
        raise HTTPException(status_code=415, detail="Định dạng audio không được hỗ trợ.")
    audio_duration_sec = None
    if suffix == ".wav":
        try:
            import wave
            with wave.open(io.BytesIO(content), "rb") as wav:
                audio_duration_sec = round(wav.getnframes() / wav.getframerate(), 2)
        except (wave.Error, ZeroDivisionError, EOFError):
            pass
    temp_path: str | None = None
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            temp_path = temporary.name
        model = await asyncio.to_thread(_get_qwen_asr_model)
        lang = "Vietnamese" if language.lower() in {"vi", "vie", "vi-vn"} else language
        def infer():
            with _QWEN_INFERENCE_LOCK:
                return model.transcribe(audio=temp_path, language=lang)
        results = await asyncio.to_thread(infer)
        transcript = (results[0].text if results else "").strip()
        for prefix in ("_idle!", "_start!", "_end!", "_idle", "_start"):
            if transcript.startswith(prefix):
                transcript = transcript[len(prefix):].strip()
        interview_logger.add_log(
            stage="LOCAL_STT", message="Qwen3-ASR transcribed local microphone audio",
            session_id=session_id,
            details={"model": settings.stt_model_id, "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                     "text_length": len(transcript), "kind": kind,
                     "audio_duration_sec": audio_duration_sec},
        )
        return TranscriptionResponse(text=transcript, model_id=settings.stt_model_id, language=language)
    except Exception as exc:
        logger.exception("Local Qwen3-ASR transcription failed")
        raise HTTPException(status_code=503, detail=f"Qwen3-ASR không khả dụng: {type(exc).__name__}") from exc
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)


@router.get("/voices")
async def list_voices():
    settings = get_settings()
    return {"default_provider": "vieneu", "default_model": settings.vieneu_model_id,
            "default": settings.vieneu_voice,
            "voices": [{**voice, "provider": "vieneu"} for voice in VIENEU_PRESET_VOICES]}


@router.get("/synthesize")
async def synthesize_speech(
    text: str = Query(..., min_length=1), voice: str | None = None,
    provider: str = Query("auto", pattern="^(auto|vieneu)$"),
):
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Văn bản không được để trống")
    settings = get_settings()
    target_voice = _voice(voice)
    cache_key = hashlib.sha256(f"{settings.vieneu_model_id}:{target_voice}:{clean_text}".encode()).hexdigest()
    started = time.perf_counter()
    audio = _AUDIO_CACHE.get(cache_key)
    cache_hit = audio is not None
    if audio is None:
        try:
            audio, _ = await _synthesize_vieneu(clean_text, target_voice)
        except Exception as exc:
            logger.exception("VieNeu TTS synthesis failed")
            raise HTTPException(status_code=503, detail=f"VieNeu TTS không khả dụng: {type(exc).__name__}") from exc
        _cache_put(_AUDIO_CACHE, cache_key, audio)
    interview_logger.add_log(
        stage="NEURAL_TTS", message="Local VieNeu TTS produced WAV",
        details={"provider": "vieneu", "model": settings.vieneu_model_id, "voice": target_voice,
                 "latency_ms": round((time.perf_counter() - started) * 1000, 1), "cache_hit": cache_hit},
    )
    return Response(content=audio, media_type="audio/wav", headers={"X-TTS-Provider": "vieneu", "X-TTS-Source": "vieneu"})


@router.post("/synthesize-aligned")
async def synthesize_aligned_speech(request: AlignedSpeechRequest):
    clean_text = request.text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Văn bản không được để trống")
    settings = get_settings()
    target_voice = _voice(request.voice)
    cache_key = hashlib.sha256(f"aligned:{settings.vieneu_model_id}:{target_voice}:{clean_text}".encode()).hexdigest()
    cached = _ALIGNED_TTS_CACHE.get(cache_key)
    if cached is not None:
        interview_logger.add_log(
            stage="NEURAL_TTS_ALIGNED", message="Local VieNeu TTS WAV served from cache",
            session_id=request.session_id,
            details={"provider": "vieneu", "model": settings.vieneu_model_id,
                     "voice": target_voice, "latency_ms": 0.0, "cache_hit": True},
        )
        return cached
    started = time.perf_counter()
    try:
        audio, duration = await _synthesize_vieneu(clean_text, target_voice)
    except Exception as exc:
        logger.exception("VieNeu aligned TTS synthesis failed")
        raise HTTPException(status_code=503, detail=f"VieNeu TTS không khả dụng: {type(exc).__name__}") from exc
    chars = list(clean_text)
    count = len(chars)
    leading_offset = 0.15
    alignment = {"characters": chars,
                 "character_start_times_seconds": [round(leading_offset + i * duration / count, 3) for i in range(count)],
                 "character_end_times_seconds": [round(leading_offset + (i + 1) * duration / count, 3) for i in range(count)]}
    body = {"audio_base64": base64.b64encode(audio).decode("ascii"),
            "alignment": alignment, "normalized_alignment": alignment,
            "alignment_kind": "estimated", "audio_mime_type": "audio/wav",
            "text": clean_text, "provider": "vieneu", "model": settings.vieneu_model_id,
            "character_cost": "0"}
    _cache_put(_ALIGNED_TTS_CACHE, cache_key, body)
    interview_logger.add_log(
        stage="NEURAL_TTS_ALIGNED", message="Local VieNeu TTS produced WAV and estimated caption timings",
        session_id=request.session_id,
        details={"provider": "vieneu", "model": settings.vieneu_model_id, "voice": target_voice,
                 "latency_ms": round((time.perf_counter() - started) * 1000, 1), "alignment_kind": "estimated"},
    )
    return body
