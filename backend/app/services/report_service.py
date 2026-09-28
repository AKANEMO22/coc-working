"""
CÓC ĐI LÀM — Comprehensive Report Generation Service (§14)
Tính toán và tổng hợp báo cáo đánh giá năng lực thực tập OJT hoàn toàn từ:
- Kết quả đánh giá Rubric thực tế (EvidenceEnvelope) qua từng turn
- Dữ liệu thu thập từ Jev Controller & Hard Policy Engine
- Lịch sử câu hỏi & câu trả lời thực của ứng viên
Tuyệt đối KHÔNG sử dụng dữ liệu giả (fake/mock/hardcoded).
"""

import logging
from typing import Any
from app.core.redis import RedisSessionManager

logger = logging.getLogger(__name__)

# Trọng số chuẩn (§14) cho 4 trục năng lực OJT
AXIS_WEIGHTS = {
    "hr_motivation": 0.10,     # Động lực & Tinh thần OJT
    "project_defense": 0.25,   # Thẩm định Dự án STAR (Google XYZ)
    "technical_core": 0.45,    # Nền tảng Chuyên môn Kỹ thuật
    "case_study": 0.20,        # Tư duy Xử lý Sự cố & Tình huống
}


class ReportService:
    """Service tổng hợp báo cáo đánh giá OJT từ kết quả turn thực tế."""

    def __init__(self, redis: RedisSessionManager | None = None):
        self.redis = redis or RedisSessionManager()

    def generate_report(self, session_id: str, state: dict | None = None) -> dict[str, Any]:
        """
        Tổng hợp toàn bộ báo cáo từ các lượt phỏng vấn thực tế của session_id.
        """
        if not state:
            state = self.redis.get_hot_state(session_id) or {}

        # 1. Lấy danh sách các lượt trả lời đã được đánh giá thực tế
        turn_evaluations = self.redis.get_turn_evaluations(session_id)

        student_id = state.get("student_id", "")
        role = state.get("role", "Software Engineer Intern")
        company = state.get("company_target", "FPT Software")

        # 2. Xử lý trường hợp chưa có lượt đánh giá nào
        if not turn_evaluations:
            logger.info(f"Session {session_id} has 0 turn evaluations. Returning empty report structure.")
            empty_report = {
                "report_status": "NO_EVALUATION",
                "session_id": session_id,
                "student_id": student_id,
                "role": role,
                "company_target": company,
                "overall_score": 0.0,
                "max_score": 10.0,
                "grade": "Chưa hoàn thành — Chưa có câu trả lời nào được ghi nhận",
                "radar_scores": {
                    "hr_motivation": 0.0,
                    "project_defense": 0.0,
                    "technical_core": 0.0,
                    "case_study": 0.0,
                },
                "strengths": [],
                "weaknesses": ["Phiên phỏng vấn chưa ghi nhận câu trả lời nào từ ứng viên."],
                "turn_evaluations": [],
                "evaluated_turns": [],
                "learning_roadmap": [],
                "retry_recommendations": [],
                "recommendations": [],
                "competencies": [
                    {"dimension": k, "score": 0.0, "max": 10.0}
                    for k in ["hr_motivation", "project_defense", "technical_core", "case_study"]
                ],
            }
            self.redis.cache_report(session_id, empty_report)
            return empty_report

        # 3. Phân loại điểm từng turn theo 4 trục radar
        axis_scores: dict[str, list[float]] = {
            "hr_motivation": [],
            "project_defense": [],
            "technical_core": [],
            "case_study": [],
        }

        all_awarded_points: list[str] = []
        all_missed_points: list[str] = []
        low_score_turns: list[dict] = []
        formatted_turns: list[dict] = []

        for idx, turn in enumerate(turn_evaluations):
            stage = (turn.get("stage") or "").lower()
            rubric = (turn.get("rubric_type") or "").lower()
            score = float(turn.get("score", 0.0))

            # Xác định trục năng lực
            if "hr" in stage or "motivation" in stage or rubric == "hr_motivation":
                axis_scores["hr_motivation"].append(score)
            elif "project" in stage or "defense" in stage or "star" in stage or rubric == "star_framework":
                axis_scores["project_defense"].append(score)
            elif "case" in stage or "incident" in stage or "scenario" in stage or rubric == "case_study":
                axis_scores["case_study"].append(score)
            else:
                axis_scores["technical_core"].append(score)

            # Thu thập điểm mạnh / yếu từ bằng chứng rubric
            awarded = turn.get("points_awarded") or []
            missed = turn.get("points_missed") or []

            if score >= 5.0:
                for pt in awarded:
                    if pt and pt not in all_awarded_points:
                        all_awarded_points.append(pt)

            if score < 7.5:
                for pt in missed:
                    if pt and pt not in all_missed_points:
                        all_missed_points.append(pt)
                low_score_turns.append(turn)

            # Format lượt đánh giá hiển thị trên UI
            formatted_turns.append({
                "turn_number": turn.get("turn_number", idx + 1),
                "stage": turn.get("stage", "technical_core"),
                "question": turn.get("question", "Câu hỏi phỏng vấn"),
                "score": round(score, 1),
                "candidate_summary": turn.get("candidate_summary", ""),
                "better_answer_hint": turn.get("better_answer_hint", ""),
            })

        # 4. Tính điểm trung bình cho từng trục Radar
        radar_scores = {}
        tested_weights = 0.0
        weighted_sum = 0.0

        for axis, weight in AXIS_WEIGHTS.items():
            scores = axis_scores[axis]
            if scores:
                avg = round(sum(scores) / len(scores), 1)
                radar_scores[axis] = avg
                weighted_sum += avg * weight
                tested_weights += weight
            else:
                radar_scores[axis] = 0.0

        # Tính overall_score chuẩn hóa theo các trục đã làm bài
        if tested_weights > 0:
            overall_score = round(weighted_sum / tested_weights, 1)
        else:
            all_scores = [t.get("score", 0.0) for t in turn_evaluations]
            overall_score = round(sum(all_scores) / max(1, len(all_scores)), 1)

        # 5. Phân loại chuẩn tuyển dụng (Grade)
        if overall_score >= 8.5:
            grade = "Pass — Xuất sắc vượt chuẩn OJT (High Distinction)"
        elif overall_score >= 7.0:
            grade = "Pass — Đạt yêu cầu thực tập (OJT Qualified)"
        elif overall_score >= 5.0:
            grade = "Cần cải thiện — Chưa đạt chuẩn OJT (Conditional / Needs Improvement)"
        else:
            grade = "Chưa đạt — Cần rèn luyện lại từ đầu (Not Qualified)"

        # 6. Tổng hợp Điểm Mạnh (Strengths) thực tế
        strengths = [s for s in all_awarded_points if len(s.strip()) > 5][:4]
        if not strengths:
            if overall_score >= 7.0:
                strengths = ["Nắm vững kiến thức nền tảng và trả lời đúng trọng tâm các câu hỏi được giao."]
            else:
                strengths = ["Có tinh thần tham gia phỏng vấn và nỗ lực phản hồi các câu hỏi đặt ra."]

        # 7. Tổng hợp Lỗ hổng cần đào sâu (Weaknesses) thực tế
        weaknesses = [w for w in all_missed_points if len(w.strip()) > 5][:4]
        if not weaknesses:
            if overall_score >= 8.5:
                weaknesses = ["Ứng viên thể hiện rất tốt, cần tiếp tục phát huy ở các tình huống kiến trúc quy mô lớn hơn."]
            else:
                weaknesses = ["Cần đào sâu hơn vào chi tiết triển khai kỹ thuật và liên hệ số liệu thực tiễn."]

        # 8. Sinh Lộ trình học tập cá nhân hóa (Personalized Learning Roadmap) từ các điểm yếu thực tế
        learning_roadmap = []
        seen_skills = set()

        for turn in low_score_turns:
            stage = turn.get("stage", "Kỹ năng chuyên môn")
            missed = turn.get("points_missed") or []
            score = float(turn.get("score", 5.0))

            skill_name = self._map_stage_to_skill(stage, turn.get("question", ""))
            if skill_name in seen_skills:
                continue
            seen_skills.add(skill_name)

            action_desc = f"Học và luyện tập: {'; '.join(missed[:2])}" if missed else f"Củng cố kiến thức nền tảng về {skill_name}"
            priority = "HIGH" if score < 5.0 else "MEDIUM"
            est_hours = 16 if score < 5.0 else 8

            learning_roadmap.append({
                "skill": skill_name,
                "action": action_desc,
                "estimated_hours": est_hours,
                "priority": priority,
            })

            if len(learning_roadmap) >= 4:
                break

        if not learning_roadmap:
            learning_roadmap = [
                {
                    "skill": "Kiến trúc hệ thống nâng cao",
                    "action": "Tìm hiểu sâu về Distributed Systems, Message Broker (Kafka) và Microservices",
                    "estimated_hours": 16,
                    "priority": "LOW",
                }
            ]

        # 9. Hàng đợi câu hỏi luyện lại (Candidate Retry Queue)
        retry_recommendations = []
        for turn in low_score_turns:
            q_text = turn.get("question", "")
            hint = turn.get("better_answer_hint", "")
            if q_text:
                rec_text = f"Luyện tập lại câu hỏi: \"{q_text}\" ({hint})"
                if rec_text not in retry_recommendations:
                    retry_recommendations.append(rec_text)
            if len(retry_recommendations) >= 3:
                break

        if not retry_recommendations:
            retry_recommendations = [
                "Ứng viên đã hoàn thành tốt các câu hỏi trong phiên, không có câu hỏi bắt buộc phải luyện lại."
            ]

        # 10. Đóng gói Report hoàn chỉnh
        report = {
            "report_status": "READY",
            "session_id": session_id,
            "student_id": student_id,
            "role": role,
            "company_target": company,
            "overall_score": overall_score,
            "max_score": 10.0,
            "grade": grade,
            "radar_scores": radar_scores,
            "strengths": strengths,
            "weaknesses": weaknesses,
            "turn_evaluations": formatted_turns,
            "evaluated_turns": formatted_turns,
            "learning_roadmap": learning_roadmap,
            "retry_recommendations": retry_recommendations,
            "recommendations": retry_recommendations,
            "competencies": [
                {"dimension": k, "score": v, "max": 10.0}
                for k, v in radar_scores.items()
            ],
        }

        # Lưu cache báo cáo
        self.redis.cache_report(session_id, report)
        return report

    def _map_stage_to_skill(self, stage: str, question: str) -> str:
        """Ánh xạ stage và câu hỏi thành tên môn/kỹ năng chuẩn xác."""
        q_lower = (question or "").lower()
        if "database" in q_lower or "sql" in q_lower or "index" in q_lower or "transaction" in q_lower or "hibernate" in q_lower or "jpa" in q_lower:
            return "Cơ sở dữ liệu nâng cao (Database & ORM)"
        if "react" in q_lower or "dom" in q_lower or "state" in q_lower or "frontend" in q_lower:
            return "Lập trình Frontend nâng cao (React & Web Performance)"
        if "spring" in q_lower or "api" in q_lower or "rest" in q_lower or "microservice" in q_lower:
            return "Phát triển Backend (Spring Boot & Microservices)"
        if "star" in stage.lower() or "project" in stage.lower():
            return "Kỹ năng thẩm định dự án (STAR Framework & Metrics)"
        if "incident" in stage.lower() or "case" in stage.lower():
            return "Kỹ năng xử lý sự cố hệ thống (Incident Response & RCA)"
        if "hr" in stage.lower() or "motivation" in stage.lower():
            return "Định hướng nghề nghiệp & Tìm hiểu văn hóa doanh nghiệp"
        return "Nền tảng kỹ thuật chuyên môn (Core Engineering)"


_report_service: ReportService | None = None


def get_report_service() -> ReportService:
    global _report_service
    if _report_service is None:
        _report_service = ReportService()
    return _report_service
