"""Local E2E coverage for framework -> sample CV/JD -> interview opening."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domains.candidate import api as cv_api
from app.main import create_app
from app.shared.contracts import WSMessageType
from app.domains.interview.catalog import get_interview_catalog
from app.domains.interview.services.dialogue import get_interview_dialogue
from app.domains.interview.services.questions import get_question_service
from app.domains.interview.websocket import ws_manager
import app.shared.infrastructure.redis as redis_core


def test_catalog_public_projection_does_not_expose_cv_contact_or_raw_text(tmp_path):
    (tmp_path / "candidates_clean.json").write_text(json.dumps([{
        "candidate_id": "CV_X1",
        "framework_id": "IF_X",
        "canonical_role_id": "ROLE_X",
        "target_role": "X Engineer",
        "technical_skills": ["Python"],
        "projects": [{"name": "Local project", "description": "built locally"}],
        "email": "candidate@example.invalid",
        "phone": "000",
        "raw_cv": "private raw CV text",
    }]), encoding="utf-8")
    (tmp_path / "jobs_below_mid_clean.json").write_text(json.dumps([{
        "job_id": "JOB_X1",
        "framework_id": "IF_X",
        "canonical_role_id": "ROLE_X",
        "job_title": "X Engineer",
        "company_name": "Example",
        "skills_required": ["Python"],
    }]), encoding="utf-8")
    (tmp_path / "interview_frameworks_clean.json").write_text(json.dumps([{
        "position_id": "IF_X",
        "role_title": "X Engineer",
        "canonical_role_id": "ROLE_X",
        "canonical_role_name": "X Engineer",
        "role_family": "Engineering",
        "technical_questions": [{"id": "X_Q1", "level": "Intern", "question": "Explain Python lists?"}],
        "behavioral_questions": [],
    }]), encoding="utf-8")

    catalog = get_interview_catalog().__class__(tmp_path)
    public = catalog.public_catalog()
    serialized = json.dumps(public)
    assert public["available"] is True
    assert public["frameworks"][0]["sample_candidate"]["candidate_id"] == "CV_X1"
    assert "candidate@example.invalid" not in serialized
    assert "private raw CV text" not in serialized
    assert catalog.framework_question_bank("IF_X")[0]["stage"] == "technical_core"


def test_normalized_pair_drives_generated_interview_with_offline_model_double(monkeypatch, generated_model):
    catalog = get_interview_catalog()
    if not catalog.available:
        pytest.skip("normalized interview dataset is not mounted in this environment")
    pair = catalog.sample_pair("IF_FE")
    if not pair:
        pytest.skip("no normalized sample pair is available for IF_FE")
    assert pair["candidate"].get("project_count"), "the selected sample CV should contain interviewable project evidence"
    assert pair["job"].get("required_skills"), "the selected sample JD should contain required skills"

    monkeypatch.setattr(redis_core, "get_redis_client", lambda: None)
    monkeypatch.setattr(get_interview_dialogue(), "client", None)
    monkeypatch.setattr(cv_api.get_cv_analyzer(), "gemini_client", None)
    app = create_app()
    app.state.debug_traffic_enabled = False

    session_id = None
    with TestClient(app) as client:
        catalog_response = client.get("/api/v1/cv/interview-catalog")
        assert catalog_response.status_code == 200
        catalog_entry = next(item for item in catalog_response.json()["frameworks"] if item["framework_id"] == "IF_FE")
        assert catalog_entry["sample_candidate"]["candidate_id"] == pair["candidate"]["candidate_id"]
        assert catalog_entry["sample_job"]["job_id"] == pair["job"]["job_id"]

        sample_response = client.get("/api/v1/cv/interview-catalog/IF_FE/sample")
        assert sample_response.status_code == 200
        sample_payload = sample_response.json()
        assert "email" not in sample_payload["candidate_profile"]
        assert "raw_cv" not in sample_payload["candidate_profile"]
        assert sample_payload["candidate_profile"]["projects"]

        create_response = client.post(
            "/api/v1/sessions/create",
            json={
                "student_id": "LOCAL_FRAMEWORK_E2E",
                "target_company": sample_payload["job_context"]["company"],
                "target_role": sample_payload["job_context"]["title"],
                "framework_id": sample_payload["framework_id"],
                "candidate_id": sample_payload["candidate_id"],
                "job_id": sample_payload["job_id"],
            },
        )
        assert create_response.status_code == 200, create_response.text
        created = create_response.json()
        session_id = created["session_id"]
        blueprint = created["blueprint"]
        assert blueprint["framework_id"] == "IF_FE"
        assert blueprint["source_candidate_id"] == sample_payload["candidate_id"]
        assert blueprint["source_job_id"] == sample_payload["job_id"]
        assert blueprint["framework_context"]["competencies"]
        assert all(stage["seed_question"] is None for stage in blueprint["stages"])

        with client.websocket_connect(f"/ws/interview/{session_id}") as websocket:
            initial_state = websocket.receive_json()
            opening = websocket.receive_json()
            assert initial_state["type"] == WSMessageType.STATE_SYNC.value
            assert opening["type"] == WSMessageType.QUESTION_TEXT.value
            assert opening["payload"]["question_text"] not in {item["question"] for item in catalog.framework_question_bank("IF_FE")}
            assert opening["payload"]["provenance"]["source_type"] == "ai_generated"
            assert generated_model.calls[0]["context"]["framework"]["framework_id"] == "IF_FE"
            assert generated_model.calls[0]["context"]["cv_evidence"]["candidate_id"] == sample_payload["candidate_id"]
            assert all(item["question"] not in generated_model.calls[0]["prompt"] for item in catalog.framework_question_bank("IF_FE"))

        with client.websocket_connect(f"/ws/interview/{session_id}") as websocket:
            assert websocket.receive_json()["type"] == WSMessageType.STATE_SYNC.value
            resumed = websocket.receive_json()
            assert resumed["payload"]["question_id"] == opening["payload"]["question_id"]
            assert len(generated_model.calls) == 1

    if session_id:
        ws_manager.disconnect(session_id)
