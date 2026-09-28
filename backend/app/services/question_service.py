"""
CÓC ĐI LÀM — Question Service (§11)
Lựa chọn câu hỏi & provenance tracking.
Thứ tự ưu tiên: Curated → Template → Gemini Flash → Gemini Pro.
"""

from google import genai
from google.genai import types
from app.models.schemas import (
    Question, QuestionProvenance, SourceType, RubricType,
    NextAction, InterviewBlueprint, InterviewState,
)
from app.core.config import get_settings
from app.core.database import SupabaseService
import json
import logging
import asyncio
import time
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)


class QuestionService:
    """
    Dịch vụ câu hỏi với provenance tracking (§11).
    Execution semantics theo next_action.
    """
    _quota_cooldown_until: float = 0.0


    def __init__(self, db: SupabaseService | None = None):
        self.settings = get_settings()
        self.db = db
        self.gemini_client = None
        self._init_gemini()

    def _init_gemini(self):
        if self.settings.google_gemini_api_key:
            self.gemini_client = genai.Client(api_key=self.settings.google_gemini_api_key)

    async def get_next_question(
        self,
        next_action: NextAction,
        state: InterviewState,
        blueprint: InterviewBlueprint,
        evaluation: dict | None = None,
        stage_idx: int = 0,
    ) -> Question | None:
        """
        Lấy câu hỏi tiếp theo dựa trên next_action, blueprint, và tiến trình phỏng vấn.
        Tự động chuyển stage theo tiến độ và ngăn ngừa lặp lại câu hỏi.
        §11.3: finish_interview → không gọi Question Service.
                wrap_up → closing template.
        """
        # finish_interview → KHÔNG gọi Question Service (§11.3)
        if next_action == NextAction.FINISH_INTERVIEW:
            logger.info("finish_interview → Question Service not called")
            return None

        # wrap_up → closing template
        if next_action == NextAction.WRAP_UP:
            return self._get_wrap_up_question(state)

        # 1. Xác định stage hiện tại từ state.current_topic
        stages = blueprint.stages if blueprint and blueprint.stages else []
        current_stage_idx = 0
        if stages:
            for idx, stg in enumerate(stages):
                if stg.stage_name == state.current_topic:
                    current_stage_idx = idx
                    break

        # 2. Logic chuyển stage thông minh (§23.2):
        # - Nếu next_action yêu cầu chuyển topic
        # - Hoặc stage 1 (hr_motivation) đã hỏi xong câu hỏi mở đầu
        # - Hoặc số câu hỏi ở stage hiện tại đã chạm budget của stage
        current_stage = stages[current_stage_idx] if current_stage_idx < len(stages) else None
        budget = current_stage.question_budget if current_stage else 1

        should_advance_stage = (
            next_action in [NextAction.SWITCH_TOPIC, NextAction.FINISH_TOPIC]
            or (current_stage and current_stage.stage_name == "hr_motivation" and state.questions_on_current_concept >= 1)
            or (state.questions_on_current_concept >= budget)
        )

        if should_advance_stage and current_stage_idx < len(stages) - 1:
            current_stage_idx += 1
            current_stage = stages[current_stage_idx]
            state.current_topic = current_stage.stage_name
            state.questions_on_current_concept = 0
            logger.info(f"Advanced to interview stage {current_stage_idx}: {state.current_topic}")

        # Nếu đã hoàn thành tất cả các stage
        if state.remaining_scored_question_budget <= 0 or current_stage_idx >= len(stages):
            return self._get_wrap_up_question(state)

        # 3. Chọn câu hỏi theo thứ tự ưu tiên (§11.1), đảm bảo KHÔNG trùng lặp
        question = None

        # Ưu tiên 1: Ngân hàng câu hỏi thu thập từ Model Orchestrator & Curated Bank
        question = await self._try_curated_bank(state, blueprint, current_stage_idx)
        if question and question.question_text not in state.asked_question_texts:
            self._register_question(state, question)
            return question

        # Ưu tiên 2: Sinh câu hỏi động bằng Gemini Flash dựa trên ngữ cảnh câu trả lời trước
        question = await self._generate_with_flash(state, blueprint, evaluation, current_stage_idx)
        if question and question.question_text not in state.asked_question_texts:
            self._register_question(state, question)
            return question

        # Ưu tiên 3: Seed question từ Blueprint stage
        if current_stage and current_stage.seed_question and current_stage.seed_question not in state.asked_question_texts:
            seed_q = Question(
                question_id=f"q_seed_{uuid.uuid4().hex[:8]}",
                question_text=current_stage.seed_question,
                rubric_type=current_stage.rubric_type,
                difficulty=state.current_difficulty,
                concepts=current_stage.concepts or [],
                applicable_roles=[blueprint.target_role],
                provenance=QuestionProvenance(
                    source_type=SourceType.CURATED,
                    verification_status="verified",
                ),
            )
            self._register_question(state, seed_q)
            return seed_q

        # Ưu tiên 4: Template slot-filling
        question = self._try_template(state, blueprint, current_stage_idx)
        if question and question.question_text not in state.asked_question_texts:
            self._register_question(state, question)
            return question

        # Fallback cuối cùng: Wrap-up closing
        return self._get_wrap_up_question(state)

    def _register_question(self, state: InterviewState, question: Question):
        """Ghi nhận câu hỏi đã được hỏi vào state để loại trừ lặp."""
        if question.question_text not in state.asked_question_texts:
            state.asked_question_texts.append(question.question_text)
        state.questions_on_current_concept += 1
        if question.concepts:
            state.current_concept = question.concepts[0]
        if not question.stage_name:
            question.stage_name = state.current_topic or "technical_core"
        if not question.target_rubric:
            question.target_rubric = question.rubric_type.value if hasattr(question.rubric_type, "value") else str(question.rubric_type)
        if not question.expected_concepts:
            question.expected_concepts = question.concepts

    async def _try_curated_bank(
        self,
        state: InterviewState,
        blueprint: InterviewBlueprint,
        stage_idx: int,
    ) -> Question | None:
        """Thử lấy từ Ngân hàng câu hỏi của Model Orchestrator hoặc Curated Database."""
        stage = blueprint.stages[stage_idx] if blueprint and stage_idx < len(blueprint.stages) else None
        target_stage_name = stage.stage_name if stage else "technical_core"
        target_rubric = stage.rubric_type.value if stage else "technical_correctness"

        # 1. Tra cứu trực tiếp từ Model Orchestrator Ingested Knowledge (do MCP Web Search thu thập)
        try:
            from app.services.orchestrator_service import get_orchestrator_service
            orchestrator = get_orchestrator_service()
            ingested_questions = orchestrator.get_ingested_questions(state.company_target, state.role)
            for q_data in ingested_questions:
                q_text = q_data.get("question") or q_data.get("question_text", "")
                q_stage = q_data.get("stage", "")
                q_rubric = q_data.get("rubric_type", "")
                if hasattr(q_rubric, "value"):
                    q_rubric = q_rubric.value

                if q_text and q_text not in state.asked_question_texts:
                    # Khớp stage hoặc rubric
                    if q_stage == target_stage_name or q_rubric == target_rubric or target_stage_name in ["technical_core", "applied_scenario"]:
                        return Question(
                            question_id=q_data.get("id") or f"q_orch_{uuid.uuid4().hex[:8]}",
                            question_text=q_text,
                            rubric_type=RubricType(q_rubric or target_rubric),
                            difficulty=q_data.get("difficulty", state.current_difficulty),
                            concepts=q_data.get("expected_concepts") or q_data.get("concepts", []),
                            applicable_roles=[state.role],
                            provenance=QuestionProvenance(
                                source_type=SourceType.CURATED,
                                source_url=q_data.get("url") or q_data.get("source", "Model Orchestrator MCP Discovery"),
                                verification_status="verified",
                            ),
                        )
        except Exception as e:
            logger.warning(f"Failed to query Orchestrator Ingested Bank: {e}")

        # 2. Tra cứu từ PostgreSQL/Supabase nếu có kết nối
        if self.db:
            try:
                questions = await self.db.get_questions_by_role(state.role, limit=10)
                if questions:
                    for q_data in questions:
                        if q_data["question_text"] not in state.asked_question_texts:
                            return Question(
                                question_id=q_data.get("question_id", f"q_{uuid.uuid4().hex[:8]}"),
                                question_text=q_data["question_text"],
                                rubric_type=RubricType(q_data.get("rubric_type", "technical_correctness")),
                                difficulty=q_data.get("difficulty", 2),
                                concepts=q_data.get("concepts", []),
                                applicable_roles=q_data.get("applicable_roles", []),
                                provenance=QuestionProvenance(
                                    source_type=SourceType.CURATED,
                                    verification_status="verified",
                                ),
                            )
            except Exception as e:
                logger.error(f"Curated bank query failed: {e}")

        return None

    def _try_template(
        self,
        state: InterviewState,
        blueprint: InterviewBlueprint,
        stage_idx: int,
    ) -> Question | None:
        """Template + slot-filling đảm bảo không lặp câu đã hỏi."""
        templates = {
            RubricType.HR_MOTIVATION: [
                "Em hãy chia sẻ ngắn gọn về lý do chọn ứng tuyển vị trí {role} tại {company} và kỳ vọng học hỏi được gì trong kỳ OJT?",
                "Điều gì ở môi trường công nghệ tại {company} khiến em muốn gắn bó và cống hiến thay vì các lựa chọn khác?",
            ],
            RubricType.STAR_FRAMEWORK: [
                "Hãy chia sẻ về một dự án phần mềm em từng thực hiện. Trình bày rõ thách thức, giải pháp kỹ thuật em tự thiết kế và bài học rút ra.",
                "Trong quá trình làm việc nhóm ở trường hoặc dự án cá nhân, em đã từng giải quyết bất đồng kỹ thuật với đồng đội như thế nào?",
            ],
            RubricType.TECHNICAL_CORRECTNESS: [
                "Em hãy giải thích {concept} hoạt động như thế nào trong nền tảng {role}?",
                "Khi phát triển ứng dụng với {role}, khi nào nên sử dụng {concept} và có nhược điểm gì cần lưu ý?",
                "Giải thích sự khác biệt giữa xử lý đồng bộ (synchronous) và bất đồng bộ (asynchronous) trong hệ thống backend?",
            ],
            RubricType.CASE_STUDY: [
                "Giả sử hệ thống {role} đang chạy production bất ngờ gặp tình huống {scenario}, em sẽ tiến hành các bước điều tra và khắc phục như thế nào?",
                "Nếu database bị nghẽn (connection pool exhausted) vào giờ cao điểm, giải pháp trước mắt và lâu dài của em là gì?",
            ],
        }

        if stage_idx < len(blueprint.stages):
            stage = blueprint.stages[stage_idx]
            rubric_templates = templates.get(stage.rubric_type, [])
            for tmpl in rubric_templates:
                text = tmpl.format(
                    role=state.role,
                    company=state.company_target,
                    concept=state.current_concept or "công nghệ cốt lõi",
                    context=state.role,
                    scenario="tải tăng đột biến và phản hồi chậm",
                )
                if text not in state.asked_question_texts:
                    return Question(
                        question_id=f"q_tmpl_{uuid.uuid4().hex[:8]}",
                        question_text=text,
                        rubric_type=stage.rubric_type,
                        difficulty=state.current_difficulty,
                        concepts=[state.current_concept] if state.current_concept else [],
                        applicable_roles=[state.role],
                        provenance=QuestionProvenance(
                            source_type=SourceType.TEMPLATE_GENERATED,
                            verification_status="auto_generated",
                        ),
                    )

        return None

    async def _generate_with_flash(
        self,
        state: InterviewState,
        blueprint: InterviewBlueprint,
        evaluation: dict | None,
        stage_idx: int,
    ) -> Question | None:
        """Sinh câu hỏi bằng Gemini 3.8 Flash qua Interactions API hoặc generate_content."""
        if not self.gemini_client:
            return None

        stage = blueprint.stages[stage_idx] if stage_idx < len(blueprint.stages) else None
        prompt = f"""Bạn là phỏng vấn viên kỹ thuật OJT giàu kinh nghiệm. Hãy sinh MỘT câu hỏi phỏng vấn bằng tiếng Việt cho ứng viên:
- Vị trí: {state.role}
- Công ty: {state.company_target}
- Giai đoạn: {stage.stage_name if stage else 'technical_core'}
- Chủ đề: {state.current_concept or 'kỹ thuật nền tảng'}
- Độ khó: {state.current_difficulty}/5
- Rubric đánh giá: {stage.rubric_type.value if stage else 'technical_correctness'}

{"Dựa trên đánh giá câu trả lời trước đó: " + json.dumps(evaluation, ensure_ascii=False) if evaluation else ""}

Yêu cầu: Câu hỏi rõ ràng, thực tế và mang tính phân loại cao.
Trả về định dạng JSON thuần duy nhất có dạng:
{{"question_text": "Nội dung câu hỏi phỏng vấn ở đây"}}"""

        # Nếu đang trong thời gian cooldown 429 thì bỏ qua ngay để dùng ngân hàng câu hỏi
        if time.time() < self.__class__._quota_cooldown_until:
            return None

        loop = asyncio.get_event_loop()

        def _call_model():
            # Sinh câu hỏi qua generate_content với timeout tức thì và không bị sleep retry
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash"]:
                try:
                    response = self.gemini_client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=0.7,
                            response_mime_type="application/json",
                        ),
                    )
                    if response and response.text:
                        result = json.loads(response.text)
                        q_text = result.get("question_text", "").strip()
                        if q_text:
                            return Question(
                                question_id=f"q_flash_{uuid.uuid4().hex[:8]}",
                                question_text=q_text,
                                rubric_type=stage.rubric_type if stage else RubricType.TECHNICAL_CORRECTNESS,
                                difficulty=state.current_difficulty,
                                concepts=[state.current_concept] if state.current_concept else [],
                                applicable_roles=[state.role],
                                provenance=QuestionProvenance(
                                    source_type=SourceType.AI_GENERATED,
                                    generation_model=model_name,
                                    generation_context_refs=[state.session_id],
                                    verification_status="auto_generated",
                                ),
                            )
                except Exception as e:
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                        self.__class__._quota_cooldown_until = time.time() + 90.0
                        logger.warning(f"Flash question generation 429 quota reached ({model_name}): cooldown set for 90s")
                        return None
                    logger.warning(f"Flash question generation failed with {model_name}: {e}")
            return None

        try:
            return await asyncio.wait_for(loop.run_in_executor(None, _call_model), timeout=2.5)
        except Exception:
            return None

    async def _generate_with_pro(
        self,
        state: InterviewState,
        blueprint: InterviewBlueprint,
        evaluation: dict | None,
        stage_idx: int,
    ) -> Question | None:
        """Sinh câu hỏi cá nhân hóa sâu bằng Gemini 2.0 Pro."""
        if not self.gemini_client:
            return None

        try:
            prompt = f"""Sinh MỘT câu hỏi phỏng vấn OJT CÁ NHÂN HÓA SÂU bằng tiếng Việt.
Cá nhân hóa dựa trên dự án trong CV hoặc kinh nghiệm riêng biệt của ứng viên.

- Ứng viên: {state.candidate_name}
- Vị trí: {state.role}
- Công ty: {state.company_target}
- Chủ đề: {state.current_concept}

Chỉ trả về JSON với trường "question_text"."""

            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_pro_model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.7,
                    response_mime_type="application/json",
                ),
            )

            result = json.loads(response.text)
            return Question(
                question_id=f"q_pro_{uuid.uuid4().hex[:8]}",
                question_text=result.get("question_text", ""),
                rubric_type=RubricType.TECHNICAL_CORRECTNESS,
                difficulty=state.current_difficulty,
                concepts=[state.current_concept] if state.current_concept else [],
                applicable_roles=[state.role],
                provenance=QuestionProvenance(
                    source_type=SourceType.AI_GENERATED,
                    generation_model=self.settings.gemini_pro_model,
                    generation_context_refs=[state.session_id],
                    verification_status="auto_generated",
                ),
            )

        except Exception as e:
            logger.error(f"Pro question generation failed: {e}")
            return None

    def _get_wrap_up_question(self, state: InterviewState) -> Question:
        """Closing/wrap-up template (§11.3)."""
        return Question(
            question_id=f"q_wrap_{uuid.uuid4().hex[:8]}",
            question_text=(
                f"Cảm ơn {state.candidate_name} đã tham gia phiên phỏng vấn thử hôm nay. "
                f"Trước khi kết thúc, em có câu hỏi nào muốn hỏi lại về vị trí {state.role} "
                f"tại {state.company_target} không?"
            ),
            rubric_type=RubricType.HR_MOTIVATION,
            difficulty=1,
            stage_name="wrap_up",
            target_rubric="hr_motivation",
            expected_concepts=[],
            applicable_roles=[state.role],
            provenance=QuestionProvenance(
                source_type=SourceType.TEMPLATE_GENERATED,
                verification_status="verified",
            ),
        )


_service_instance: QuestionService | None = None


def get_question_service() -> QuestionService:
    global _service_instance
    if _service_instance is None:
        _service_instance = QuestionService()
    return _service_instance
