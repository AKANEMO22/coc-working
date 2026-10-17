"""LLM-first spoken dialogue for the interview orchestrator.

Framework example questions are references, not spoken fallbacks. A failed
model call must be reported instead of reciting corpus text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from google import genai
from google.genai import types

from app.shared.config import get_settings
from app.domains.interview.catalog import framework_context as build_framework_context, get_interview_catalog
from app.domains.interview.services.guidance import QuestionGenerationUnavailable, copies_reference, framework_guidance

logger = logging.getLogger(__name__)


class InterviewDialogueOrchestrator:
    _cooldown_until = 0.0

    def __init__(self):
        self.settings = get_settings()
        self.client = None
        if self.settings.google_gemini_api_key:
            try:
                self.client = genai.Client(
                    api_key=self.settings.google_gemini_api_key,
                    http_options=types.HttpOptions(
                        timeout=round(self.settings.interview_question_timeout_sec * 1000),
                        retry_options=types.HttpRetryOptions(attempts=1),
                    ),
                )
            except Exception as exc:
                logger.warning("Could not initialize interview dialogue model: %s", exc)

    async def format_opening_question(
        self,
        company: str = "",
        role: str = "",
        candidate_name: str = "",
        seed_question: str = "",
        framework_context: dict[str, Any] | None = None,
        candidate_context: dict[str, Any] | None = None,
        job_context: dict[str, Any] | None = None,
    ) -> str:
        # seed_question is accepted only for import compatibility; never feed a
        # copied example to the opening model or return it as a fallback.
        catalog = get_interview_catalog()
        selected = framework_context or build_framework_context(catalog.resolve_framework(role=role))
        context = self._context_json(framework_guidance(selected), candidate_context, job_context)
        display_name = candidate_name if candidate_name and not candidate_name.upper().startswith("DEMO_") and not candidate_name.upper().startswith("STUDENT_") else ""
        greeting = f"Chào bạn {display_name}!" if display_name else "Chào bạn!"
        prompt = f"""Bạn là một Technical Interviewer / Tech Lead giàu kinh nghiệm tại Việt Nam (mang phong thái chuyên nghiệp, ấm áp, cởi mở, đúng chuẩn các buổi Mock Interview IT trên YouTube và thực tế).
Đây là LƯỢT MỞ ĐẦU (Opening) của buổi phỏng vấn vị trí {role or 'Software Engineer'} tại {company or 'công ty'}.
Mục tiêu chính: Chào đón ứng viên, giới thiệu bản thân người phỏng vấn và mời ứng viên tự giới thiệu bản thân về mặt kỹ thuật (Technical Self-Introduction).
TUYỆT ĐỐI KHÔNG nhảy vào hỏi lý thuyết hàn lâm hay đố bài tập kỹ thuật hóc búa ngay lúc này.

Hãy viết lời thoại mở đầu tự nhiên, lịch thiệp, liền mạch (khoảng 3-4 câu):
1. Lời chào & Giới thiệu bản thân: {greeting} Giới thiệu mình là người phỏng vấn kỹ thuật đại diện cho {company or 'công ty'} trong buổi phỏng vấn vị trí {role or 'Software Engineer'} hôm nay.
2. Tạo không khí thoải mái & Nêu mục tiêu: Bày tỏ sự vui mừng được đồng hành cùng bạn. Nhấn mạnh đây là buổi trao đổi cởi mở hai chiều để hai bên cùng tìm hiểu về kỹ năng, kinh nghiệm cũng như định hướng công việc.
3. Mời ứng viên tự giới thiệu bản thân: Mời ứng viên chia sẻ đôi nét về bản thân, quá trình học tập, các mảng công nghệ/kỹ năng thế mạnh mà bạn tự tin nhất và 1-2 dự án tiêu biểu gần đây.

Xưng hô: "mình" - "bạn" (lịch sự, thân thiện, văn phong nói tự nhiên, không rườm rà, phát âm rõ ràng cho TTS).
Chỉ trả về phần lời thoại mà interviewer có thể nói thành tiếng, không giải thích."""
        generated = await self._generate(prompt)
        references = self._reference_texts(selected, role)
        if not generated or copies_reference(generated, references):
            raise QuestionGenerationUnavailable()
        return generated

    async def compose_turn(
        self,
        last_question: str,
        candidate_answer: str,
        evaluation: dict | None,
        next_action: str,
        prev_stage: str,
        next_stage: str,
        raw_question: str,
        role: str = "",
        company: str = "",
        candidate_name: str = "",
        framework_context: dict[str, Any] | None = None,
        candidate_context: dict[str, Any] | None = None,
        job_context: dict[str, Any] | None = None,
    ) -> str:
        question = raw_question.strip()
        references = self._reference_texts(framework_context or {}, role)
        if not question or copies_reference(question, references):
            raise QuestionGenerationUnavailable()
        feedback = json.dumps(evaluation or {}, ensure_ascii=False, default=str)
        context = self._context_json(framework_context, candidate_context, job_context)
        prompt = f"""Bạn là một Technical Interviewer / Tech Lead giàu kinh nghiệm tại Việt Nam (mang phong thái chuyên nghiệp, thân thiện, tôn trọng, giao tiếp hai chiều tự nhiên như các buổi phỏng vấn kỹ thuật thực tế trên YouTube).
