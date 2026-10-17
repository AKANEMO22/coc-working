"""
CÓC ĐI LÀM — CV parsing and evidence preparation for interviews.
Extract profile → compare CV/JD evidence → prepare framework-guided questions.
"""

from google import genai
from google.genai import types
from app.shared.config import get_settings
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CVAnalyzer:
    """
    Candidate profile and evidence used by the interview workflow.
    """

    def __init__(self):
        self.settings = get_settings()
        self.gemini_client = None
        if self.settings.google_gemini_api_key:
            self.gemini_client = genai.Client(api_key=self.settings.google_gemini_api_key)

    # ================================================================
    # Tầng 1: Đa Định Dạng & Trích Xuất Cấu Trúc (§19.1)
    # ================================================================

    async def parse_cv(self, file_path: str, file_type: str = "pdf") -> dict:
        """Trích xuất thông tin từ CV đa định dạng."""
        try:
            text_content = ""

            if file_type == "pdf":
                text_content = self._extract_pdf_text(file_path)
            elif file_type in ("docx", "doc"):
                text_content = self._extract_docx_text(file_path)
            elif file_type == "txt":
                with open(file_path, "r", encoding="utf-8") as f:
                    text_content = f.read()

            if not text_content.strip():
                # Fallback: dùng Gemini Vision cho CV dạng ảnh/scan
                text_content = await self._extract_with_vision(file_path)

            # Trích xuất thực thể chuẩn hóa bằng Gemini
            profile = await self._extract_entities(text_content)
            return profile

        except Exception as e:
            logger.error(f"CV parsing failed: {e}")
            return {"error": str(e), "raw_text": ""}

    def _extract_pdf_text(self, file_path: str) -> str:
        """Trích xuất text từ PDF."""
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_parts.append(text)
            return "\n".join(text_parts)
        except Exception as e:
            logger.error(f"PDF extraction failed: {e}")
            return ""

    def _extract_docx_text(self, file_path: str) -> str:
        """Trích xuất text từ DOCX."""
        try:
            from docx import Document
            doc = Document(file_path)
            return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        except Exception as e:
            logger.error(f"DOCX extraction failed: {e}")
            return ""

    async def _extract_with_vision(self, file_path: str) -> str:
        """Dùng Gemini Vision cho CV dạng ảnh/scan phức tạp."""
        if not self.gemini_client:
            return ""

        try:
            with open(file_path, "rb") as f:
                file_data = f.read()

            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_flash_model,
                contents=[
                    types.Part.from_bytes(data=file_data, mime_type="application/pdf"),
                    "Trích xuất TOÀN BỘ nội dung text từ CV này. Giữ nguyên cấu trúc sections.",
                ],
            )
            return response.text
        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            return ""

    async def _extract_entities(self, text: str) -> dict:
        """Trích xuất thực thể chuẩn hóa bằng Gemini."""
        if not self.gemini_client or not text.strip():
            return {"raw_text": text}

        try:
            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_flash_model,
                contents=f"""Phân tích CV sau và trích xuất thông tin theo JSON schema:
{{
  "candidate_name": "string",
  "target_role": "string|null — vị trí nghề nghiệp nêu rõ trong CV; không suy đoán nếu thiếu",
  "current_level": "Intern|Fresher|Junior|Mid|Senior|null — chỉ dùng mức thể hiện rõ trong CV",
  "email": "string|null",
  "phone": "string|null",
  "github": "string|null",
  "linkedin": "string|null",
  "portfolio": "string|null",
  "education": [{{
    "university": "string",
    "major": "string",
    "gpa": "number|null",
    "graduation_year": "string|null"
  }}],
  "skills": {{
    "hard_skills": ["string"],
    "soft_skills": ["string"],
    "tools": ["string"]
  }},
  "projects": [{{
    "name": "string",
    "role": "string",
    "technologies": ["string"],
    "description": "string",
    "results": "string|null"
  }}],
  "certifications": ["string"],
  "awards": ["string"]
}}

CV Content:
{text}""",
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            profile = json.loads(response.text)
            profile["raw_text"] = text
            return profile

        except Exception as e:
            logger.error(f"Entity extraction failed: {e}")
            return {"raw_text": text}


    # ================================================================
    # Tầng 3: Phân Tích Khoảng Cách Kỹ Năng (§19.3)
    # ================================================================

    async def analyze_gaps(self, profile: dict, jd_text: str) -> dict:
        """Compare CV evidence to JD skills for interview preparation."""
        cv_skills = self._profile_skills(profile)
        required_skills = self._required_skills_from_jd(jd_text)
        cv_by_casefold = {skill.casefold(): skill for skill in cv_skills}
        matched = [cv_by_casefold[item.casefold()] for item in required_skills if item.casefold() in cv_by_casefold]
        missing = [item for item in required_skills if item.casefold() not in cv_by_casefold]
        score = round(100 * len(matched) / len(required_skills)) if required_skills else None

        if not self.gemini_client:
            return {
                "match_score": score,
                "matched_skills": matched,
                "critical_hard_gaps": [{"skill": skill, "severity": "unverified"} for skill in missing],
                "depth_gaps": [],
                "missing_keywords": [],
                "analysis_source": "local_skill_overlap" if required_skills else "no_structured_jd_skills",
            }

        try:
            cv_skills = profile.get("skills", {})
            cv_projects = profile.get("projects", [])

            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_flash_model,
                contents=f"""So sánh kỹ năng CV và yêu cầu JD, phân loại gaps:

CV Skills: {json.dumps(cv_skills, ensure_ascii=False)}
CV Projects: {json.dumps(cv_projects, ensure_ascii=False)}

JD (Bản mô tả công việc):
{jd_text}

Trả về JSON:
{{
  "match_score": 0-100,
  "matched_skills": ["string"],
  "critical_hard_gaps": [{{
    "skill": "string",
    "jd_requirement": "string",
    "severity": "critical|high|medium"
  }}],
  "depth_gaps": [{{
    "skill": "string",
    "current_level": "string",
    "required_level": "string"
  }}],
  "context_mismatches": [{{
    "skill": "string",
    "cv_context": "string",
    "jd_context": "string"
  }}],
  "suggested_rewrites": [{{
    "original": "string",
    "improved": "string",
    "reason": "string"
  }}],
  "missing_keywords": ["string"]
}}""",
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            result = json.loads(response.text)
            result.setdefault("matched_skills", matched)
            result.setdefault("critical_hard_gaps", [{"skill": skill, "severity": "unverified"} for skill in missing])
            result["analysis_source"] = "gemini_plus_local_evidence"
            return result

        except Exception as e:
            logger.error(f"Gap analysis failed: {e}")
            return {
                "match_score": score,
                "matched_skills": matched,
                "critical_hard_gaps": [{"skill": skill, "severity": "unverified"} for skill in missing],
                "depth_gaps": [],
                "missing_keywords": [],
                "analysis_source": "local_skill_overlap_after_model_error",
            }

    @staticmethod
    def _profile_skills(profile: dict) -> list[str]:
        skills = profile.get("skills") or {}
        if isinstance(skills, dict):
            values = [item for group in skills.values() for item in (group if isinstance(group, list) else [group])]
        elif isinstance(skills, list):
            values = skills
        else:
            values = []
        return list(dict.fromkeys(str(item).strip() for item in values if item and str(item).strip()))

    @staticmethod
    def _required_skills_from_jd(jd_text: str) -> list[str]:
        try:
            parsed = json.loads(jd_text)
            if isinstance(parsed, dict):
                values = parsed.get("required_skills") or parsed.get("skills_required") or []
                if isinstance(values, list):
                    return list(dict.fromkeys(str(item).strip() for item in values if item))
        except (TypeError, json.JSONDecodeError):
            pass
        return []

    # ================================================================
    # Tầng 4: Cầu Nối Đề Cương Phỏng Vấn (§19.4)
    # ================================================================

    async def generate_interview_seeds(self, profile: dict, gaps: dict, framework_id: str | None = None) -> list[str]:
        """Generate practice questions from framework criteria and real CV evidence."""
        if not self.gemini_client:
            return []
        import asyncio
        from app.domains.interview.facade import framework_context, get_interview_catalog, copies_reference, framework_guidance
        from app.domains.candidate.context import profile_context

        catalog = get_interview_catalog()
        framework = catalog.resolve_framework(framework_id=framework_id, role=profile.get("target_role"))
        references = [str(item.get("question", "")) for item in catalog.framework_question_bank(
            framework_id=(framework or {}).get("position_id"), role=profile.get("target_role"),
        )]
        context = {
            "framework_criteria": framework_guidance(framework_context(framework)),
            "cv_evidence": profile_context(profile), "jd_gaps": gaps,
        }
        prompt = """Tạo 3-5 câu hỏi luyện phỏng vấn MỚI cho CV/JD này theo các năng lực và rubric của framework.
Framework là khung hướng dẫn, không phải kịch bản để đọc lại. Không chép nguyên câu mẫu hoặc chỉ đổi vài từ.
Hỏi về đóng góp cá nhân, quyết định kỹ thuật, trade-off và bằng chứng kết quả thật trong CV.
Không bịa thông tin; nếu CV thiếu dự án thì hỏi theo kỹ năng/JD và ghi rõ tình huống giả định.
Chỉ trả JSON {"questions":["..."]}. Ngữ cảnh:\n""" + json.dumps(context, ensure_ascii=False, default=str)

        def generate():
            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_flash_model, contents=prompt,
                config=types.GenerateContentConfig(temperature=0.6, response_mime_type="application/json"),
            )
            result = json.loads(response.text)
            questions = result.get("questions", [])
            if not isinstance(questions, list):
                return []
            generated = []
            for value in questions:
                if not isinstance(value, str) or not value.strip():
                    continue
                value = value.strip()
                if not copies_reference(value, references + generated):
                    generated.append(value)
            return generated[:5]
        try:
            return await asyncio.wait_for(asyncio.to_thread(generate), timeout=self.settings.interview_generation_timeout_sec)
        except Exception as exc:
            logger.warning("Interview prep generation unavailable: %s", exc)
            return []


_analyzer_instance: CVAnalyzer | None = None


def get_cv_analyzer() -> CVAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = CVAnalyzer()
    return _analyzer_instance
