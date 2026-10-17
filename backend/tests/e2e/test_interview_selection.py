"""Independent CV/JD selection -> session/model context; providers are doubled."""

import json

import pytest
from fastapi.testclient import TestClient

from app.domains.candidate.catalog import CandidateCatalog
from app.domains.candidate import catalog as candidate_catalog, facade as candidate_facade
from app.domains.interview import catalog as interview_catalog, facade as interview_facade
from app.domains.interview.websocket import ws_manager
from app.main import create_app
from app.shared.infrastructure.redis import RedisSessionManager


@pytest.fixture
def selection_client(tmp_path, monkeypatch):
    cvs = [
        {"candidate_id": f"CV_FE_{suffix}", "canonical_role_id": "ROLE_FE", "framework_id": "IF_FE", "target_role": "Frontend",
         "technical_skills": [skill], "projects": [{"name": f"Project {suffix}", "description": "User-owned evidence"}],
         "email": "private@example.invalid", "phone": "secret-phone", "raw_cv": "secret-raw-cv"}
        for suffix, skill in (("A", "Vue"), ("B", "React"))
    ]
    jobs = [
        {"job_id": f"JD_FE_{suffix}", "canonical_role_id": "ROLE_FE", "framework_id": "IF_FE", "job_title": f"Frontend {suffix}",
         "company_name": f"Company {suffix}", "skills_required": [skill], "required_level": "Junior", "declared_levels": "Junior", "raw_job": "do-not-list-raw-job"}
        for suffix, skill in (("A", "Vue"), ("B", "React"))
    ] + [{"job_id": "JD_AI", "canonical_role_id": "ROLE_AI", "framework_id": "IF_AI", "job_title": "AI Intern", "company_name": "AI Company", "skills_required": ["Python"], "required_level": "Intern", "declared_levels": "Fresher, Intern"}]
    frameworks = [{"position_id": fid, "canonical_role_id": rid, "role_title": title, "canonical_role_name": title,
                   "role_family": "Engineering", "target_competencies": [skill], "technical_questions": [], "behavioral_questions": []}
                  for fid, rid, title, skill in (("IF_FE", "ROLE_FE", "Frontend", "React"), ("IF_AI", "ROLE_AI", "AI", "Python"))]
    for filename, records in (("candidates_clean.json", cvs), ("jobs_below_mid_clean.json", jobs), ("interview_frameworks_clean.json", frameworks)):
        (tmp_path / filename).write_text(json.dumps(records), encoding="utf-8")
    cv_catalog = CandidateCatalog(tmp_path)
    framework_catalog = interview_catalog.InterviewCatalog(tmp_path)
    monkeypatch.setattr(candidate_catalog, "get_candidate_catalog", lambda *_: cv_catalog)
    monkeypatch.setattr(candidate_facade, "get_candidate_catalog", lambda *_: cv_catalog)
    monkeypatch.setattr(interview_catalog, "get_interview_catalog", lambda: framework_catalog)
    monkeypatch.setattr(interview_facade, "get_interview_catalog", lambda: framework_catalog)
    app = create_app()
    app.state.debug_traffic_enabled = False
    with TestClient(app) as client:
        yield client


def selection(**updates):
    payload = {"student_id": "SELECT_E2E", "framework_id": "IF_FE", "candidate_id": "CV_FE_B", "job_id": "JD_FE_B", "target_company": "Company B", "target_role": "Frontend B"}
    payload.update(updates)
    return payload


def test_options_are_independent_even_when_framework_has_no_matching_cv(selection_client):
    response = selection_client.get("/api/v1/cv/interview-options")
    assert response.status_code == 200
    data = response.json()
    assert [row["candidate_id"] for row in data["candidates"]] == ["CV_FE_A", "CV_FE_B"]
    assert [row["job_id"] for row in data["jobs"]] == ["JD_FE_A", "JD_FE_B", "JD_AI"]
    assert data["available"] is True
    text = response.text
    assert all(secret not in text for secret in ("private@example.invalid", "secret-phone", "secret-raw-cv", "do-not-list-raw-job"))
    assert set(data["candidates"][0]) == {"candidate_id", "target_role", "experience_level", "skills", "project_count", "canonical_role_id", "framework_id", "resolved_framework_id"}
    assert data["candidates"][0]["resolved_framework_id"] == "IF_FE"
    assert data["jobs"][-1]["resolved_framework_id"] == "IF_AI"


