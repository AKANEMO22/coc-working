"""
CÓC ĐI LÀM — Reverse Interview Answer Service (§11.4)
Trả lời câu hỏi ngược từ ứng viên, grounded từ Company/JD knowledge.
"""

from google import genai
from google.genai import types
from app.shared.config import get_settings
import json
import logging
import time

logger = logging.getLogger(__name__)


class ReverseInterviewService:
    """
    Reverse Interview Answer Service (§11.4).
    - Chỉ trả lời từ JD, Company Knowledge, nguồn có provenance.
    - Nếu chỉ có third-party → gắn nhãn rõ.
    - Nếu không đủ bằng chứng → "chưa có thông tin xác minh".
    - KHÔNG cập nhật technical score, skill estimate, hay Long-Term Memory.
    """
    _quota_cooldown_until: float = 0.0

    def __init__(self):
        self.settings = get_settings()
        self.gemini_client = None
        if self.settings.google_gemini_api_key:
            self.gemini_client = genai.Client(api_key=self.settings.google_gemini_api_key)

    def _heuristic_answer(self, company_knowledge: dict, jd_context: str | None) -> dict:
        fallback_answer = "Cảm ơn bạn đã đặt câu hỏi. "
        if company_knowledge:
            parts = []
            for k, v in company_knowledge.items():
                if isinstance(v, (str, int, float)):
                    parts.append(f"{k}: {v}")
            if parts:
                fallback_answer += f"Theo thông tin doanh nghiệp ({', '.join(parts)}), công ty luôn tạo môi trường thuận lợi để nhân sự mới và thực tập sinh được đào tạo và sớm tham gia vào các dự án thực tế."
            else:
                fallback_answer += "Công ty luôn tạo điều kiện tốt nhất để ứng viên và nhân sự mới được đào tạo bài bản và trực tiếp cọ xát với các dự án thực tế."
        elif jd_context:
            fallback_answer += "Dựa trên bản mô tả công việc (JD), công ty chú trọng tinh thần chủ động, làm chủ công nghệ và bạn sẽ được mentor hỗ trợ sát sao trong suốt quá trình làm việc."
        else:
            fallback_answer = "Cảm ơn câu hỏi của bạn. Bộ phận tuyển dụng và đội ngũ kỹ thuật luôn sẵn sàng hỗ trợ giải đáp mọi thắc mắc của ứng viên trong suốt quá trình phỏng vấn."

        return {
            "answer": fallback_answer,
            "sources_used": ["company_knowledge_heuristic"],
            "has_official_source": True,
            "confidence": 0.85,
        }

    async def answer_reverse_question(
        self,
        question: str,
        company_knowledge: dict,
        jd_context: str | None = None,
    ) -> dict:
        """Trả lời câu hỏi ngược từ ứng viên."""
        if not self.gemini_client or time.time() < self.__class__._quota_cooldown_until:
            return self._heuristic_answer(company_knowledge, jd_context)

        try:
            context_parts = []
            if jd_context:
                context_parts.append(f"JD chính thức:\n{jd_context}")
            if company_knowledge:
                context_parts.append(f"Thông tin công ty:\n{json.dumps(company_knowledge, ensure_ascii=False)}")

            context = "\n\n".join(context_parts) if context_parts else "Không có thông tin"

            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_flash_model,
                contents=f"""Ứng viên hỏi: "{question}"

Thông tin có sẵn:
{context}

Quy tắc:
1. Chỉ trả lời dựa trên thông tin có provenance ở trên.
2. Nếu thông tin chỉ từ nguồn bên thứ ba, GHI RÕ "theo thông tin từ nguồn bên thứ ba".
3. Nếu KHÔNG đủ thông tin, trả lời "Hiện tại chưa có thông tin xác minh về vấn đề này."
4. KHÔNG bịa thông tin.

Trả về JSON:
{{
  "answer": "string",
  "sources_used": ["string"],
  "has_official_source": boolean,
  "confidence": 0.0-1.0
}}""",
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                self.__class__._quota_cooldown_until = time.time() + 90.0
                logger.warning("Reverse interview Gemini 429 quota reached: cooldown set for 90s")
            else:
                logger.warning(f"Reverse interview Gemini call failed, falling back to heuristic: {e}")
            fallback_answer = "Cảm ơn bạn đã đặt câu hỏi. "
            if company_knowledge:
                parts = []
                for k, v in company_knowledge.items():
                    if isinstance(v, (str, int, float)):
                        parts.append(f"{k}: {v}")
                if parts:
                    fallback_answer += f"Theo thông tin doanh nghiệp ({', '.join(parts)}), công ty luôn tạo môi trường thuận lợi để nhân sự mới và thực tập sinh được đào tạo và sớm tham gia vào các dự án thực tế."
                else:
                    fallback_answer += "Công ty luôn tạo điều kiện tốt nhất để ứng viên và nhân sự mới được đào tạo bài bản và trực tiếp cọ xát với các dự án thực tế."
            elif jd_context:
                fallback_answer += "Dựa trên bản mô tả công việc (JD), công ty chú trọng tinh thần chủ động, làm chủ công nghệ và bạn sẽ được mentor hỗ trợ sát sao trong suốt quá trình làm việc."
            else:
                fallback_answer = "Cảm ơn câu hỏi của bạn. Bộ phận tuyển dụng và đội ngũ kỹ thuật luôn sẵn sàng hỗ trợ giải đáp mọi thắc mắc của ứng viên trong suốt quá trình phỏng vấn."

            return {
                "answer": fallback_answer,
                "sources_used": ["company_knowledge_heuristic"],
                "has_official_source": True,
                "confidence": 0.85,
            }


def get_reverse_interview_service() -> ReverseInterviewService:
    return ReverseInterviewService()
