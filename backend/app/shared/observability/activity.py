"""
CÓC ĐI LÀM — Interview Session Live Logger (§4, §8, §16)
Quản lý in-memory ring buffer log của phiên phỏng vấn trực tiếp:
Input/partial ASR -> Laya streaming/clarification -> ASR Gate -> live question/TTS;
final rubric runs only after the session ends.
"""

from typing import Any, Optional
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)


class InterviewLogManager:
    """Quản lý in-memory ring buffer log của buổi phỏng vấn trực tiếp."""

    def __init__(self, max_logs: int = 300):
        self.logs: list[dict[str, Any]] = []
        self.max_logs = max_logs
        # Log khởi động hệ thống
        self.add_log(
            stage="SYSTEM_READY",
            message="Hệ thống Interview Turn & Neural Audio Engine đã sẵn sàng tiếp nhận luồng phỏng vấn.",
            details={"status": "ONLINE", "tts_engine": "VieNeu local", "stt_engine": "Qwen3-ASR local", "decision_controller": "Laya multilingual local model; deterministic fallback if unavailable"},
        )

    def add_log(
        self,
        stage: str,
        message: str,
        session_id: Optional[str] = None,
        turn_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ):
        entry = {
            "id": f"turn_log_{uuid.uuid4().hex[:10]}",
            "timestamp": datetime.now().strftime("%H:%M:%S.%f")[:-3],
            "stage": stage.upper(),
            "session_id": session_id or "",
            "turn_id": turn_id or "",
            "message": message,
            "details": details or {},
        }
        self.logs.append(entry)
        if len(self.logs) > self.max_logs:
            self.logs.pop(0)

        logger.info(f"[InterviewLive:{stage.upper()}] {message}")

    def get_logs(self, limit: int = 50, session_id: Optional[str] = None) -> list[dict[str, Any]]:
        if session_id:
            filtered = [l for l in self.logs if l.get("session_id") == session_id]
            return filtered[-limit:]
        return self.logs[-limit:]

    def clear(self):
        self.logs.clear()


# Singleton
interview_logger = InterviewLogManager()