def test_non_default_cv_and_jd_reach_blueprint_and_model(selection_client, generated_model):
    response = selection_client.post("/api/v1/sessions/create", json=selection())
    assert response.status_code == 200, response.text
    data = response.json()
    blueprint = data["blueprint"]
    assert blueprint["source_candidate_id"] == "CV_FE_B"
    assert blueprint["source_job_id"] == "JD_FE_B"
    assert blueprint["candidate_context"]["projects"][0]["name"] == "Project B"
    assert blueprint["job_context"]["company"] == "Company B"
    sid = data["session_id"]
    try:
        with selection_client.websocket_connect(f"/ws/interview/{sid}") as socket:
            socket.receive_json()
            message = socket.receive_json()
            assert message["type"] == "question_text"
        context = generated_model.calls[-1]["context"]
        assert context["cv_evidence"]["candidate_id"] == "CV_FE_B"
        assert context["job_requirements"]["job_id"] == "JD_FE_B"
    finally:
        ws_manager.disconnect(sid)


def test_wrong_job_is_rejected_even_with_cross_role_cv_flag(selection_client):
    response = selection_client.post("/api/v1/sessions/create", json=selection(job_id="JD_AI", allow_cross_role_cv=True))
    assert response.status_code == 422
    assert RedisSessionManager().get_cached_candidate_memory("SELECT_E2E") is None


def test_uploaded_cv_role_and_level_cannot_be_paired_with_wrong_jd(selection_client):
    RedisSessionManager().cache_candidate_memory("UPLOADED_MATCH_E2E", {
        "profile": {"candidate_name": "Uploader", "target_role": "Frontend Developer",
                    "current_level": "Junior", "skills": {"hard_skills": ["React"]}},
    })
    valid = selection_client.post("/api/v1/sessions/create", json={
        "student_id": "UPLOADED_MATCH_E2E", "job_id": "JD_FE_B",
        "target_role": "Frontend B", "target_company": "Company B",
    })
    assert valid.status_code == 200, valid.text
    assert valid.json()["blueprint"]["source_job_id"] == "JD_FE_B"

    wrong_role = selection_client.post("/api/v1/sessions/create", json={
        "student_id": "UPLOADED_MATCH_E2E", "job_id": "JD_AI",
        "target_role": "AI Intern", "target_company": "AI Company",
    })
    assert wrong_role.status_code == 422

    RedisSessionManager().cache_candidate_memory("UPLOADED_LEVEL_E2E", {
        "profile": {"candidate_name": "Uploader", "target_role": "Frontend Developer",
                    "current_level": "Senior", "skills": {"hard_skills": ["React"]}},
    })
    wrong_level = selection_client.post("/api/v1/sessions/create", json={
        "student_id": "UPLOADED_LEVEL_E2E", "job_id": "JD_FE_B",
        "target_role": "Frontend B", "target_company": "Company B",
    })
    assert wrong_level.status_code == 422


def test_cv_transfer_requires_confirmation_and_keeps_original_evidence(selection_client):
    payload = selection(framework_id="IF_AI", job_id="JD_AI", target_role="AI Intern")
    denied = selection_client.post("/api/v1/sessions/create", json=payload)
    assert denied.status_code == 422
    assert RedisSessionManager().get_cached_candidate_memory("SELECT_E2E") is None
    approved = selection_client.post("/api/v1/sessions/create", json={**payload, "allow_cross_role_cv": True})
    assert approved.status_code == 200, approved.text
    blueprint = approved.json()["blueprint"]
    assert blueprint["framework_id"] == "IF_AI"
    assert blueprint["candidate_context"]["target_role"] == "Frontend"
    assert blueprint["source_candidate_id"] == "CV_FE_B"
    assert blueprint["job_context"]["job_id"] == "JD_AI"


