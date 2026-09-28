"""
CÓC ĐI LÀM — CV REST API (Phân hệ 1)
Endpoints: upload CV, analyze, gap analysis.
"""

from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.services.cv_analyzer import get_cv_analyzer
from app.core.config import get_settings
import tempfile
import os
import logging
import uuid

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/upload")
async def upload_cv(
    file: UploadFile = File(...),
    student_id: str = Form(...),
):
    """Tải lên và phân tích CV."""
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

        # Tầng 2: ATS Audit
        ats_result = await analyzer.audit_ats_compliance(profile)

        # Tầng 2: XYZ Scoring
        xyz_result = await analyzer.score_xyz_formula(profile)

        # Cache profile into Redis/Memory store
        from app.core.redis import RedisSessionManager
        redis = RedisSessionManager()
        redis.cache_candidate_memory(student_id, {"profile": profile, "ats": ats_result, "xyz": xyz_result})

        return {
            "student_id": student_id,
            "filename": file.filename,
            "profile": profile,
            "ats_audit": ats_result,
            "xyz_scores": xyz_result,
        }

    finally:
        os.unlink(tmp_path)


@router.get("/profile/{student_id}")
async def get_candidate_profile(student_id: str):
    """Lấy profile CV đã lưu của sinh viên."""
    from app.core.redis import RedisSessionManager
    redis = RedisSessionManager()
    data = redis.get_cached_candidate_memory(student_id)
    if data and "profile" in data:
        return {"student_id": student_id, "has_profile": True, "profile": data["profile"]}
    return {"student_id": student_id, "has_profile": False, "profile": None}


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
):
    """Tầng 4: Tạo hạt giống phỏng vấn từ CV."""
    analyzer = get_cv_analyzer()

    import json
    profile_data = json.loads(profile)
    gaps_data = json.loads(gaps)

    seeds = await analyzer.generate_interview_seeds(profile_data, gaps_data)
    return {
        "student_id": student_id,
        "interview_seeds": seeds,
    }
