"""
CÓC ĐI LÀM — Sessions REST API
Quản lý phiên phỏng vấn, blueprint generation, và báo cáo.
"""

from fastapi import APIRouter, HTTPException
from app.models.schemas import (
    CreateSessionRequest, CreateSessionResponse,
    GuestLoginRequest, GuestLoginResponse,
    InterviewState, InterviewBlueprint, BlueprintStage,
    SessionStatus, RubricType, ReportStatus,
)
from app.core.redis import RedisSessionManager
from app.core.config import get_settings
import uuid
import logging
from datetime import datetime
from app.services.interview_logger import interview_logger

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/live-logs")
async def get_live_logs(limit: int = 50, session_id: str | None = None):
    """Truy xuất luồng log hoạt động thời gian thực của buổi phỏng vấn (Input -> Jev -> Rubric -> TTS)."""
    return {
        "total": len(interview_logger.logs),
        "logs": interview_logger.get_logs(limit=limit, session_id=session_id),
    }


@router.post("/guest-login", response_model=GuestLoginResponse)
async def guest_login(request: GuestLoginRequest):
    """PILOT_DEMO: Đăng nhập bằng tên + MSSV."""
    settings = get_settings()
    if settings.auth_profile != "PILOT_DEMO":
        raise HTTPException(status_code=403, detail="Guest login chỉ dùng trong PILOT_DEMO")

    # Kiểm tra profile hiện tại
    # TODO: Check Supabase for existing profile
    return GuestLoginResponse(
        student_id=request.student_id,
        candidate_name=request.candidate_name,
        has_existing_profile=False,
        session_count=0,
    )


