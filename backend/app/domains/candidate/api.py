"""
CÓC ĐI LÀM — Candidate context for interview preparation.
CV/JD are interview inputs, not a separate CV optimization product.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request
from app.domains.candidate.services.cv_analyzer import get_cv_analyzer
from app.shared.config import get_settings
import tempfile
import os
import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()


def _uploaded_cv_match(profile: dict) -> dict:
    """Metadata for filtering JD choices, never a guessed company or JD."""
    from app.domains.interview.facade import get_interview_catalog as load_catalog
    from app.domains.candidate.context import JOB_LEVELS

    role = str(profile.get("target_role") or "").strip()
    raw_level = str(profile.get("current_level") or "").strip()
    level = next((item for item in JOB_LEVELS if item.casefold() == raw_level.casefold()), None)
    framework = load_catalog().resolve_uploaded_cv_role(role) if role else None
    return {
        "target_role": role or None,
        "experience_level": level,
        "resolved_framework_id": framework.get("position_id") if framework else None,
    }


@router.get("/interview-catalog")
async def get_interview_catalog():
    """List role frameworks with safe sample CV/JD choices, excluding contact/raw-CV data."""
    from app.domains.interview.facade import get_interview_catalog as load_catalog

    result = load_catalog().public_catalog()
    if not result.get("available"):
        result["message"] = "Không đọc được thư mục normalized; hãy kiểm tra NORMALIZED_DATA_DIR."
    return result


@router.get("/interview-catalog/{framework_id}/sample")
async def get_interview_sample(framework_id: str):
    """Return one sanitized sample CV/JD/framework pair for interview preparation."""
    from app.domains.interview.facade import framework_context, get_interview_catalog as load_catalog
    from app.domains.candidate.catalog import get_candidate_catalog
    from app.domains.candidate.context import candidate_context, candidate_to_profile, job_context

    catalog = load_catalog()
    pair = catalog.sample_pair(framework_id)
    if not pair:
        raise HTTPException(status_code=404, detail="Không tìm thấy cặp CV/JD mẫu cho framework này")
    candidates = get_candidate_catalog()
    candidate = candidates.get_candidate(pair["candidate"]["candidate_id"])
    job = candidates.get_job(pair["job"]["job_id"])
    framework = pair["framework"]
    return {
        "framework_id": framework.get("position_id"),
        "candidate_id": candidate.get("candidate_id"),
        "job_id": job.get("job_id"),
        "candidate_profile": candidate_to_profile(candidate),
        "candidate_context": candidate_context(candidate),
        "job_context": job_context(job),
        "framework_context": framework_context(framework),
    }


@router.get("/interview-options")
async def get_interview_options(role_id: str | None = None, level: str | None = None):
    """List all loaded CVs/JDs safely so users can select each independently."""
    from app.domains.candidate.catalog import get_candidate_catalog
    from app.domains.interview.facade import get_interview_catalog as load_frameworks
    from app.domains.candidate.context import JOB_LEVELS

    if level and level not in JOB_LEVELS:
        raise HTTPException(status_code=422, detail="Cấp độ không hợp lệ")

    result = get_candidate_catalog().selection_options()
    frameworks = load_frameworks()
    for group, title_key in (("candidates", "target_role"), ("jobs", "title")):
        for option in result[group]:
            framework = frameworks.resolve_selection_framework(
                framework_id=option.get("framework_id"), canonical_role_id=option.get("canonical_role_id"),
                role=option.get(title_key),
            )
            option["resolved_framework_id"] = framework.get("position_id") if framework else None
    result["total_jobs"] = len(result["jobs"])
    result["jobs"] = [option for option in result["jobs"]
                      if (not role_id or option["canonical_role_id"] == role_id)
                      and (not level or level in option["levels"])]
    if not result["available"]:
        result["message"] = "Chưa đọc được danh sách CV/JD; kiểm tra dữ liệu normalized."
    return result


@router.post("/upload")
async def upload_cv(
    file: UploadFile = File(...),
    student_id: str = Form(...),
):
    """Đọc CV và lưu profile làm ngữ cảnh phỏng vấn, không chấm tối ưu CV."""
    analyzer = get_cv_analyzer()

    # Validate file type
    allowed_types = ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain"]
    if file.content_type not in allowed_types and not file.filename.endswith((".pdf", ".docx", ".txt")):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ PDF, DOCX hoặc TXT")

    # Save temp file
    suffix = os.path.splitext(file.filename)[1] if file.filename else ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        # Tầng 1: Parse CV
        file_type = suffix.lstrip(".")
        profile = await analyzer.parse_cv(tmp_path, file_type)

        # Cache profile into Redis/Memory store
        from app.shared.infrastructure.redis import RedisSessionManager
        redis = RedisSessionManager()
        redis.cache_candidate_memory(student_id, {"profile": profile})

        return {
            "student_id": student_id,
            "filename": file.filename,
            "profile": profile,
            "interview_match": _uploaded_cv_match(profile),
        }

    finally:
        os.unlink(tmp_path)


@router.get("/profile/{student_id}")
async def get_candidate_profile(student_id: str):
    """Lấy profile CV đã lưu của sinh viên."""
    from app.shared.infrastructure.redis import RedisSessionManager
    redis = RedisSessionManager()
    data = redis.get_cached_candidate_memory(student_id)
    if data and "profile" in data:
        return {"student_id": student_id, "has_profile": True, "profile": data["profile"],
                "interview_match": _uploaded_cv_match(data["profile"])}
    return {"student_id": student_id, "has_profile": False, "profile": None, "interview_match": None}


@router.post("/demo-profile")
async def seed_local_demo_profile(
    request: Request,
    student_id: str = Form(...),
    sample_cv_text: str = Form(...),
):
    """Seed the bundled fictional CV without sending it to an external AI provider.

    This endpoint is deliberately restricted to the fixed local demo account and
    development mode so it cannot overwrite a real candidate profile.
    """
    settings = get_settings()
    client_host = request.client.host if request.client else ""
    if (
        settings.app_env != "development"
        or settings.auth_profile != "PILOT_DEMO"
        or client_host not in {"127.0.0.1", "::1", "testclient"}
        or student_id != "DEMO_NVA_LOCAL"
    ):
        raise HTTPException(status_code=404, detail="Not found")

    raw_text = sample_cv_text.strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="CV mẫu đang trống")
    if len(raw_text) > 20_000:
        raise HTTPException(status_code=413, detail="CV mẫu vượt quá giới hạn demo")

    # The demo profile is deterministic. In particular, don't invoke Gemini
    # here: the button should work offline and must not create API usage.
    profile = {
        "candidate_name": "Nguyễn Văn An",
        "email": "nguyenvanan.dev@email.com",
        "phone": "0901 234 567",
        "education": [{
            "university": "Đại học Công nghệ Thông tin - ĐHQG TP.HCM",
            "major": "Kỹ thuật Phần mềm",
            "gpa": 3.2,
            "graduation_year": "2022",
        }],
        "skills": {
            "hard_skills": ["Java", "Spring Boot", "Spring MVC", "SQL", "REST API", "Microservices", "Redis"],
            "soft_skills": ["Troubleshooting", "Root Cause Analysis", "Scrum/Agile", "Teamwork"],
            "tools": ["Git", "Maven", "Docker", "Postman", "JUnit", "Mockito"],
        },
        "projects": [{
            "name": "Hệ thống Quản lý Bán hàng & Tích hợp Đối tác",
            "role": "Java Backend Developer",
            "technologies": ["Java 11", "Spring Boot", "PostgreSQL", "Docker", "Redis"],
            "description": "Tích hợp REST API, xử lý truy vấn N+1 và tối ưu truy vấn SQL/Redis.",
            "results": "Phục vụ hơn 50.000 yêu cầu/ngày; giảm 25% thời gian phản hồi API.",
        }],
        "raw_text": raw_text,
    }
    from app.shared.infrastructure.redis import RedisSessionManager
    RedisSessionManager().cache_candidate_memory(student_id, {
        "candidate_name": profile["candidate_name"],
        "profile": profile,
        "is_local_demo": True,
    })

    return {
        "student_id": student_id,
        "filename": "sample_cv_nguyen_van_an.txt",
        "profile": profile,
        "provider": "local-demo",
    }


@router.post("/analyze-gaps")
async def analyze_gaps(
    student_id: str = Form(...),
    jd_text: str = Form(...),
    profile: str = Form(...),
):
    """Tầng 3: Phân tích khoảng cách kỹ năng CV vs JD."""
    analyzer = get_cv_analyzer()

    import json
    profile_data = json.loads(profile)

    gaps = await analyzer.analyze_gaps(profile_data, jd_text)
    return {
        "student_id": student_id,
        "gap_analysis": gaps,
    }


@router.post("/interview-seeds")
async def generate_interview_seeds(
    student_id: str = Form(...),
    profile: str = Form(...),
    gaps: str = Form("{}"),
    framework_id: str | None = Form(None),
):
    """Tầng 4: Tạo hạt giống phỏng vấn từ CV."""
    analyzer = get_cv_analyzer()

    import json
    profile_data = json.loads(profile)
    gaps_data = json.loads(gaps)

    seeds = await analyzer.generate_interview_seeds(profile_data, gaps_data, framework_id=framework_id)
    if not seeds:
        raise HTTPException(status_code=503, detail="Model chưa sinh được câu hỏi theo CV/JD/framework. Kiểm tra Gemini; hệ thống không trả câu mẫu thay thế.")
    return {
        "student_id": student_id,
        "interview_seeds": seeds,
        "generation_source": "model_guided_by_framework",
    }
