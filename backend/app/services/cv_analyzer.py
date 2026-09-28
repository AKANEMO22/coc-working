"""
CÓC ĐI LÀM — CV Analyzer Service (§19)
Pipeline 4 tầng: Parsing → ATS Audit → Gap Analysis → Blueprint Bridge.
"""

from google import genai
from google.genai import types
from app.core.config import get_settings
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class CVAnalyzer:
    """
    Phân hệ 1: Phòng Lab Tối ưu CV (§19).
    Pipeline 4 tầng xử lý CV.
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
    # Tầng 2: Kiểm Toán ATS & Google XYZ (§19.2)
    # ================================================================

    async def audit_ats_compliance(self, profile: dict) -> dict:
        """Kiểm tra tương thích ATS."""
        issues = []
        score = 100

        # Kiểm tra sections bắt buộc
        required_sections = ["candidate_name", "education", "skills", "projects"]
        for section in required_sections:
            if not profile.get(section):
                issues.append(f"Thiếu phân mục: {section}")
                score -= 15

        # Kiểm tra contact info
        if not profile.get("email") and not profile.get("phone"):
            issues.append("Thiếu thông tin liên hệ (email/phone)")
            score -= 10

        return {
            "ats_score": max(0, score),
            "issues": issues,
            "recommendations": [
                "Đảm bảo CV có đủ: Contact, Summary, Skills, Experience/Projects, Education"
            ] if issues else [],
        }

    async def score_xyz_formula(self, profile: dict) -> dict:
        """Đánh giá câu từ theo Công thức Google XYZ."""
        if not self.gemini_client:
            return {"xyz_scores": {}, "action_verb_ratio": 0, "quantified_metric_score": 0}

        try:
            projects = profile.get("projects", [])
            if not projects:
                return {"xyz_scores": {}, "action_verb_ratio": 0, "quantified_metric_score": 0}

            response = self.gemini_client.models.generate_content(
                model=self.settings.gemini_flash_model,
                contents=f"""Đánh giá các mô tả dự án/kinh nghiệm theo công thức Google XYZ:
"Đã hoàn thành [X], được đo lường bằng [Y], thông qua việc thực hiện [Z]"

Dự án:
{json.dumps(projects, ensure_ascii=False)}

Trả về JSON:
{{
  "project_scores": [{{
    "project_name": "string",
    "has_action_verb": boolean,
    "has_quantified_metric": boolean,
    "has_method_described": boolean,
    "xyz_score": 0-100,
    "improvement_suggestion": "string"
  }}],
  "action_verb_ratio": 0.0-1.0,
  "quantified_metric_score": 0.0-1.0,
  "overall_xyz_score": 0-100
}}""",
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)

        except Exception as e:
            logger.error(f"XYZ scoring failed: {e}")
            return {}

    # ================================================================
    # Tầng 3: Phân Tích Khoảng Cách Kỹ Năng (§19.3)
    # ================================================================

    async def analyze_gaps(self, profile: dict, jd_text: str) -> dict:
        """So khớp CV với JD, phân loại gaps."""
        if not self.gemini_client:
            return {"gaps": [], "match_score": 0}

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
            return json.loads(response.text)

        except Exception as e:
            logger.error(f"Gap analysis failed: {e}")
            return {"gaps": [], "match_score": 0}

    # ================================================================
    # Tầng 4: Cầu Nối Đề Cương Phỏng Vấn (§19.4)
    # ================================================================

    async def generate_interview_seeds(self, profile: dict, gaps: dict) -> list[dict]:
        """Trích xuất hạt giống thẩm định dự án CV."""
        seeds = []
        projects = profile.get("projects", [])

        for project in projects:
            seed = {
                "project_name": project.get("name", "Unknown"),
                "claimed_technologies": project.get("technologies", []),
                "claimed_role": project.get("role", "unknown"),
                "claimed_results": project.get("results", ""),
                "defense_questions": [],
                "suspicious_points": [],
            }

            if self.gemini_client:
                try:
                    response = self.gemini_client.models.generate_content(
                        model=self.settings.gemini_flash_model,
                        contents=f"""Tạo 2-3 câu hỏi thẩm định dự án CV này theo mô hình STAR:
Dự án: {json.dumps(project, ensure_ascii=False)}

Trả về JSON:
{{
  "defense_questions": ["string"],
  "check_points": ["string"]
}}""",
                        config=types.GenerateContentConfig(
                            temperature=0.5,
                            response_mime_type="application/json",
                        ),
                    )
                    result = json.loads(response.text)
                    seed["defense_questions"] = result.get("defense_questions", [])
                    seed["suspicious_points"] = result.get("check_points", [])
                except Exception:
                    pass

            seeds.append(seed)

        return seeds


_analyzer_instance: CVAnalyzer | None = None


def get_cv_analyzer() -> CVAnalyzer:
    global _analyzer_instance
    if _analyzer_instance is None:
        _analyzer_instance = CVAnalyzer()
    return _analyzer_instance
