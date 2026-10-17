"""Framework-guided interview questions: generate for this CV/JD, never recite the bank."""

import asyncio
import json
import logging
import time
import uuid

from google import genai
from google.genai import types

from app.shared.config import get_settings
from app.shared.infrastructure.database import SupabaseService
from app.shared.contracts import (
    InterviewBlueprint, InterviewState, NextAction, Question, QuestionProvenance, RubricType, SourceType,
)
from app.domains.interview.catalog import get_interview_catalog
from app.domains.interview.services.guidance import QuestionGenerationUnavailable, copies_reference, framework_guidance

logger = logging.getLogger(__name__)


class QuestionService:
    _quota_cooldown_until = 0.0

    def __init__(self, db: SupabaseService | None = None):
        self.settings = get_settings()
        self.db = db  # Compatibility only; a DB question is not a spoken fallback.
        self.gemini_client = None
        self._init_gemini()

    def _init_gemini(self):
        if self.settings.google_gemini_api_key:
            try:
                self.gemini_client = genai.Client(
                    api_key=self.settings.google_gemini_api_key,
                    http_options=types.HttpOptions(
                        timeout=round(self.settings.interview_question_timeout_sec * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
            except Exception as exc:
                logger.warning("Could not initialize question generation: %s", exc)

    @staticmethod
    def _reference_texts(blueprint: InterviewBlueprint, role: str) -> list[str]:
        return [str(item.get("question", "")) for item in get_interview_catalog().framework_question_bank(
            framework_id=blueprint.framework_id, role=role,
        )]

    async def get_opening_question(self, state: InterviewState, blueprint: InterviewBlueprint) -> Question:
        references = self._reference_texts(blueprint, state.role)
        cached = state.current_question
        if cached and (cached.get("provenance") or {}).get("source_type") == SourceType.AI_GENERATED.value:
            restored = Question(**cached)
            if not copies_reference(restored.question_text, references):
                return restored
        if not blueprint.stages:
            raise QuestionGenerationUnavailable()
        index = next((i for i, stage in enumerate(blueprint.stages) if stage.stage_name == state.current_topic), 0)
        question = await self._generate_with_flash(state, blueprint, None, index, next_action="opening")
        if not question or copies_reference(question.question_text, references + state.asked_question_texts):
            raise QuestionGenerationUnavailable()
        state.current_topic = blueprint.stages[index].stage_name
        self._register_question(state, question)
        return question

    async def generate_interruption_dialogue(
        self,
        action: str,
        state: InterviewState,
        blueprint: InterviewBlueprint,
        unclear_phrase: str = "",
    ) -> str | None:
        """Generate one short, contextual clarification; never substitute a canned line."""
        if not self.gemini_client or time.time() < self.__class__._quota_cooldown_until:
            return None

        intent = {
            "ASK_REPEAT": "The transcript itself is unclear. Ask the candidate to repeat only the unclear phrase, and do not imply an answer.",
            "CLARIFY_NOW": "The transcript is audible but has more than one plausible meaning. Ask one concise, neutral question to disambiguate it.",
            "AI_SOFT_INTERRUPT": "The candidate has been speaking at length without a clear answer. Politely redirect to one specific aspect of the original question.",
        }.get(action)
        if not intent:
            return None

        context = {
            "role": state.role,
            "original_question": (state.current_question or {}).get("question_text", ""),
            "candidate_answer_so_far": state.candidate_answer_draft[-600:],
            "unclear_phrase": unclear_phrase,
            "instruction": intent,
        }
        prompt = """Bạn là người phỏng vấn tiếng Việt. Ứng viên vừa nói một ý chưa nghe rõ.
Hãy hỏi lại đúng ý đó bằng MỘT câu ngắn, tự nhiên (tối đa 30 từ); không chấm điểm, không trả lời hộ, không đổi chủ đề.
Nếu `unclear_phrase` có giá trị, chỉ hỏi lại đúng cụm đó; giữ nguyên phần trả lời đã nghe rõ.
Trả JSON duy nhất: {\"utterance\":\"câu hỏi ngắn?\"}.
Ngữ cảnh:\n""" + json.dumps(context, ensure_ascii=False, default=str)

        def call_model() -> str | None:
            try:
                response = self.gemini_client.models.generate_content(
                    model=self.settings.gemini_flash_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        response_mime_type="application/json",
                        max_output_tokens=220,
                    ),
                )
                data = json.loads(response.text or "{}")
                utterance = data.get("utterance") if isinstance(data, dict) else None
                if not isinstance(utterance, str):
                    logger.warning("Clarification generation returned no utterance string")
                    return None
                utterance = utterance.strip()
                if utterance and not utterance.endswith(("?", "？")):
                    utterance = utterance.rstrip(".!") + "?"
                if not utterance or len(utterance) > 500:
                    logger.warning("Clarification generation returned invalid spoken question (chars=%s)", len(utterance))
                    return None
                return utterance
            except Exception as exc:
                error = str(exc).casefold()
                if "429" in error or "quota" in error or "resource_exhausted" in error:
                    self.__class__._quota_cooldown_until = time.time() + 90
                logger.warning("Clarification generation failed: %s", exc)
                return None

        try:
            return await asyncio.wait_for(asyncio.to_thread(call_model), timeout=self.settings.interview_clarification_timeout_sec)
        except Exception as exc:
            logger.warning("Clarification generation unavailable: %s", exc)
            return None

    async def get_next_question(
        self, next_action: NextAction, state: InterviewState, blueprint: InterviewBlueprint,
        evaluation: dict | None = None, stage_idx: int = 0,
        last_question: str = "", candidate_answer: str = "",
    ) -> Question | None:
        if next_action == NextAction.FINISH_INTERVIEW:
            return None
        if not blueprint or not blueprint.stages:
            raise QuestionGenerationUnavailable()
        if next_action == NextAction.WRAP_UP or state.remaining_scored_question_budget <= 0:
            return await self._get_wrap_up_question(state, blueprint)

        index = next((i for i, stage in enumerate(blueprint.stages) if stage.stage_name == state.current_topic), stage_idx)
        index = min(max(index, 0), len(blueprint.stages) - 1)
        stage = blueprint.stages[index]
        advance = next_action in (NextAction.SWITCH_TOPIC, NextAction.FINISH_TOPIC) or state.questions_on_current_concept >= stage.question_budget
        if advance and index == len(blueprint.stages) - 1:
            # Stay within the last scored stage until the question budget is
            # exhausted; a wrap-up must not appear halfway through the session.
            advance = False
        if advance:
            index += 1
            stage = blueprint.stages[index]

        # Do not commit stage progression when the provider fails/refuses to generate.
        generation_state = state.model_copy(deep=True)
        generation_state.current_topic = stage.stage_name
        if advance:
            generation_state.current_concept = (stage.concepts or [None])[0]
            generation_state.questions_on_current_concept = 0
        question = await self._generate_with_flash(
            generation_state, blueprint, evaluation, index,
            next_action=next_action.value, last_question=last_question, candidate_answer=candidate_answer,
        )
        references = self._reference_texts(blueprint, state.role)
        if not question or copies_reference(question.question_text, references + state.asked_question_texts):
            raise QuestionGenerationUnavailable()
        state.current_topic = stage.stage_name
        if advance:
            state.questions_on_current_concept = 0
        self._register_question(state, question)
        return question

    def _register_question(self, state: InterviewState, question: Question):
        state.asked_question_texts.append(question.question_text)
        state.questions_on_current_concept += 1
        if question.concepts:
            state.current_concept = question.concepts[0]
        question.stage_name = question.stage_name or state.current_topic
        question.target_rubric = question.target_rubric or question.rubric_type.value
        question.expected_concepts = question.expected_concepts or question.concepts
        state.current_question = question.model_dump(mode="json")

    async def _generate_with_flash(
        self, state: InterviewState, blueprint: InterviewBlueprint, evaluation: dict | None, stage_idx: int,
        *, next_action: str = "same_level", last_question: str = "", candidate_answer: str = "",
    ) -> Question | None:
        if not self.gemini_client or time.time() < self.__class__._quota_cooldown_until:
            return None
        stage = blueprint.stages[stage_idx]
        guidance = framework_guidance(blueprint.framework_context)
        is_opening = next_action == "opening"
        candidate_display_name = state.candidate_name
        if (
            not candidate_display_name
            or candidate_display_name.upper().startswith("DEMO_")
            or candidate_display_name.upper().startswith("STUDENT_")
            or candidate_display_name.upper().startswith("SV_")
        ):
            candidate_display_name = ""

        context = {
            "framework": guidance,
            "cv_evidence": blueprint.candidate_context,
            "job_requirements": blueprint.job_context,
            "stage": stage.model_dump(exclude={"seed_question"}),
            "candidate_name": candidate_display_name,
            "role": state.role, "company": state.company_target,
            "difficulty": state.current_difficulty, "action": next_action,
            "previous_question": last_question,
            "candidate_answer": candidate_answer,
            "evaluation": evaluation,
            "already_asked": state.asked_question_texts,
        }

        if is_opening:
            greeting_name = f"bạn {candidate_display_name}" if candidate_display_name else "bạn"
            prompt = f"""Bạn là một Technical Interviewer / Tech Lead giàu kinh nghiệm tại Việt Nam (mang phong thái chuyên nghiệp, ấm áp, cởi mở, đúng chuẩn các buổi Mock Interview IT trên YouTube và thực tế).
Đây là LƯỢT MỞ ĐẦU (Opening) của buổi phỏng vấn.
Mục tiêu chính: Chào đón ứng viên, giới thiệu bản thân người phỏng vấn và mời ứng viên tự giới thiệu bản thân về mặt kỹ thuật (Technical Self-Introduction).
TUYỆT ĐỐI KHÔNG nhảy vào hỏi lý thuyết hàn lâm hay đố bài tập kỹ thuật hóc búa ngay lúc này.

Hãy viết lời thoại mở đầu tự nhiên, lịch thiệp, liền mạch (khoảng 3-4 câu):
1. Lời chào & Giới thiệu bản thân: Chào ứng viên ("Chào {greeting_name}!"). Giới thiệu mình là người phỏng vấn kỹ thuật đại diện cho {state.company_target or 'công ty'} trong buổi phỏng vấn vị trí {state.role} hôm nay.
2. Tạo không khí thoải mái & Nêu mục tiêu: Bày tỏ sự vui mừng được đồng hành cùng ứng viên. Nhấn mạnh đây là một buổi trao đổi kỹ thuật cởi mở, hai chiều để hai bên cùng tìm hiểu về kỹ năng, kinh nghiệm cũng như định hướng công việc.
3. Mời ứng viên tự giới thiệu bản thân: Mời ứng viên chia sẻ đôi nét về bản thân, quá trình học tập, các mảng công nghệ/kỹ năng thế mạnh mà ứng viên tự tin nhất và 1-2 dự án tiêu biểu gần đây.

Xưng hô: "mình" - "bạn" (lịch sự, thân thiện, văn phong nói tự nhiên, phát âm rõ ràng cho TTS, không dùng ký hiệu hay gạch đầu dòng).
Trả JSON duy nhất dạng: {{"question_text": "lời thoại mở đầu hoàn chỉnh của interviewer", "expected_concepts": ["self_introduction", "communication", "background_overview"]}}
Ngữ cảnh phiên:\n""" + json.dumps(context, ensure_ascii=False, default=str)
        else:
            prompt = f"""Bạn là một Technical Interviewer / Tech Lead giàu kinh nghiệm tại Việt Nam (mang phong thái chuyên nghiệp, thân thiện, tôn trọng, giao tiếp hai chiều tự nhiên như các buổi phỏng vấn kỹ thuật thực tế trên YouTube).
Khung năng lực (Framework), giai đoạn hiện tại ({stage.stage_name}) và tiêu chí đánh giá ({stage.rubric_type.value}) là kim chỉ nam để định hướng buổi phỏng vấn. Bạn phải giữ nguyên vẹn khung đánh giá nhưng diễn đạt lời thoại hoàn toàn tự nhiên như văn nói.

Quy tắc cấu trúc lời thoại của Interviewer (khoảng 2 - 4 câu súc tích):
1. Phản hồi kết nối (Conversational Bridge - 1 đến 2 câu):
   - Nếu lượt trước là câu mở đầu và ứng viên vừa giới thiệu bản thân: Hãy nồng nhiệt ghi nhận phần giới thiệu của ứng viên. Nhắc lại cụ thể công nghệ hoặc dự án tiêu biểu mà ứng viên THỰC SỰ vừa nói trong `candidate_answer` (ví dụ: "Cảm ơn phần giới thiệu rất rõ ràng của bạn. Mình thấy bạn đã có trải nghiệm thực chiến với Spring Boot và dự án E-commerce..."). Sau đó chuyển tiếp mượt mà vào giai đoạn chuyên môn đầu tiên.
   - Nếu lượt trước là câu hỏi chuyên môn/tình huống:
     + Nếu ứng viên trả lời tốt/đúng: Ghi nhận điểm sáng hoặc giải pháp hợp lý của ứng viên một cách tự nhiên (ví dụ: "Cách tiếp cận xử lý cache với Redis của bạn rất hợp lý...", "Đúng vậy, việc tối ưu query và index là điểm mấu chốt ở đây...").
     + Nếu ứng viên trả lời còn thiếu sót hoặc chưa chuẩn xác: Thừa nhận ý tưởng và nhẹ nhàng phản hồi hoặc gợi mở thách thức theo `action` (ví dụ: "Mình hiểu hướng tiếp cận của bạn. Tuy nhiên trong môi trường phân tán khi tải tăng đột biến thì...", "Ý tưởng của bạn khá thú vị, nhưng hãy thử cân nhắc xem...").
     + Nếu ứng viên trả lời chưa biết hoặc xin bỏ qua/gặp khó: Tạo sự an tâm, không gây áp lực (ví dụ: "Không sao cả, phần này đòi hỏi kinh nghiệm thực chiến chuyên sâu. Chúng ta sẽ cùng chuyển sang một chủ đề khác...").
   - NGUYÊN TẮC: Chỉ phản ánh những gì ứng viên THỰC SỰ vừa nói trong `candidate_answer`. Tuyệt đối không bịa đặt hoặc khen sáo rỗng.

2. Đặt câu hỏi kế tiếp (Next Question):
   - Đặt MỘT câu hỏi mới, rõ ràng, trọng tâm, bám sát hành động điều phối `{next_action}`:
     + probe: Đào sâu vào chi tiết kỹ thuật cụ thể, cơ chế hoạt động bên dưới hoặc edge case của câu vừa trả lời.
     + same_level: Giữ nguyên độ khó hiện tại, hỏi một khía cạnh kỹ thuật/năng lực liên quan trong giai đoạn `{stage.stage_name}`.
     + harder: Nâng cao thử thách (kiến trúc hệ thống, tối ưu tải lớn, xử lý lỗi phân tán, concurrency).
     + easier: Đưa ra câu hỏi nền tảng cơ bản hơn hoặc gợi ý nhẹ nhàng giúp ứng viên lấy lại tự tin.
     + switch_topic / finish_topic: Giới thiệu nhẹ nhàng việc chuyển sang chủ đề mới trong giai đoạn và đặt câu hỏi mở đầu cho chủ đề đó.
     + clarify_answer / verify_reasoning: Đặt câu hỏi yêu cầu ứng viên giải thích rõ hơn lý do lựa chọn giải pháp.
   - Câu hỏi phải phù hợp với vị trí `{state.role}`, dựa trên kinh nghiệm thực trong CV/JD, câu từ tự nhiên cho giao tiếp nói, không đọc nguyên văn từ ngân hàng câu hỏi.

3. Phong thái & Giọng văn:
   - Xưng hô "mình" - "bạn" (chuẩn mực phỏng vấn IT hiện đại, lịch sự, tôn trọng).
   - Văn phong nói trôi chảy, súc tích, ngữ điệu tự nhiên cho bộ đọc TTS, không dùng gạch đầu dòng hay ký tự đặc biệt.

Trả JSON duy nhất: {{"question_text": "lời phản hồi kết nối + câu hỏi tiếp theo", "expected_concepts": ["năng lực cần kiểm chứng"]}}
Ngữ cảnh phiên:\n""" + json.dumps(context, ensure_ascii=False, default=str)

        references = self._reference_texts(blueprint, state.role) + state.asked_question_texts

        def call_model():
            try:
                response = self.gemini_client.models.generate_content(
                    model=self.settings.gemini_flash_model, contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.65, response_mime_type="application/json"),
                )
                result = json.loads(response.text)
                text = result.get("question_text")
                if not isinstance(text, str) or not text.strip() or len(text) > 2500:
                    return None
                text = text.strip()
                if copies_reference(text, references):
                    logger.warning("Rejected generated question overlapping source/history for %s", state.session_id)
                    return None
                concepts = result.get("expected_concepts", [])
                concepts = [item for item in concepts if isinstance(item, str) and item.strip()][:5] if isinstance(concepts, list) else []
                rubric = RubricType.HR_MOTIVATION if is_opening else stage.rubric_type
                target_rubric = RubricType.HR_MOTIVATION.value if is_opening else stage.rubric_type.value
                resolved_concepts = (
                    ["self_introduction", "communication", "background_overview"]
                    if is_opening
                    else (concepts or (stage.concepts or [])[:2])
                )
                return Question(
                    question_id=f"q_generated_{uuid.uuid4().hex[:8]}", question_text=text,
                    rubric_type=rubric, difficulty=1 if is_opening else state.current_difficulty,
                    stage_name=stage.stage_name, target_rubric=target_rubric,
                    concepts=resolved_concepts,
                    applicable_roles=[state.role],
                    provenance=QuestionProvenance(
                        source_type=SourceType.AI_GENERATED, generation_model=self.settings.gemini_flash_model,
                        source_refs=[blueprint.framework_id] if blueprint.framework_id else [],
                        generation_context_refs=[value for value in (state.session_id, blueprint.source_candidate_id, blueprint.source_job_id) if value],
                        verification_status="generated_not_source_copy",
                    ),
                )
            except Exception as exc:
                error = str(exc).casefold()
                if "429" in error or "quota" in error or "resource_exhausted" in error:
                    self.__class__._quota_cooldown_until = time.time() + 90
                logger.warning("Question model generation failed: %s", exc)
                return None
        try:
            return await asyncio.wait_for(asyncio.to_thread(call_model), timeout=self.settings.interview_question_timeout_sec)
        except Exception as exc:
            logger.warning("Question model unavailable: %s", exc)
            return None

    async def _get_wrap_up_question(self, state: InterviewState, blueprint: InterviewBlueprint | None = None) -> Question:
        from app.domains.interview.services.dialogue import get_interview_dialogue
        text = await get_interview_dialogue().format_wrap_up(
            role=state.role, company=state.company_target, candidate_name=state.candidate_name,
            framework_context=blueprint.framework_context if blueprint else {},
        )
        if not text:
            raise QuestionGenerationUnavailable()
        return Question(
            question_id=f"q_wrap_{uuid.uuid4().hex[:8]}", question_text=text,
            rubric_type=RubricType.HR_MOTIVATION, difficulty=1, stage_name="wrap_up",
            target_rubric="hr_motivation", expected_concepts=[], applicable_roles=[state.role],
            provenance=QuestionProvenance(source_type=SourceType.AI_GENERATED,
                generation_model=self.settings.gemini_flash_model, verification_status="auto_generated"),
        )


_service_instance: QuestionService | None = None


def get_question_service() -> QuestionService:
    global _service_instance
    if _service_instance is None:
        _service_instance = QuestionService()
    return _service_instance
