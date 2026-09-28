"""
CÓC ĐI LÀM — High-Fidelity Vietnamese Neural TTS Service (§4, §12)
Sử dụng Microsoft Neural Text-to-Speech (Hoài My & Nam Minh)
cho giọng đọc tiếng Việt siêu tự nhiên, chuẩn phát âm, ngắt nghỉ như người thật.
"""

from fastapi import APIRouter, Query, HTTPException, Response
from fastapi.responses import StreamingResponse
import edge_tts
import io
import hashlib
import logging
import time
from app.services.interview_logger import interview_logger

logger = logging.getLogger(__name__)

router = APIRouter()

# Bộ đệm LRU cache trong bộ nhớ cho audio TTS (giảm tối đa độ trễ cho câu hỏi lặp lại)
_AUDIO_CACHE: dict[str, bytes] = {}
_MAX_CACHE_ENTRIES = 200

SUPPORTED_VOICES = {
    "hoaimy": "vi-VN-HoaiMyNeural",     # Giọng nữ phỏng vấn viên chuyên nghiệp, truyền cảm
    "namminh": "vi-VN-NamMinhNeural",   # Giọng nam phỏng vấn viên đĩnh đạc, trầm ấm
}

@router.get("/voices")
async def list_voices():
    """Danh sách giọng đọc tiếng Việt chất lượng cao."""
    return {
        "default": "vi-VN-HoaiMyNeural",
        "voices": [
            {
                "id": "vi-VN-HoaiMyNeural",
                "alias": "hoaimy",
                "name": "Hoài My (Nữ - Truyền cảm, chuẩn phỏng vấn viên)",
                "gender": "Female",
                "locale": "vi-VN",
            },
            {
                "id": "vi-VN-NamMinhNeural",
                "alias": "namminh",
                "name": "Nam Minh (Nam - Chững chạc, chuyên nghiệp)",
                "gender": "Male",
                "locale": "vi-VN",
            },
        ],
    }

@router.get("/synthesize")
async def synthesize_speech(
    text: str = Query(..., min_length=1, description="Đoạn văn bản tiếng Việt cần đọc"),
    voice: str = Query("vi-VN-HoaiMyNeural", description="Giọng đọc Neural (vi-VN-HoaiMyNeural hoặc vi-VN-NamMinhNeural)"),
    rate: str = Query("+0%", description="Tốc độ đọc (+0%, +10%, -5%...)"),
):
    """
    Tổng hợp tiếng nói tiếng Việt chuẩn Neural bằng Microsoft Edge TTS.
    Trả về định dạng audio/mpeg phát mượt mà trên mọi trình duyệt.
    """
    clean_text = text.strip()
    if not clean_text:
        raise HTTPException(status_code=400, detail="Văn bản không được để trống")

    # Chuẩn hóa voice
    target_voice = voice
    if voice.lower() in SUPPORTED_VOICES:
        target_voice = SUPPORTED_VOICES[voice.lower()]
    elif voice not in SUPPORTED_VOICES.values():
        target_voice = "vi-VN-HoaiMyNeural"

    # Bắt đầu đo thời gian tổng hợp
    t_start = time.perf_counter()

    # Kiểm tra bộ đệm cache
    cache_key = hashlib.md5(f"{target_voice}:{rate}:{clean_text}".encode("utf-8")).hexdigest()
    if cache_key in _AUDIO_CACHE:
        latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
        audio_cached = _AUDIO_CACHE[cache_key]
        interview_logger.add_log(
            stage="NEURAL_TTS",
            message=f"Xuất âm thanh Neural TTS (Bộ đệm Cache): {len(clean_text.split())} từ ({round(len(audio_cached)/1024, 1)} KB trong {latency_ms}ms)",
            details={
                "voice": target_voice,
                "text": clean_text[:120],
                "word_count": len(clean_text.split()),
                "audio_size_bytes": len(audio_cached),
                "audio_size_kb": round(len(audio_cached) / 1024, 1),
                "latency_ms": latency_ms,
                "cache_hit": True,
            },
        )
        return Response(
            content=audio_cached,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-TTS-Source": "cache",
            },
        )

    try:
        communicate = edge_tts.Communicate(clean_text, target_voice, rate=rate)
        audio_buffer = io.BytesIO()

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        audio_bytes = audio_buffer.getvalue()
        if not audio_bytes:
            raise HTTPException(status_code=500, detail="Không thể tạo luồng âm thanh")

        latency_ms = round((time.perf_counter() - t_start) * 1000, 1)
        interview_logger.add_log(
            stage="NEURAL_TTS",
            message=f"Tổng hợp giọng nói Neural TTS [{target_voice}]: {len(clean_text.split())} từ ({round(len(audio_bytes)/1024, 1)} KB trong {latency_ms}ms)",
            details={
                "voice": target_voice,
                "text": clean_text[:120],
                "word_count": len(clean_text.split()),
                "audio_size_bytes": len(audio_bytes),
                "audio_size_kb": round(len(audio_bytes) / 1024, 1),
                "latency_ms": latency_ms,
                "cache_hit": False,
            },
        )

        # Lưu cache
        if len(_AUDIO_CACHE) >= _MAX_CACHE_ENTRIES:
            # Xóa 20% mục cũ nhất
            keys_to_remove = list(_AUDIO_CACHE.keys())[:40]
            for k in keys_to_remove:
                _AUDIO_CACHE.pop(k, None)

        _AUDIO_CACHE[cache_key] = audio_bytes

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=86400",
                "X-TTS-Source": "edge-neural",
            },
        )

    except Exception as e:
        logger.error(f"TTS synthesis error for text '{clean_text[:40]}...': {e}")
        raise HTTPException(status_code=500, detail=f"Lỗi tổng hợp giọng nói: {str(e)}")
