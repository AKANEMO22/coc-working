"""
CÓC ĐI LÀM — Evaluation Queue Service
Retry PENDING_EVALUATION jobs asynchronously (§6.4).
"""

import logging
from datetime import datetime
from app.core.redis import RedisSessionManager

logger = logging.getLogger(__name__)


class EvaluationQueue:
    """Hàng đợi retry cho turns PENDING_EVALUATION (§6.4)."""

    def __init__(self):
        self.pending_jobs: list[dict] = []

    async def enqueue(self, turn_id: str, session_id: str, rubric_type: str, context: dict):
        """Đưa turn vào hàng đợi retry."""
        job = {
            "turn_id": turn_id,
            "session_id": session_id,
            "rubric_type": rubric_type,
            "context": context,
            "enqueued_at": datetime.utcnow().isoformat(),
            "retry_count": 0,
            "max_retries": 3,
        }
        self.pending_jobs.append(job)
        logger.info(f"Enqueued evaluation job: turn={turn_id}, session={session_id}")

    async def process_pending(self):
        """Xử lý các jobs pending (chạy background)."""
        from app.services.evidence_evaluator import get_evidence_evaluator
        from app.models.schemas import RubricType
        evaluator = get_evidence_evaluator()

        completed = []
        for job in list(self.pending_jobs):
            if job["retry_count"] >= job["max_retries"]:
                logger.warning(f"Max retries reached for turn={job['turn_id']}")
                completed.append(job)
                continue

            job["retry_count"] += 1
            logger.info(f"Retrying evaluation: turn={job['turn_id']}, attempt={job['retry_count']}")

            try:
                ctx = job.get("context", {})
                result = await evaluator.evaluate(
                    turn_id=job["turn_id"],
                    rubric_type=RubricType(job["rubric_type"]),
                    verified_transcript=ctx.get("transcript", ""),
                    current_question=ctx.get("question", ""),
                    candidate_context=ctx.get("candidate_context", {}),
                    company_context=ctx.get("company_context"),
                )
                if result is not None:
                    logger.info(f"Evaluation retry succeeded for turn={job['turn_id']}")
                    redis = RedisSessionManager()
                    turn_eval = {
                        "turn_number": len(redis.get_turn_evaluations(job["session_id"])) + 1,
                        "turn_id": job["turn_id"],
                        "stage": ctx.get("stage", "technical_core"),
                        "rubric_type": job["rubric_type"],
                        "question": ctx.get("question", ""),
                        "candidate_answer": ctx.get("transcript", ""),
                        "score": round(result.score, 1),
                        "confidence": result.evaluation_confidence,
                        "candidate_summary": "; ".join(result.points_awarded[:3]) if result.points_awarded else "Đã hoàn thành đánh giá lại.",
                        "better_answer_hint": "Cần bổ sung: " + "; ".join(result.points_missed[:2]) if result.points_missed else "Đã đạt chuẩn.",
                        "points_awarded": result.points_awarded,
                        "points_missed": result.points_missed,
                        "payload": result.payload,
                        "evaluated_at": datetime.utcnow().isoformat(),
                    }
                    redis.save_turn_evaluation(job["session_id"], turn_eval)
                    completed.append(job)
            except Exception as e:
                logger.error(f"Retry evaluation failed for turn={job['turn_id']}: {e}")

        for job in completed:
            if job in self.pending_jobs:
                self.pending_jobs.remove(job)


_queue_instance: EvaluationQueue | None = None


def get_evaluation_queue() -> EvaluationQueue:
    global _queue_instance
    if _queue_instance is None:
        _queue_instance = EvaluationQueue()
    return _queue_instance
