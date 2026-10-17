from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.domains.candidate import api as cv_api
from app.main import create_app
from app.shared.infrastructure.redis import RedisSessionManager


def test_local_demo_profile_is_seeded_without_ai_or_persistent_cache(monkeypatch):
    monkeypatch.setattr(
        cv_api,
        "get_settings",
        lambda: SimpleNamespace(app_env="development", auth_profile="PILOT_DEMO"),
    )
    saved: dict = {}
    monkeypatch.setattr(
        RedisSessionManager,
        "cache_candidate_memory",
        lambda _self, student_id, memory: saved.update(student_id=student_id, memory=memory),
    )

    def no_model_or_cv_scoring():
        raise AssertionError("local demo must not invoke model/ATS/XYZ")
    monkeypatch.setattr(cv_api, "get_cv_analyzer", no_model_or_cv_scoring)
    app = create_app()
    app.state.debug_traffic_enabled = False

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cv/demo-profile",
            data={
                "student_id": "DEMO_NVA_LOCAL",
                "sample_cv_text": "NGUYỄN VĂN AN\nJava, Spring Boot, REST API",
            },
        )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["provider"] == "local-demo"
    assert data["profile"]["candidate_name"] == "Nguyễn Văn An"
    assert data["profile"]["raw_text"] == "NGUYỄN VĂN AN\nJava, Spring Boot, REST API"
    assert saved["student_id"] == "DEMO_NVA_LOCAL"
    assert saved["memory"]["is_local_demo"] is True
    assert "ats_audit" not in data and "xyz_scores" not in data
    assert "ats" not in saved["memory"] and "xyz" not in saved["memory"]


def test_cv_upload_only_parses_interview_profile(monkeypatch):
    from pathlib import Path

    profile = {"candidate_name": "Interview Candidate", "skills": {"hard_skills": ["Python"]}, "projects": []}
    calls = []
    class ParsingOnlyAnalyzer:
        async def parse_cv(self, path, file_type):
            assert Path(path).read_bytes() == b"Python project experience"
            calls.append((path, file_type))
            return profile
        async def audit_ats_compliance(self, *_args):
            raise AssertionError("CV optimization has been removed")
        async def score_xyz_formula(self, *_args):
            raise AssertionError("CV optimization must not spend model quota")
    monkeypatch.setattr(cv_api, "get_cv_analyzer", lambda: ParsingOnlyAnalyzer())
    app = create_app()
    app.state.debug_traffic_enabled = False
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cv/upload",
            data={"student_id": "INTERVIEW_UPLOAD_TEST"},
            files={"file": ("candidate.txt", b"Python project experience", "text/plain")},
        )
        cached = client.get("/api/v1/cv/profile/INTERVIEW_UPLOAD_TEST").json()
    assert response.status_code == 200, response.text
    assert response.json() == {"student_id": "INTERVIEW_UPLOAD_TEST", "filename": "candidate.txt", "profile": profile,
                               "interview_match": {"target_role": None, "experience_level": None, "resolved_framework_id": None}}
    assert cached["has_profile"] is True and cached["profile"] == profile
    assert cached["interview_match"]["resolved_framework_id"] is None
    assert calls[0][1] == "txt" and not Path(calls[0][0]).exists()
    memory = RedisSessionManager().get_cached_candidate_memory("INTERVIEW_UPLOAD_TEST")
    assert memory == {"profile": profile}


def test_local_demo_profile_is_hidden_outside_development(monkeypatch):
    monkeypatch.setattr(
        cv_api,
        "get_settings",
        lambda: SimpleNamespace(app_env="production", auth_profile="PILOT_DEMO"),
    )
    app = create_app()
    app.state.debug_traffic_enabled = False

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/cv/demo-profile",
            data={
                "student_id": "DEMO_NVA_LOCAL",
                "sample_cv_text": "fictional demo CV",
            },
        )

    assert response.status_code == 404


def test_new_interview_uses_candidate_name_from_cached_cv(monkeypatch):
    monkeypatch.setattr(
        RedisSessionManager,
        "get_cached_candidate_memory",
        lambda _self, _student_id: {
            "candidate_name": "Nguyễn Văn An",
            "profile": {"candidate_name": "Nguyễn Văn An"},
        },
    )
    monkeypatch.setattr(RedisSessionManager, "set_hot_state", lambda *_args: None)
    monkeypatch.setattr(RedisSessionManager, "cache_blueprint", lambda *_args: None)
    app = create_app()
    app.state.debug_traffic_enabled = False

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/sessions/create",
            json={
                "student_id": "DEMO_NVA_LOCAL",
                "target_company": "FPT Software",
                "target_role": "Java Backend Intern",
                "domain_pack": "it_software",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["state"]["candidate_name"] == "Nguyễn Văn An"
