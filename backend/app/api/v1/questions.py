"""
CÓC ĐI LÀM — Questions REST API
Truy xuất Ngân hàng câu hỏi.
"""

from fastapi import APIRouter, HTTPException
from app.services.question_service import get_question_service
import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()


from pydantic import BaseModel
from typing import Optional
from app.services.domain_packs import get_domain_pack_service
from app.services.orchestrator_service import get_orchestrator_service, orchestrator_logger


class OrchestrateDiscoveryRequest(BaseModel):
    company: str
    role: str
    student_id: Optional[str] = None


@router.post("/orchestrate-discovery")
async def orchestrate_discovery(request: OrchestrateDiscoveryRequest):
    """
    Model Orchestrator gọi Tool MCP Web Search và Crawler để
    tự động tìm kiếm lịch sử và câu hỏi phỏng vấn thực tế của công ty.
    """
    service = get_orchestrator_service()
    result = await service.execute_discovery_and_ingest(
        company=request.company,
        role=request.role,
        student_id=request.student_id,
    )
    return result


@router.get("/orchestrator-logs")
async def get_orchestrator_logs(limit: int = 50):
    """Truy xuất danh sách log hoạt động và tool calls của Model Orchestrator."""
    return {
        "total": len(orchestrator_logger.logs),
        "logs": orchestrator_logger.get_logs(limit=limit),
    }


@router.get("/bank")
async def get_question_bank(
    role: str = "Java Backend Intern",
    company: Optional[str] = None,
    limit: int = 20,
):
    """Truy xuất câu hỏi từ Question Bank theo role và company."""
    domain_service = get_domain_pack_service()
    pack = domain_service.get_pack_for_role(role)

    # Lấy câu hỏi đặc thù công ty đã được Orchestrator nạp
    orchestrator = get_orchestrator_service()
    company_questions = []
    if company:
        company_questions = orchestrator.get_ingested_questions(company, role)

    # Ghép câu hỏi từ company và domain pack
    questions = []
    for cq in company_questions:
        questions.append({
            "id": cq.get("id", f"q_c_{uuid.uuid4().hex[:6]}"),
            "question": cq.get("question"),
            "stage": cq.get("stage", "technical_core"),
            "rubric_type": cq.get("rubric_type", "technical_correctness"),
            "difficulty": cq.get("difficulty", 3),
            "expected_concepts": cq.get("concepts") or cq.get("expected_concepts", []),
            "source": cq.get("source", f"{company} Interview Intelligence"),
            "url": cq.get("url", ""),
        })

    for i, q in enumerate(pack.seed_topics):
        questions.append({
            "id": f"q_dp_{i+1}",
            "question": q,
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 2,
            "expected_concepts": pack.core_competencies[:2],
            "source": f"Domain Pack: {pack.display_name}",
        })

    return {
        "role": role,
        "company": company,
        "domain": pack.display_name,
        "total": len(questions[:limit]),
        "competencies": pack.core_competencies,
        "questions": questions[:limit],
    }


@router.get("/curated/{role}")
@router.get("/by-role/{role}")
async def get_curated_questions(role: str):
    """Lấy câu hỏi curated theo role."""
    domain_service = get_domain_pack_service()
    pack = domain_service.get_pack_for_role(role)

    return [
        {
            "id": f"q_{i+1}",
            "role": role,
            "domain": pack.domain_id,
            "question": topic,
            "category": "core_competency",
        }
        for i, topic in enumerate(pack.seed_topics)
    ]