@router.post("/create", response_model=CreateSessionResponse)
@router.post("/initiate", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """Tạo phiên phỏng vấn mới với Interview Blueprint."""
    session_id = f"ses_{uuid.uuid4().hex[:12]}"
    settings = get_settings()

    # Sinh Interview Blueprint (§23.2)
    blueprint = _generate_blueprint(
        session_id=session_id,
        student_id=request.student_id,
        company=request.target_company,
        role=request.target_role,
        domain_pack=request.domain_pack,
        skill_gaps=request.skill_gaps,
    )

    # Tạo initial state (§7.2)
    state = InterviewState(
        session_id=session_id,
        candidate_name=request.student_id,  # Will be updated
        student_id=request.student_id,
        role=request.target_role,
        company_target=request.target_company,
        current_topic=blueprint.stages[0].stage_name if blueprint.stages else None,
        time_remaining_sec=settings.session_default_duration_sec,
        remaining_scored_question_budget=settings.session_scored_question_budget,
    )

    # Lưu vào Redis hot state
    try:
        redis = RedisSessionManager()
        redis.set_hot_state(session_id, state.model_dump())
        redis.cache_blueprint(session_id, blueprint.model_dump())
        logger.info(f"Session created: {session_id}")
    except Exception as e:
        logger.warning(f"Redis not available, continuing without hot state: {e}")

    # Ghi log khởi tạo phiên
    interview_logger.add_log(
        stage="SESSION_INIT",
        message=f"Khởi tạo phiên phỏng vấn mới: Sinh viên {request.student_id} | {request.target_company} — {request.target_role}",
        session_id=session_id,
        details={
            "student_id": request.student_id,
            "company": request.target_company,
            "role": request.target_role,
            "domain_pack": request.domain_pack,
            "total_stages": len(blueprint.stages),
            "question_budget": settings.session_scored_question_budget,
            "duration_sec": settings.session_default_duration_sec,
        },
    )

    return CreateSessionResponse(
        session_id=session_id,
        blueprint=blueprint,
        state=state,
    )


@router.get("/{session_id}/state")
async def get_session_state(session_id: str):
    """Lấy trạng thái phiên hiện tại."""
    try:
        redis = RedisSessionManager()
        state = redis.get_hot_state(session_id)
        if state:
            return state
    except Exception:
        pass

    raise HTTPException(status_code=404, detail="Session not found")


from app.services.report_service import get_report_service


@router.get("/{session_id}/report")
async def get_session_report(session_id: str):
    """
    Lấy báo cáo đánh giá tổng kết (§14):
    - Radar Chart 4 trục: HR Motivation, Project Defense, Technical Core, Case Study
    - Điểm chi tiết kèm bằng chứng (Evidence-Complete) tính toán trực tiếp từ các lượt phỏng vấn
    - Gợi ý câu trả lời tốt hơn (Better-Answer Examples)
    - Lộ trình cải thiện năng lực (Personalized Learning Roadmap)
    """
    try:
        redis = RedisSessionManager()
        state = redis.get_hot_state(session_id)
        if not state:
            # Kiểm tra xem đã có cached report hoàn chỉnh chưa
            cached_report = redis.get_cached_report(session_id)
            if cached_report:
                return cached_report
            raise HTTPException(status_code=404, detail="Phiên phỏng vấn không tồn tại hoặc đã hết hạn")

        report_service = get_report_service()
        report = report_service.generate_report(session_id=session_id, state=state)
        return report

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/end")
async def end_session(session_id: str):
    """Kết thúc phiên phỏng vấn và tổng hợp báo cáo."""
    try:
        redis = RedisSessionManager()
        state = redis.get_hot_state(session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        state["status"] = SessionStatus.COMPLETED.value
        state["report_status"] = ReportStatus.READY.value
        redis.set_hot_state(session_id, state)

        # Tổng hợp báo cáo đánh giá thực tế
        report_service = get_report_service()
        report = report_service.generate_report(session_id=session_id, state=state)

        interview_logger.add_log(
            stage="SESSION_END",
            message=f"Phiên phỏng vấn {session_id} đã kết thúc. Điểm tổng kết: {report.get('overall_score', 0.0)}/10.0 ({report.get('grade')})",
            session_id=session_id,
            details={"overall_score": report.get("overall_score"), "grade": report.get("grade")},
        )

        return {
            "session_id": session_id,
            "status": "COMPLETED",
            "report": report,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _generate_blueprint(
    session_id: str,
    student_id: str,
    company: str,
    role: str,
    domain_pack: str,
    skill_gaps: list[str] | None = None,
) -> InterviewBlueprint:
    """Sinh Interview Blueprint 4 giai đoạn (§23.2)."""
    settings = get_settings()
    total_time = settings.session_default_duration_sec

    stages = [
        BlueprintStage(
            stage_id=1,
            stage_name="hr_motivation",
            target_duration_sec=int(total_time * 0.10),
            rubric_type=RubricType.HR_MOTIVATION,
            seed_question=f"Em hãy chia sẻ ngắn gọn về lý do chọn ứng tuyển vị trí {role} tại {company} và kỳ vọng học hỏi được gì trong kỳ OJT?",
            question_budget=1,
        ),
        BlueprintStage(
            stage_id=2,
            stage_name="cv_project_defense",
            target_duration_sec=int(total_time * 0.25),
            rubric_type=RubricType.STAR_FRAMEWORK,
            seed_question="Hãy chia sẻ về một dự án em ấn tượng nhất trong CV. Mô tả bối cảnh, nhiệm vụ, hành động và kết quả theo mô hình STAR.",
            question_budget=2,
        ),
        BlueprintStage(
            stage_id=3,
            stage_name="technical_core",
            target_duration_sec=int(total_time * 0.45),
            rubric_type=RubricType.TECHNICAL_CORRECTNESS,
            concepts=skill_gaps or ["core_fundamentals"],
            question_budget=3,
        ),
        BlueprintStage(
            stage_id=4,
            stage_name="applied_scenario",
            target_duration_sec=int(total_time * 0.20),
            rubric_type=RubricType.CASE_STUDY,
            seed_question=f"Giả sử hệ thống đang chạy gặp sự cố nghiêm trọng liên quan đến vị trí {role}, em sẽ xử lý tình huống này như thế nào?",
            question_budget=2,
        ),
    ]

    return InterviewBlueprint(
        blueprint_id=f"bp_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        candidate_name=student_id,
        student_id=student_id,
        target_company=company,
        target_role=role,
        domain_pack=domain_pack,
        total_planned_questions=settings.session_scored_question_budget,
        stages=stages,
    )
