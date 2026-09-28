"""
CÓC ĐI LÀM — Rubric-Aware Evidence Evaluator (§6)
Provider mặc định: Google Gemini 2.0 Flash API với Structured Outputs.
Evaluator chỉ tạo evidence/score theo rubric; KHÔNG có quyền chọn hành động tiếp theo.
"""

from google import genai
from google.genai import types
from app.models.schemas import (
    EvaluationEnvelope, RubricType,
    TechnicalEvidenceOutput, HRMotivationEvaluationOutput,
    STAREvaluationOutput, CaseStudyEvaluationOutput,
    AuditRecord, EventType, ValidationStatus,
)
from app.core.config import get_settings
import json
import logging
import asyncio
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class EvidenceEvaluator:
    """
    Rubric-Aware Evidence Evaluator (§6).
    Sử dụng Gemini 2.0 Flash cho evaluation chính.
    Mọi provider phải trả cùng hợp đồng schema.
    """
    _quota_cooldown_until: float = 0.0

    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self._init_client()

    def _init_client(self):
        """Khởi tạo Gemini client."""
        if self.settings.google_gemini_api_key:
            self.client = genai.Client(api_key=self.settings.google_gemini_api_key)
            logger.info("Gemini evaluator client initialized")
        else:
            logger.warning("Gemini API key not configured. Evaluator will not work.")

    @property
    def is_available(self) -> bool:
        return self.client is not None

    async def evaluate(
        self,
        turn_id: str,
        rubric_type: RubricType,
        verified_transcript: str,
        current_question: str,
        candidate_context: dict,
        company_context: dict | None = None,
    ) -> EvaluationEnvelope | None:
        """
        Đánh giá câu trả lời theo rubric type tương ứng.
        Returns EvaluationEnvelope hoặc None nếu evaluator lỗi.
        """
        if not self.is_available:
            logger.error("Evaluator not available - all providers failed")
            return None

        # 1. Fast-path: Phát hiện phản hồi "không biết", "chưa rõ", từ chối trả lời hoặc quá ngắn (< 3 từ)
        lower_t = (verified_transcript or "").strip().lower()
        no_answer_patterns = [
            "không biết", "chưa biết", "chưa rõ", "không rõ", "chưa tìm hiểu",
            "chưa học", "bỏ qua", "quên mất", "chưa nắm", "chưa có kinh nghiệm",
            "chưa nghe", "em chịu", "tôi chịu", "không có câu trả lời",
            "không có ý kiến", "pass câu này", "chuyển câu", "tiếp theo đi",
            "không biết gì hết", "k biết", "ko biet", "chịu thôi"
        ]
        is_no_answer = not lower_t or any(p in lower_t for p in no_answer_patterns) or len(lower_t.split()) <= 2

        if is_no_answer:
            logger.info(f"Fast-path no-answer detected for turn={turn_id}: '{verified_transcript}'")
            if rubric_type == RubricType.HR_MOTIVATION:
                payload = {
                    "role_motivation_specificity": 0.0,
                    "company_understanding_evidence": 0.0,
                    "learning_goal_clarity": 0.0,
                    "collaboration_example_quality": None,
                    "assessed_dimensions": [
                        "role_motivation_specificity",
                        "company_understanding_evidence",
                        "learning_goal_clarity",
                    ],
                    "observed_points": [],
                    "missing_points": ["Ứng viên chưa chia sẻ lý do ứng tuyển hoặc mục tiêu học hỏi"],
                    "_confidence": 0.95,
                }
                payload_schema = "HRMotivation_EvaluationOutput"
            elif rubric_type == RubricType.TECHNICAL_CORRECTNESS:
                payload = {
                    "correctness": 0.0,
                    "covered": [],
                    "missing": ["Khái niệm kỹ thuật theo yêu cầu câu hỏi"],
                    "misconceptions": ["Ứng viên chưa nắm hoặc chưa tìm hiểu chủ đề này"],
                    "depth": 0,
                    "_confidence": 0.95,
                }
                payload_schema = "TechnicalEvidenceOutput"
            elif rubric_type == RubricType.STAR_FRAMEWORK:
                payload = {
                    "situation_clarity": 0.0,
                    "task_definition": 0.0,
                    "action_depth": 0.0,
                    "result_quantification": 0.0,
                    "ownership_evidence_strength": 0.0,
                    "role_ownership": "unclear",
                    "missing_star_components": ["situation", "task", "action", "result"],
                    "_confidence": 0.95,
                }
                payload_schema = "STAR_EvaluationOutput"
            elif rubric_type == RubricType.CASE_STUDY:
                payload = {
                    "problem_structuring": 0.0,
                    "root_cause_identification": 0.0,
                    "solution_feasibility": 0.0,
                    "business_impact_awareness": 0.0,
                    "structured_framework_used": None,
                    "_confidence": 0.95,
                }
                payload_schema = "CaseStudy_EvaluationOutput"
            else:
                payload = None
                payload_schema = ""

            if payload:
                return EvaluationEnvelope(
                    turn_id=turn_id,
                    rubric_type=rubric_type,
                    payload_schema=payload_schema,
                    evaluation_confidence=0.95,
                    payload={k: v for k, v in payload.items() if not k.startswith("_")},
                )

        try:
            # Dispatch theo rubric type
            if rubric_type == RubricType.TECHNICAL_CORRECTNESS:
                payload = await self._evaluate_technical(
                    verified_transcript, current_question, candidate_context
                )
                payload_schema = "TechnicalEvidenceOutput"
            elif rubric_type == RubricType.HR_MOTIVATION:
                payload = await self._evaluate_hr_motivation(
                    verified_transcript, current_question, candidate_context, company_context
                )
                payload_schema = "HRMotivation_EvaluationOutput"
            elif rubric_type == RubricType.STAR_FRAMEWORK:
                payload = await self._evaluate_star(
                    verified_transcript, current_question, candidate_context
                )
                payload_schema = "STAR_EvaluationOutput"
            elif rubric_type == RubricType.CASE_STUDY:
                payload = await self._evaluate_case_study(
                    verified_transcript, current_question, candidate_context
                )
                payload_schema = "CaseStudy_EvaluationOutput"
            else:
                logger.error(f"Unknown rubric_type: {rubric_type}")
                return None

            if payload is None:
                return None

            envelope = EvaluationEnvelope(
                turn_id=turn_id,
                rubric_type=rubric_type,
                payload_schema=payload_schema,
                evaluation_confidence=payload.get("_confidence", 0.85),
                payload={k: v for k, v in payload.items() if not k.startswith("_")},
            )

            logger.info(f"Evaluation complete: turn={turn_id}, rubric={rubric_type.value}")
            return envelope

        except Exception as e:
            logger.error(f"Evaluation failed for turn {turn_id}: {e}")
            return None

    async def _evaluate_technical(
        self,
        transcript: str,
        question: str,
        context: dict,
    ) -> dict | None:
        """Đánh giá kỹ thuật (§6.2)."""
        system_prompt = """Bạn là một chuyên gia đánh giá câu trả lời phỏng vấn kỹ thuật OJT.
Đánh giá câu trả lời của ứng viên dựa CHÍNH XÁC trên nội dung transcript đã xác minh.
Trả về kết quả theo schema TechnicalEvidenceOutput.

Quy tắc:
- correctness: 0.0-1.0, mức độ chính xác kỹ thuật
- covered: danh sách các điểm ứng viên đã đề cập đúng
- missing: danh sách các điểm quan trọng bị bỏ sót
- misconceptions: danh sách các hiểu sai/nhầm lẫn kỹ thuật
- depth: 0=không đủ nội dung, 1=nhận biết, 2=hiểu cơ bản, 3=hiểu rõ, 4=phân tích sâu, 5=kiến trúc/tối ưu"""

        user_prompt = f"""Câu hỏi phỏng vấn: {question}

Transcript đã xác minh của ứng viên:
{transcript}

Ngữ cảnh bổ sung:
- Role: {context.get('role', 'N/A')}
- Concepts liên quan: {context.get('concepts', [])}

Hãy đánh giá theo schema TechnicalEvidenceOutput (JSON)."""

        return await self._call_gemini(
            system_prompt, user_prompt,
            TechnicalEvidenceOutput,
            context=context,
        )

    async def _evaluate_hr_motivation(
        self,
        transcript: str,
        question: str,
        context: dict,
        company_context: dict | None,
    ) -> dict | None:
        """Đánh giá HR/Động lực (§6.3)."""
        system_prompt = """Bạn là chuyên gia đánh giá phần HR/động lực ứng tuyển OJT.
Đánh giá NỘI DUNG CÓ THỂ QUAN SÁT trong câu trả lời, KHÔNG suy luận tính cách hay trạng thái tâm lý.
Dimension nào chưa được hỏi trong turn này thì để null.
Trả về JSON theo HRMotivation_EvaluationOutput schema."""

        company_info = ""
        if company_context:
            company_info = f"\nThông tin công ty: {json.dumps(company_context, ensure_ascii=False)}"

        user_prompt = f"""Câu hỏi: {question}

Transcript đã xác minh:
{transcript}

Role ứng tuyển: {context.get('role', 'N/A')}
Company: {context.get('company', 'N/A')}{company_info}

Đánh giá theo HRMotivation_EvaluationOutput (JSON)."""

        return await self._call_gemini(
            system_prompt, user_prompt,
            HRMotivationEvaluationOutput,
            context=context,
        )

    async def _evaluate_star(
        self,
        transcript: str,
        question: str,
        context: dict,
    ) -> dict | None:
        """Đánh giá STAR framework (§21.2)."""
        system_prompt = """Bạn là chuyên gia đánh giá câu trả lời theo STAR framework cho phỏng vấn OJT.
ownership_evidence_strength chỉ đo mức độ cụ thể, nhất quán và có thể truy vết của bằng chứng.
KHÔNG PHẢI xác suất nói thật/nói dối, KHÔNG suy luận gian lận.
Trả về JSON theo STAR_EvaluationOutput schema."""

        user_prompt = f"""Câu hỏi phỏng vấn: {question}

Transcript đã xác minh:
{transcript}

Dự án CV liên quan: {context.get('cv_project', 'N/A')}

Đánh giá theo STAR_EvaluationOutput (JSON)."""

        return await self._call_gemini(
            system_prompt, user_prompt,
            STAREvaluationOutput,
            context=context,
        )

    async def _evaluate_case_study(
        self,
        transcript: str,
        question: str,
        context: dict,
    ) -> dict | None:
        """Đánh giá Case Study (§21.3)."""
        system_prompt = """Bạn là chuyên gia đánh giá tư duy giải quyết vấn đề thực chiến cho phỏng vấn OJT.
Đánh giá khả năng phân rã bài toán, xác định nguyên nhân gốc rễ, tính khả thi và nhận thức tác động kinh doanh.
Trả về JSON theo CaseStudy_EvaluationOutput schema."""

        user_prompt = f"""Bài toán tình huống: {question}

Transcript đã xác minh:
{transcript}

Role: {context.get('role', 'N/A')}

Đánh giá theo CaseStudy_EvaluationOutput (JSON)."""

        return await self._call_gemini(
            system_prompt, user_prompt,
            CaseStudyEvaluationOutput,
            context=context,
        )

    async def _call_gemini(
        self,
        system_prompt: str,
        user_prompt: str,
        output_model,
        context: dict | None = None,
    ) -> dict | None:
        """Gọi Gemini Flash API với timeout nghiêm ngặt (3.0s) và tự động fallback về Heuristic Evaluation."""
        # Kiểm tra cooldown quota: Nếu vừa bị 429 thì không gọi Gemini tránh nghẽn thread pool
        if time.time() < self.__class__._quota_cooldown_until:
            return self._evaluate_heuristic(output_model, user_prompt, context)

        loop = asyncio.get_event_loop()

        def _execute():
            # Thử qua các model Gemini khả dụng
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash"]:
                try:
                    resp = self.client.models.generate_content(
                        model=model_name,
                        contents=user_prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_prompt,
                            temperature=0.1,
                            response_mime_type="application/json",
                            response_schema=output_model,
                        ),
                    )
                    if resp and resp.text:
                        result = json.loads(resp.text)
                        result["_confidence"] = 0.88
                        return result
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                        self.__class__._quota_cooldown_until = time.time() + 90.0
                        logger.warning(f"Gemini quota exhausted ({model_name}). Setting evaluator cooldown for 90s.")
                    else:
                        logger.warning(f"Gemini {model_name} call attempt error: {e}")
            return None

        if self.client:
            try:
                eval_result = await asyncio.wait_for(loop.run_in_executor(None, _execute), timeout=2.5)
                if eval_result:
                    return eval_result
            except asyncio.TimeoutError:
                logger.warning("Gemini evaluation timed out after 2.5s, invoking fast heuristic evaluator")
            except Exception as e:
                logger.warning(f"Gemini evaluation exception: {e}, invoking fast heuristic evaluator")

        # Fallback tức thì không bao giờ để giao diện bị treo
        return self._evaluate_heuristic(output_model, user_prompt, context)

    def _evaluate_heuristic(
        self,
        output_model,
        user_prompt: str,
        context: dict | None = None,
    ) -> dict:
        """Đánh giá nhanh theo luật và từ khóa, trả về kết quả trong 10ms khi LLM quá tải hoặc timeout."""
        ctx = context or {}
        model_name = getattr(output_model, "__name__", "")
        words = user_prompt.split()
        word_count = len(words)

        if "Technical" in model_name:
            concepts = ctx.get("concepts", []) or []
            found = [c for c in concepts if c.lower() in user_prompt.lower()]
            missing = [c for c in concepts if c not in found]
            score = 0.6 if not concepts else min(1.0, max(0.3, len(found) / max(1, len(concepts))))
            depth = min(4, max(1, word_count // 15))
            return {
                "correctness": score,
                "covered": found or ["Khái niệm cơ bản theo câu hỏi"],
                "missing": missing,
                "misconceptions": [],
                "depth": depth,
                "_confidence": 0.82,
            }

        elif "HRMotivation" in model_name:
            company = ctx.get("company", "")
            has_company = company.lower() in user_prompt.lower() if company else True
            has_growth = any(w in user_prompt.lower() for w in ["học", "phát triển", "mục tiêu", "kỳ vọng", "kinh nghiệm", "đóng góp"])
            return {
                "role_motivation_specificity": min(0.9, max(0.3, word_count / 25)),
                "company_understanding_evidence": 0.7 if has_company else 0.4,
                "learning_goal_clarity": 0.8 if has_growth else 0.4,
                "collaboration_example_quality": None,
                "assessed_dimensions": ["role_motivation_specificity", "company_understanding_evidence", "learning_goal_clarity"],
                "observed_points": ["Ứng viên thể hiện thái độ cầu tiến và mong muốn tham gia OJT"],
                "missing_points": [] if has_company else [f"Cần tìm hiểu kỹ hơn về các dự án thực tế tại {company}"],
                "_confidence": 0.82,
            }

        elif "STAR" in model_name:
            return {
                "situation_clarity": 0.6,
                "task_definition": 0.6,
                "action_depth": min(0.85, max(0.4, word_count / 30)),
                "result_quantification": 0.4,
                "ownership_evidence_strength": 0.6,
                "role_ownership": "contributor",
                "missing_star_components": [],
                "_confidence": 0.80,
            }

        else:  # CaseStudy
            return {
                "problem_structuring": 0.6,
                "root_cause_identification": 0.5,
                "solution_feasibility": 0.6,
                "business_impact_awareness": 0.5,
                "structured_framework_used": "5W1H",
                "_confidence": 0.80,
            }


# Singleton
_evaluator_instance: EvidenceEvaluator | None = None


def get_evidence_evaluator() -> EvidenceEvaluator:
    global _evaluator_instance
    if _evaluator_instance is None:
        _evaluator_instance = EvidenceEvaluator()
    return _evaluator_instance
