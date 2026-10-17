"""
CÓC ĐI LÀM — Questions REST API
Truy xuất Ngân hàng câu hỏi.
"""

from fastapi import APIRouter, HTTPException
import uuid

router = APIRouter()


from typing import Optional
from app.domains.interview.catalog import get_interview_catalog


@router.post("/orchestrate-discovery", include_in_schema=False)
async def retired_web_discovery():
    """Reject calls from stale tabs without starting any web search/crawl."""
    raise HTTPException(
        status_code=410,
        detail="Đã bỏ crawl web. Sử dụng CV/JD và khung phỏng vấn trong normalized catalog.",
    )


@router.get("/orchestrator-logs", include_in_schema=False)
async def retired_discovery_logs():
    raise HTTPException(status_code=410, detail="Log crawl đã bỏ; dùng /api/v1/sessions/live-logs.")


@router.get("/bank")
async def get_question_bank(
    role: Optional[str] = None,
    company: Optional[str] = None,
    framework_id: Optional[str] = None,
    limit: int = 20,
):
    """Truy xuất câu hỏi đã chuẩn hóa theo chuyên môn/framework."""
    catalog = get_interview_catalog()
    framework = catalog.resolve_framework(framework_id=framework_id, role=role)
    resolved_role = role or (framework or {}).get("canonical_role_name") or (framework or {}).get("role_title")
    if not resolved_role:
        raise HTTPException(status_code=422, detail="Chọn role hoặc framework_id để tra cứu câu hỏi")

    # Read only the loaded framework, never a legacy web-discovery cache.
    framework_questions = catalog.framework_question_bank(
        framework_id=(framework or {}).get("position_id"), role=resolved_role,
    )

    questions = []
    for cq in framework_questions:
        questions.append({
            "id": cq.get("id", f"q_c_{uuid.uuid4().hex[:6]}"),
            "question": cq.get("question"),
            "stage": cq.get("stage", "technical_core"),
            "rubric_type": cq.get("rubric_type", "technical_correctness"),
            "difficulty": cq.get("difficulty", 3),
            "expected_concepts": cq.get("concepts") or cq.get("expected_concepts", []),
            "source": cq.get("source", "Normalized interview framework"),
            "url": cq.get("url", ""),
        })

    return {
        "role": resolved_role,
        "framework_id": (framework or {}).get("position_id"),
        "usage": "reference_only_not_live_script",
        "company": company,
        "domain": (framework or {}).get("role_family"),
        "total": len(questions[:limit]),
        "competencies": (framework or {}).get("target_competencies", []),
        "questions": questions[:limit],
    }


@router.get("/curated/{role}")
@router.get("/by-role/{role}")
async def get_curated_questions(role: str):
    """Lấy câu hỏi curated theo role."""
    catalog = get_interview_catalog()
    framework = catalog.resolve_framework(role=role)
    if not framework:
        return []
    return [
        {
            "id": item.get("id"),
            "role": framework.get("canonical_role_name") or framework.get("role_title"),
            "domain": framework.get("role_family"),
            "question": item.get("question"),
            "category": item.get("stage"),
            "source": item.get("source"),
        }
        for item in catalog.framework_question_bank(str(framework.get("position_id")))
    ]


