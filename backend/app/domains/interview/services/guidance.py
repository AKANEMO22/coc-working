"""Frameworks guide generation; their example questions must never be delivered verbatim."""

import re
from difflib import SequenceMatcher


class QuestionGenerationUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("Chưa sinh được câu hỏi theo CV/JD/framework. Hãy kiểm tra cấu hình hoặc quota Gemini rồi thử lại; hệ thống không dùng câu mẫu thay thế.")


def normalized_text(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.casefold()))


def copies_reference(text: str, references: list[str]) -> bool:
    normalized = normalized_text(text)
    if not normalized:
        return False
    for reference in references:
        source = normalized_text(reference)
        if not source:
            continue
        if normalized == source:
            return True
        if len(source.split()) >= 5 and source in normalized:
            return True
        if len(source.split()) >= 5 and SequenceMatcher(None, normalized, source).ratio() >= 0.9:
            return True
    return False


def framework_guidance(context: dict | None) -> dict:
    """Allow only planning/rubric fields, excluding question-bank and seed text."""
    context = context or {}
    keys = (
        "framework_id", "role_title", "role_family", "target_levels", "competencies",
        "interview_stages", "evaluation_matrix", "scoring_anchors", "passing_thresholds", "evaluation_rubric",
    )
    return {key: context[key] for key in keys if key in context}
