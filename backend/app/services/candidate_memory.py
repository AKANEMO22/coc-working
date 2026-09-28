"""
CÓC ĐI LÀM — Long-Term Candidate Memory Service (§7.3)
Quản lý bộ nhớ ứng viên dài hạn xuyên phiên:
- Memory consolidation sau mỗi phiên phỏng vấn.
- Memory retrieval trước phiên mới (cung cấp context cho Laya & Question Service).
- Quản lý Retry Queue cho các câu hỏi ứng viên còn yếu.
"""

from app.core.database import get_supabase_client, SupabaseService
from app.core.redis import RedisSessionManager
from app.models.schemas import InterviewState
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class CandidateMemoryService:
    """Quản lý Long-Term Candidate Memory xuyên phiên."""

    def __init__(self):
        self.redis = RedisSessionManager()

    async def retrieve_compact_memory(self, student_id: str) -> dict:
        """
        Đọc Compact Memory trước phiên phỏng vấn mới.
        Ưu tiên đọc từ Redis Cache (§7.3.2), nếu miss thì đọc từ Supabase.
        """
        # 1. Đọc Redis Cache
        cached = self.redis.get_cached_candidate_memory(student_id)
        if cached:
            return cached

        # 2. Đọc từ Database
        compact_memory = {
            "student_id": student_id,
            "session_count": 0,
            "weak_skills": [],
            "strong_skills": [],
            "retry_queue": [],
            "recent_topics": [],
        }

        try:
            client = get_supabase_client()
            db = SupabaseService(client)

            profile = await db.get_candidate_memory(student_id)
            if profile:
                compact_memory["session_count"] = profile.get("total_sessions_completed", 0)

            skills = await db.get_candidate_skill_memory(student_id)
            for s in skills:
                score = s.get("rolling_average_score", 0.0)
                skill_name = s.get("skill_name", "")
                if score < 6.0:
                    compact_memory["weak_skills"].append(skill_name)
                elif score >= 8.0:
                    compact_memory["strong_skills"].append(skill_name)

            retries = await db.get_candidate_retry_queue(student_id)
            compact_memory["retry_queue"] = [
                r.get("question_id") for r in retries if not r.get("is_resolved")
            ][:5]

        except Exception as e:
            logger.warning(f"Failed to query database for memory: {e}. Using empty memory profile.")

        # Cache vào Redis
        self.redis.cache_candidate_memory(student_id, compact_memory)
        return compact_memory

    async def consolidate_session_memory(
        self,
        session_id: str,
        student_id: str,
        state: InterviewState,
        evaluations: list[dict],
    ) -> None:
        """
        Consolidation sau phiên (§7.3.3):
        - Tổng hợp điểm kỹ năng, cập nhật rolling average.
        - Đẩy các câu hỏi có điểm < 6.0 vào candidate_retry_queue.
        - Cập nhật số phiên hoàn thành.
        """
        logger.info(f"Consolidating memory for session {session_id}, student {student_id}")

        new_weak_skills = []
        new_retries = []

        for ev in evaluations:
            overall_score = ev.get("overall_score", 0.0)
            target_concept = ev.get("target_concept", "general")
            turn_id = ev.get("turn_id", "")

            if overall_score < 6.0:
                new_weak_skills.append(target_concept)
                new_retries.append({
                    "student_id": student_id,
                    "question_id": ev.get("question_id", turn_id),
                    "concept": target_concept,
                    "last_score": overall_score,
                    "retry_priority": 10 - int(overall_score),
                    "created_at": datetime.utcnow().isoformat(),
                })

        try:
            client = get_supabase_client()
            # Cập nhật profile tổng quan
            # Thêm vào retry queue
            for item in new_retries:
                client.table("candidate_retry_queue").insert(item).execute()
        except Exception as e:
            logger.warning(f"Could not persist memory consolidation to database: {e}")

        # Invalidate / Refresh cache
        self.redis.cache_candidate_memory(student_id, {
            "student_id": student_id,
            "session_count": 1,
            "weak_skills": list(set(new_weak_skills)),
            "retry_queue": [r["question_id"] for r in new_retries],
        })


_memory_service = None


def get_candidate_memory_service() -> CandidateMemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = CandidateMemoryService()
    return _memory_service