def test_unknown_selection_never_falls_back_to_first_record(selection_client):
    for field in ("candidate_id", "job_id"):
        response = selection_client.post("/api/v1/sessions/create", json=selection(**{field: "MISSING_ID"}))
        assert response.status_code == 404


def test_backend_auto_resolves_framework_from_selected_job(selection_client, generated_model):
    # The client may omit framework_id: server must derive the same target.
    payload = selection(framework_id=None, job_id="JD_AI", target_role="AI Intern", allow_cross_role_cv=True)
    response = selection_client.post("/api/v1/sessions/create", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["blueprint"]["framework_id"] == "IF_AI"
    assert data["blueprint"]["source_candidate_id"] == "CV_FE_B"
    sid = data["session_id"]
    try:
        with selection_client.websocket_connect(f"/ws/interview/{sid}") as socket:
            socket.receive_json()
            assert socket.receive_json()["type"] == "question_text"
        context = generated_model.calls[-1]["context"]
        assert context["framework"]["framework_id"] == "IF_AI"
        assert context["cv_evidence"]["candidate_id"] == "CV_FE_B"
        assert context["job_requirements"]["job_id"] == "JD_AI"
    finally:
        ws_manager.disconnect(sid)


def test_canonical_identity_resolves_legacy_ids_and_blocks_unknown_roles(selection_client):
    from app.domains.interview.catalog import get_interview_catalog
    catalog = get_interview_catalog()
    assert catalog.resolve_selection_framework("OLD_FE", "ROLE_FE", "Frontend")["position_id"] == "IF_FE"
    # A wrong linked ID cannot override canonical identity.
    assert catalog.resolve_selection_framework("IF_AI", "ROLE_FE", "Frontend")["position_id"] == "IF_FE"
    assert catalog.resolve_selection_framework(None, "ROLE_MISSING", "AI Engineer") is None


def test_unmapped_selected_job_cannot_use_cv_framework(selection_client, monkeypatch):
    from app.domains.candidate.facade import get_candidate_catalog
    catalog = get_candidate_catalog()
    original = catalog.get_job
    def changed(job_id):
        record = original(job_id)
        return {**record, "canonical_role_id": "ROLE_UNSUPPORTED", "framework_id": "MISSING"} if record else None
    monkeypatch.setattr(catalog, "get_job", changed)
    response = selection_client.post("/api/v1/sessions/create", json=selection(framework_id=None))
    assert response.status_code == 422
    assert RedisSessionManager().get_cached_candidate_memory("SELECT_E2E") is None


def test_job_options_filter_role_and_level_together(selection_client):
    response = selection_client.get("/api/v1/cv/interview-options", params={"role_id": "ROLE_AI", "level": "Intern"})
    assert response.status_code == 200
    assert [job["job_id"] for job in response.json()["jobs"]] == ["JD_AI"]
    assert response.json()["total_jobs"] == 3
    assert len(response.json()["candidates"]) == 2  # Job filters don't erase CV choice.
    assert selection_client.get("/api/v1/cv/interview-options", params={"role_id": "ROLE_FE", "level": "Intern"}).json()["jobs"] == []
    assert selection_client.get("/api/v1/cv/interview-options", params={"level": "unknown"}).status_code == 422


def test_session_rejects_stale_job_that_no_longer_matches_filters(selection_client):
    for filters in ({"job_role_filter": "ROLE_AI"}, {"job_level_filter": "Intern"}):
        response = selection_client.post("/api/v1/sessions/create", json=selection(**filters))
        assert response.status_code == 422
        assert RedisSessionManager().get_cached_candidate_memory("SELECT_E2E") is None
    accepted = selection_client.post("/api/v1/sessions/create", json=selection(
        framework_id=None, job_id="JD_AI", allow_cross_role_cv=True,
        job_role_filter="ROLE_AI", job_level_filter="Intern",
    ))
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["blueprint"]["framework_id"] == "IF_AI"
    assert accepted.json()["blueprint"]["job_context"]["levels"] == ["Intern", "Fresher"]