Hãy soạn lời nói kế tiếp bằng tiếng Việt cho lượt thoại này (tối đa 3 - 4 câu):
1. Phản hồi kết nối (Conversational Bridge - 1 đến 2 câu):
   - Nếu lượt trước là câu mở đầu và ứng viên vừa giới thiệu bản thân: Nồng nhiệt ghi nhận phần giới thiệu của ứng viên, nhắc lại cụ thể công nghệ hoặc dự án ứng viên THỰC SỰ vừa nói trong câu trả lời. Sau đó chuyển tiếp mượt mà vào câu hỏi chuyên môn tiếp theo.
   - Nếu lượt trước là câu hỏi kỹ thuật/tình huống:
     + Nếu ứng viên trả lời đúng/tốt: Ghi nhận giải pháp hợp lý một cách tự nhiên.
     + Nếu ứng viên trả lời còn thiếu sót: Thừa nhận ý tưởng và nhẹ nhàng phản hồi theo hướng hành động ({next_action}).
     + Nếu ứng viên nói chưa rõ/chưa biết: Tạo sự an tâm, không gây áp lực và chuyển chủ đề nhẹ nhàng.
   - Chỉ phản ánh nội dung ứng viên THỰC SỰ nói, không khen sáo rỗng hay bịa thông tin.
2. Dẫn sang đúng câu hỏi tiếp theo từ question engine:
   - Nối liền câu hỏi kế tiếp: "{question}"
   - Giữ nguyên ý câu hỏi, làm cho toàn bộ lời thoại nghe tự nhiên, liền mạch như một người phỏng vấn thật đang nói chuyện.

Ứng viên: {candidate_name or 'ứng viên'}; vị trí: {role}; công ty: {company}.
Câu vừa hỏi: {last_question}
Câu trả lời của ứng viên: {candidate_answer}
Hành động điều phối: {next_action}; giai đoạn: {prev_stage} -> {next_stage}.
Câu tiếp theo cần hỏi: {question}
Ngữ cảnh framework/CV/JD: {context}
Chỉ trả về lời thoại interviewer có thể nói thành tiếng, không giải thích."""
        generated = await self._generate(prompt)
        # A question already generated from this CV/JD is safe to keep if only
        # the optional transition rewrite fails; corpus text is never allowed.
        return generated if generated and not copies_reference(generated, references) else question

    # Existing websocket/API call sites use this name.
    bridge_turn_dialog = compose_turn

    async def format_wrap_up(
        self,
        role: str,
        company: str,
        candidate_name: str,
        framework_context: dict[str, Any] | None = None,
    ) -> str:
        prompt = f"""Tạo lời kết ngắn bằng tiếng Việt cho buổi phỏng vấn luyện tập.
Ứng viên: {candidate_name}; vị trí: {role}; công ty: {company}.
Framework được dùng: {self._context_json(framework_guidance(framework_context))}
Chỉ nói lời cảm ơn và mời ứng viên hỏi ngược nếu phù hợp. Không đưa thêm kết luận tuyển dụng hay bịa thông tin."""
        generated = await self._generate(prompt)
        if not generated or copies_reference(generated, self._reference_texts(framework_context or {}, role)):
            raise QuestionGenerationUnavailable()
        return generated

    @staticmethod
    def _reference_texts(context: dict[str, Any], role: str) -> list[str]:
        return [str(item.get("question", "")) for item in get_interview_catalog().framework_question_bank(
            framework_id=context.get("framework_id"), role=role,
        )]

    @staticmethod
    def _context_json(*values: dict[str, Any] | None) -> str:
        context = {f"context_{index + 1}": value for index, value in enumerate(values) if value}
        serialized = json.dumps(context, ensure_ascii=False, default=str)
        return serialized[:12000]

    async def _generate(self, prompt: str) -> str | None:
        if not self.client or time.time() < self.__class__._cooldown_until:
            return None

        def call_model() -> str | None:
            try:
                response = self.client.models.generate_content(
                    model=self.settings.gemini_flash_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.55),
                )
                return _clean_spoken_text(getattr(response, "text", None))
            except Exception as exc:
                error = str(exc).casefold()
                if "429" in error or "quota" in error or "resource_exhausted" in error:
                    self.__class__._cooldown_until = time.time() + 90
                logger.warning("Interview dialogue generation failed: %s", exc)
                return None

        try:
            return await asyncio.wait_for(asyncio.to_thread(call_model), timeout=self.settings.interview_question_timeout_sec)
        except Exception as exc:
            logger.debug("Interview dialogue generation unavailable: %s", exc)
            return None


def _clean_spoken_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().strip('"')
    if not text:
        return None
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.casefold().startswith("text"):
            text = text[4:].strip()
    return text or None


_dialogue_service: InterviewDialogueOrchestrator | None = None


def get_interview_dialogue() -> InterviewDialogueOrchestrator:
    global _dialogue_service
    if _dialogue_service is None:
        _dialogue_service = InterviewDialogueOrchestrator()
    return _dialogue_service
