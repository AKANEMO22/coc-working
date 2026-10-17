"""
CÓC ĐI LÀM — Sessions REST API
Quản lý phiên phỏng vấn, blueprint generation, và báo cáo.
"""

from fastapi import APIRouter, HTTPException
import asyncio
import math
from app.shared.contracts import (
    CreateSessionRequest, CreateSessionResponse,
    GuestLoginRequest, GuestLoginResponse,
    InterviewState, InterviewBlueprint, BlueprintStage,
    SessionStatus, RubricType, ReportStatus,
)
from app.shared.infrastructure.redis import RedisSessionManager
from app.shared.config import get_settings
import uuid
import logging
from datetime import datetime
from app.shared.observability.activity import interview_logger
from app.domains.interview.services.evidence_evaluator import get_evidence_evaluator

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/live-logs")
async def get_live_logs(limit: int = 50, session_id: str | None = None):
    """Truy xuất log live; rubric chỉ xuất hiện sau khi phiên đã kết thúc."""
    logs = interview_logger.get_logs(limit=limit, session_id=session_id)
    samples_by_stage: dict[str, list[float]] = {}
    for entry in logs:
        details = entry.get("details") or {}
        latency = next((details.get(key) for key in (
                            "latency_ms", "decision_latency_ms", "generation_latency_ms",
                            "laya_latency_ms", "answer_to_question_latency_ms",
                        )
                        if isinstance(details.get(key), (int, float))), None)
        if latency is not None:
            samples_by_stage.setdefault(entry["stage"], []).append(float(latency))

    timing_summary = {}
    for stage, samples in samples_by_stage.items():
        ordered = sorted(samples)
        timing_summary[stage] = {
            "samples": len(ordered),
            "p50_ms": round(ordered[math.ceil(0.50 * len(ordered)) - 1], 1),
            "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 1),
            "max_ms": round(ordered[-1], 1),
        }
    return {
        "total": len(interview_logger.logs),
        "logs": logs,
        "timing_summary": timing_summary,
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
    redis = RedisSessionManager()
    from app.domains.interview.catalog import get_interview_catalog
    from app.domains.candidate.facade import CandidateDataNotFound, load_session_context, persist_candidate_selection

    catalog = get_interview_catalog()
    if request.framework_id and catalog.available and not catalog.get_framework(request.framework_id):
        raise HTTPException(status_code=422, detail="Không tìm thấy framework_id trong normalized catalog")
    try:
        snapshot = load_session_context(request.student_id, request.candidate_id, request.job_id)
    except CandidateDataNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if request.job_role_filter and snapshot.job_role_id != request.job_role_filter:
        raise HTTPException(status_code=422, detail="JD không phù hợp chuyên môn đang lọc; hãy chọn lại JD")
    if request.job_level_filter and request.job_level_filter not in snapshot.job_context.get("levels", []):
        raise HTTPException(status_code=422, detail="JD không tuyển cấp độ đang lọc; hãy chọn lại JD")

    job_framework = None
    if request.job_id:
        job_framework = catalog.resolve_selection_framework(
            framework_id=snapshot.job_framework_id,
            canonical_role_id=snapshot.job_role_id,
            role=snapshot.job_context.get("title"),
        )
        if not job_framework:
            raise HTTPException(status_code=422, detail="JD đã chọn chưa được ánh xạ tới khung phỏng vấn; không dùng khung khác thay thế")
        if not request.candidate_id:
            # An uploaded CV with explicit role/level metadata must not be
            # paired with a different JD just because its selector was stale.
            uploaded_role = snapshot.candidate_context.get("target_role")
            uploaded_level = snapshot.candidate_context.get("experience_level")
            uploaded_framework = catalog.resolve_uploaded_cv_role(uploaded_role) if uploaded_role else None
            if uploaded_framework and uploaded_framework.get("position_id") != job_framework.get("position_id"):
                raise HTTPException(status_code=422, detail="JD không đúng vị trí nêu trong CV đã tải lên")
            if uploaded_level and uploaded_level not in snapshot.job_context.get("levels", []):
                raise HTTPException(status_code=422, detail="JD không đúng cấp độ nêu trong CV đã tải lên")

    if request.framework_id:
        framework = catalog.get_framework(request.framework_id)
        if job_framework and framework and job_framework.get("position_id") != framework.get("position_id"):
            raise HTTPException(status_code=422, detail="Framework không phải khung đã ánh xạ từ JD đang chọn")
    elif request.job_id or request.candidate_id:
        # JD is the target job; CV supplies evidence and is a provisional fallback
        # only when no JD has been selected. Same resolver as the options API.
        from_job = bool(request.job_id)
        framework = catalog.resolve_selection_framework(
            framework_id=snapshot.job_framework_id if from_job else snapshot.candidate_framework_id,
            canonical_role_id=snapshot.job_role_id if from_job else snapshot.candidate_role_id,
            role=snapshot.job_context.get("title") if from_job else snapshot.candidate_context.get("target_role"),
        )
        if not framework:
            raise HTTPException(status_code=422, detail="Dữ liệu CV/JD đã chọn chưa có khung phỏng vấn phù hợp")
    else:
        # Legacy uploaded-profile clients may still supply a target role directly.
        framework = catalog.resolve_framework(role=request.target_role)
    framework_role_id = (framework or {}).get("canonical_role_id")
    candidate_framework = None
    if request.candidate_id:
        candidate_framework = catalog.resolve_selection_framework(
            framework_id=snapshot.candidate_framework_id,
            canonical_role_id=snapshot.candidate_role_id,
            role=snapshot.candidate_context.get("target_role"),
        )
    if candidate_framework and framework:
        cv_cross_role = candidate_framework.get("position_id") != framework.get("position_id")
    else:
        cv_cross_role = bool(
            snapshot.candidate_role_id
            and framework_role_id
            and snapshot.candidate_role_id != framework_role_id
        )
    if cv_cross_role and not request.allow_cross_role_cv:
        raise HTTPException(status_code=422, detail="CV khác chuyên môn; cần xác nhận dùng CV này để luyện chuyển hướng nghề nghiệp")
    target_company = request.target_company or snapshot.job_context.get("company") or ""
    target_role = request.target_role or snapshot.job_context.get("title") or (framework or {}).get("role_title") or ""
    if not target_role:
        raise HTTPException(status_code=422, detail="Cần chọn chuyên môn/vị trí phỏng vấn")
    persist_candidate_selection(request.student_id, request.candidate_id)

    job_data = dict(snapshot.job_context) or {
        "title": target_role, "company": target_company,
        "description": request.jd_text or "", "required_skills": request.skill_gaps or [],
    }
    if request.job_id and request.jd_text:
        job_data["description"] = request.jd_text[:12000]
    blueprint = _generate_blueprint(
        session_id=session_id, student_id=request.student_id,
        company=target_company, role=target_role, domain_pack=request.domain_pack,
        skill_gaps=request.skill_gaps, framework=framework,
        resolved_candidate_context=snapshot.candidate_context, resolved_job_context=job_data,
        source_candidate_id=snapshot.source_candidate_id, source_job_id=snapshot.source_job_id,
    )
    candidate_name = snapshot.candidate_name

    # Tạo initial state (§7.2)
    state = InterviewState(
        session_id=session_id,
        candidate_name=candidate_name,
        student_id=request.student_id,
        role=target_role,
        company_target=target_company,
        current_topic=blueprint.stages[0].stage_name if blueprint.stages else None,
        time_remaining_sec=settings.session_default_duration_sec,
        remaining_scored_question_budget=blueprint.total_planned_questions,
    )

    # Lưu vào Redis hot state
    try:
        redis.set_hot_state(session_id, state.model_dump())
        redis.cache_blueprint(session_id, blueprint.model_dump())
        logger.info(f"Session created: {session_id}")
    except Exception as e:
        logger.warning(f"Redis not available, continuing without hot state: {e}")

    # Ghi log khởi tạo phiên
    interview_logger.add_log(
        stage="SESSION_INIT",
        message=f"Khởi tạo phiên phỏng vấn mới: Sinh viên {request.student_id} | {target_company} — {target_role}",
        session_id=session_id,
        details={
            "student_id": request.student_id,
            "company": target_company,
            "role": target_role,
            "domain_pack": request.domain_pack,
            "framework_id": blueprint.framework_id,
            "candidate_id": request.candidate_id,
            "job_id": request.job_id,
            "cross_role_cv_confirmed": cv_cross_role and request.allow_cross_role_cv,
            "job_role_filter": request.job_role_filter,
            "job_level_filter": request.job_level_filter,
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


from app.domains.interview.services.report_service import get_report_service

_final_report_locks: dict[str, asyncio.Lock] = {}


def _pending_report_response(session_id: str, state: dict, redis: RedisSessionManager) -> dict:
    answers = state.get("committed_answers") or []
    scored_ids = {item.get("turn_id") for item in redis.get_turn_evaluations(session_id)}
    return {
        "report_status": ReportStatus.PENDING_EVALUATION.value,
        "session_id": session_id,
        "role": state.get("role", ""),
        "message": "Rubric chưa hoàn tất; không phát hành điểm tạm. Có thể thử lại khi model khả dụng.",
        "scored_answers": sum(1 for answer in answers if answer.get("turn_id") in scored_ids),
        "total_answers": len(answers),
    }


async def _finalize_session_report(session_id: str, initial_state: dict, redis: RedisSessionManager) -> dict:
    """Score committed answers only after the interview ends; failures stay explicitly pending."""
    lock = _final_report_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        state = redis.get_hot_state(session_id) or initial_state
        cached = redis.get_cached_report(session_id)
        if state.get("report_status") == ReportStatus.READY.value and cached:
            return cached

        answers = state.get("committed_answers") or []
        if not answers:
            report = get_report_service().generate_report(session_id=session_id, state=state)
            report["report_status"] = ReportStatus.NO_EVALUATION.value
            state["report_status"] = ReportStatus.NO_EVALUATION.value
            redis.set_hot_state(session_id, state)
            redis.cache_report(session_id, report)
            return report

        state["report_status"] = ReportStatus.PENDING_EVALUATION.value
        redis.set_hot_state(session_id, state)
        evaluator = get_evidence_evaluator()
        blueprint = redis.get_blueprint(session_id) or {}
        existing = {record.get("turn_id") for record in redis.get_turn_evaluations(session_id)}

        for answer in answers:
            turn_id = str(answer.get("turn_id", ""))
            if not turn_id or turn_id in existing:
                continue
            try:
                rubric_type = RubricType(answer.get("rubric_type", RubricType.TECHNICAL_CORRECTNESS.value))
            except ValueError:
                state["report_status"] = ReportStatus.PENDING_EVALUATION.value
                redis.set_hot_state(session_id, state)
                return {
                    "report_status": ReportStatus.PENDING_EVALUATION.value,
                    "session_id": session_id,
                    "message": "Không thể ánh xạ rubric cho một câu trả lời; chưa phát hành điểm tổng kết.",
                    "scored_answers": len(existing),
                    "total_answers": len(answers),
                }

            evaluation = await evaluator.evaluate(
                turn_id=turn_id,
                rubric_type=rubric_type,
                verified_transcript=answer.get("candidate_answer", ""),
                current_question=answer.get("question", ""),
                candidate_context={
                    "role": state.get("role"),
                    "company": state.get("company_target"),
                    "concepts": [answer.get("concept")] if answer.get("concept") else [],
                    "framework_id": blueprint.get("framework_id"),
                    "candidate_evidence": blueprint.get("candidate_context", {}),
                    "job_requirements": blueprint.get("job_context", {}),
                    "framework_rubric": blueprint.get("framework_context", {}).get("evaluation_matrix", []),
                },
            )
            if evaluation is None:
                state["report_status"] = ReportStatus.PENDING_EVALUATION.value
                redis.set_hot_state(session_id, state)
                interview_logger.add_log(
                    stage="FINAL_RUBRIC_PENDING",
                    message="Chưa có đánh giá rubric cho toàn phiên; không ghi điểm tạm.",
                    session_id=session_id,
                    turn_id=turn_id,
                    details={"scored_answers": len(existing), "total_answers": len(answers)},
                )
                return {
                    "report_status": ReportStatus.PENDING_EVALUATION.value,
                    "session_id": session_id,
                    "role": state.get("role", ""),
                    "message": "Đang chờ model đánh giá rubric. Chưa phát hành điểm tạm hoặc điểm giả.",
                    "scored_answers": len(existing),
                    "total_answers": len(answers),
                }

            awarded = evaluation.points_awarded
            missed = evaluation.points_missed
            redis.save_turn_evaluation(session_id, {
                "turn_number": len(existing) + 1,
                "turn_id": turn_id,
                "stage": answer.get("stage", ""),
                "rubric_type": rubric_type.value,
                "question": answer.get("question", ""),
                "candidate_answer": answer.get("candidate_answer", ""),
                "score": round(evaluation.score, 1),
                "confidence": evaluation.evaluation_confidence,
                "candidate_summary": "; ".join(awarded[:3]) if awarded else "Rubric đã hoàn tất; không có điểm mạnh được trích xuất.",
                "better_answer_hint": "Cần làm rõ: " + "; ".join(missed[:2]) if missed else "Không có điểm còn thiếu theo rubric.",
                "points_awarded": awarded,
                "points_missed": missed,
                "payload": evaluation.payload,
                "evaluated_at": datetime.utcnow().isoformat(),
            })
            existing.add(turn_id)

        report = get_report_service().generate_report(session_id=session_id, state=state)
        report["report_status"] = ReportStatus.READY.value
        state["report_status"] = ReportStatus.READY.value
        redis.set_hot_state(session_id, state)
        redis.cache_report(session_id, report)
        interview_logger.add_log(
            stage="FINAL_RUBRIC_COMPLETE",
            message=f"Đã đánh giá rubric tổng kết cho {len(answers)} câu trả lời đã chốt.",
            session_id=session_id,
            details={"scored_answers": len(answers)},
        )
        return report


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

        if state.get("report_status") == ReportStatus.READY.value:
            return redis.get_cached_report(session_id) or get_report_service().generate_report(session_id=session_id, state=state)
        if state.get("report_status") == ReportStatus.PENDING_EVALUATION.value:
            return _pending_report_response(session_id, state, redis)
        if state.get("status") in {SessionStatus.COMPLETED.value, SessionStatus.FINALIZING.value}:
            return await _finalize_session_report(session_id, state, redis)
        return {
            "report_status": "IN_PROGRESS",
            "session_id": session_id,
            "role": state.get("role", ""),
            "message": "Phiên phỏng vấn chưa kết thúc; rubric chưa chạy.",
            "committed_answers": len(state.get("committed_answers") or []),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Report generation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{session_id}/report/retry")
async def retry_session_report(session_id: str):
    """Explicitly retry final scoring; ordinary report reads never spend provider quota again."""
    redis = RedisSessionManager()
    state = redis.get_hot_state(session_id)
    if not state:
        raise HTTPException(status_code=404, detail="Phiên phỏng vấn không tồn tại hoặc đã hết hạn")
    if state.get("status") not in {SessionStatus.COMPLETED.value, SessionStatus.FINALIZING.value}:
        raise HTTPException(status_code=409, detail="Chỉ có thể chấm rubric sau khi phiên đã kết thúc")
    return await _finalize_session_report(session_id, state, redis)


@router.post("/{session_id}/end")
async def end_session(session_id: str):
    """Kết thúc phiên phỏng vấn và tổng hợp báo cáo."""
    try:
        redis = RedisSessionManager()
        state = redis.get_hot_state(session_id)
        if not state:
            raise HTTPException(status_code=404, detail="Session not found")

        if state.get("status") == SessionStatus.COMPLETED.value and state.get("report_status") == ReportStatus.READY.value:
            return {"session_id": session_id, "status": "COMPLETED", "report": redis.get_cached_report(session_id)}

        if state.get("status") == SessionStatus.COMPLETED.value and state.get("report_status") == ReportStatus.PENDING_EVALUATION.value:
            return {
                "session_id": session_id,
                "status": "COMPLETED",
                "report": _pending_report_response(session_id, state, redis),
            }

        state["status"] = SessionStatus.COMPLETED.value
        state["report_status"] = ReportStatus.PENDING_EVALUATION.value
        redis.set_hot_state(session_id, state)

        report = await _finalize_session_report(session_id, state, redis)

        interview_logger.add_log(
            stage="SESSION_END",
            message=f"Phiên phỏng vấn {session_id} đã kết thúc. Trạng thái báo cáo: {report.get('report_status')}.",
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
    framework: dict | None = None,
    resolved_candidate_context: dict | None = None,
    resolved_job_context: dict | None = None,
    source_candidate_id: str | None = None,
    source_job_id: str | None = None,
) -> InterviewBlueprint:
    """Build a competency/rubric plan, never copy example questions into the session."""
    settings = get_settings()
    total_time = settings.session_default_duration_sec
    from app.domains.interview.catalog import framework_context, get_interview_catalog

    catalog = get_interview_catalog()
    framework = framework or catalog.resolve_framework(role=role)
    framework_id = (framework or {}).get("position_id")

    competencies = [str(value) for value in (framework or {}).get("target_competencies", []) if value]
    candidate_skills = ((resolved_candidate_context or {}).get("skills") or {}).get("hard_skills", [])
    if isinstance(candidate_skills, dict):
        candidate_skills = [value for values in candidate_skills.values() for value in (values if isinstance(values, list) else [values])]
    concepts = list(dict.fromkeys((skill_gaps or []) + competencies)) or None

    source_stages = [item for item in (framework or {}).get("interview_stages", [])
                     if isinstance(item, dict) and str(item.get("stage_name", "")).strip()]
    # Older imported frameworks may omit stages. Keep one competency stage,
    # never substitute the former fixed HR/CV/technical/scenario template.
    if not source_stages:
        source_stages = [{"stage_name": "Role competency", "weight_percent": 100,
                          "description": "Assess competencies in the selected framework."}]

    def stage_rubric(item: dict) -> RubricType:
        label = f"{item.get('stage_name', '')} {item.get('description', '')}".casefold()
        if any(token in label for token in ("cv", "project", "portfolio", "dự án")):
            return RubricType.STAR_FRAMEWORK
        if any(token in label for token in ("behavior", "mindset", "motivation", "hr", "phẩm chất")):
            return RubricType.HR_MOTIVATION
        if any(token in label for token in ("case", "scenario", "experiment", "modeling", "tình huống")):
            return RubricType.CASE_STUDY
        return RubricType.TECHNICAL_CORRECTNESS

    weights = []
    for item in source_stages:
        try:
            weight = float(item.get("weight_percent", 0))
        except (TypeError, ValueError):
            weight = 0.0
        weights.append(max(0.0, weight))
    if not sum(weights):
        weights = [1.0] * len(source_stages)
    weight_total = sum(weights)
    budget = max(settings.session_scored_question_budget, len(source_stages))
    remaining = budget - len(source_stages)
    proportional = [remaining * weight / weight_total for weight in weights]
    budgets = [1 + int(amount) for amount in proportional]
    leftovers = budget - sum(budgets)
    for index in sorted(range(len(budgets)), key=lambda i: proportional[i] % 1, reverse=True)[:leftovers]:
        budgets[index] += 1

    stages = []
    for index, item in enumerate(source_stages):
        rubric = stage_rubric(item)
        description = str(item.get("description", "")).strip()
        stage_concepts = [description] if description else []
        if rubric == RubricType.STAR_FRAMEWORK:
            stage_concepts.extend(str(skill) for skill in candidate_skills[:4])
        else:
            stage_concepts.extend(competencies[:5])
        stages.append(BlueprintStage(
            stage_id=index + 1,
            stage_name=str(item["stage_name"]).strip(),
            description=description or None,
            target_duration_sec=round(total_time * weights[index] / weight_total),
            rubric_type=rubric,
            concepts=list(dict.fromkeys(stage_concepts)) or concepts,
            question_budget=budgets[index],
        ))

    return InterviewBlueprint(
        blueprint_id=f"bp_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        candidate_name=student_id,
        student_id=student_id,
        target_company=company,
        target_role=role,
        domain_pack=domain_pack,
        framework_id=framework_id,
        source_candidate_id=source_candidate_id,
        source_job_id=source_job_id,
        framework_context=framework_context(framework),
        candidate_context=resolved_candidate_context or {},
        job_context=resolved_job_context or {},
        total_planned_questions=budget,
        stages=stages,
    )
