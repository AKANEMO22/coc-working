"""Regression tests: setup and question selection must never trigger web crawling."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.domains.interview.api import questions as questions_api
from app.shared.infrastructure.redis import RedisSessionManager
from app.main import create_app
from app.shared.paths import PROJECT_ROOT
from app.shared.contracts import BlueprintStage, InterviewBlueprint, InterviewState, RubricType, NextAction
from app.domains.interview import catalog as catalog_module
from app.domains.interview.services.questions import QuestionService
from app.domains.interview.services import questions as question_module
from tools.manual.legacy.orchestrator_adapter import ModelOrchestratorService


class LocalCatalog:
    def resolve_framework(self, **_kwargs):
        return {"position_id": "IF_LOCAL", "role_title": "Local Engineer", "role_family": "Engineering"}

    def framework_question_bank(self, **_kwargs):
        return [{
            "id": "LOCAL_Q1",
            "question": "Explain the project architecture from the loaded framework?",
            "stage": "technical_core",
            "rubric_type": "technical_correctness",
            "difficulty": 2,
            "expected_concepts": ["architecture"],
            "source": "Normalized framework IF_LOCAL",
        }]


def test_retired_discovery_endpoints_do_not_invoke_any_service(monkeypatch):
    def unexpected_discovery(*_args, **_kwargs):
        pytest.fail("retired route tried to start discovery")

    monkeypatch.setattr(ModelOrchestratorService, "execute_discovery_and_ingest", unexpected_discovery)
    app = create_app()
    app.state.debug_traffic_enabled = False
    with TestClient(app) as client:
        response = client.post("/api/v1/questions/orchestrate-discovery", json={"company": "Local", "role": "Engineer"})
        assert response.status_code == 410
        assert client.get("/api/v1/questions/orchestrator-logs").status_code == 410
        assert "/api/v1/questions/orchestrate-discovery" not in client.get("/openapi.json").json()["paths"]


def test_question_bank_reads_loaded_framework_not_legacy_web_cache(monkeypatch, generated_model):
    def unexpected_cache(*_args, **_kwargs):
        pytest.fail("question lookup tried to read a legacy crawl cache")

    monkeypatch.setattr(RedisSessionManager, "get_cached_candidate_memory", unexpected_cache)
    monkeypatch.setattr(questions_api, "get_interview_catalog", lambda: LocalCatalog())
    app = create_app()
    app.state.debug_traffic_enabled = False
    with TestClient(app) as client:
        response = client.get("/api/v1/questions/bank?framework_id=IF_LOCAL&company=Local")
        assert response.status_code == 200
        assert response.json()["questions"][0]["id"] == "LOCAL_Q1"
        assert response.json()["questions"][0]["source"] == "Normalized framework IF_LOCAL"

    monkeypatch.setattr(catalog_module, "get_interview_catalog", lambda: LocalCatalog())
    monkeypatch.setattr(question_module, "get_interview_catalog", lambda: LocalCatalog())
    monkeypatch.setattr(QuestionService, "_init_gemini", lambda _self: None)
    state = InterviewState(session_id="local", student_id="local", candidate_name="local", role="Local Engineer", company_target="Local", current_topic="technical_core")
    blueprint = InterviewBlueprint(
        blueprint_id="local", session_id="local", student_id="local", candidate_name="local",
        target_company="Local", target_role="Local Engineer", domain_pack="local", framework_id="IF_LOCAL",
        stages=[BlueprintStage(stage_id=1, stage_name="technical_core", target_duration_sec=60, rubric_type=RubricType.TECHNICAL_CORRECTNESS)],
    )
    service = QuestionService()
    service.gemini_client = generated_model
    selected = asyncio.run(service.get_next_question(NextAction.SAME_LEVEL, state, blueprint))
    assert selected is not None and selected.question_id != "LOCAL_Q1"
    assert selected.provenance.source_type.value == "ai_generated"
    assert LocalCatalog().framework_question_bank()[0]["question"] not in generated_model.calls[-1]["prompt"]


def test_legacy_adapter_cannot_start_web_discovery():
    with pytest.raises(RuntimeError, match="removed"):
        asyncio.run(ModelOrchestratorService().execute_discovery_and_ingest("Local", "Engineer"))


def test_frontend_has_no_discovery_trigger_and_monitor_reads_current_session_only():
    root = PROJECT_ROOT
    for relative in (
        "frontend/src/app/interview/page.tsx",
        "frontend/src/app/interview/[sessionId]/page.tsx",
        "frontend/src/components/interview/InterviewActivityPanel.tsx",
    ):
        source = (root / relative).read_text(encoding="utf-8")
        assert "orchestrate-discovery" not in source
        assert "triggerDiscovery" not in source
        assert "OrchestratorConsole" not in source
    monitor = (root / "frontend/src/components/interview/InterviewActivityPanel.tsx").read_text(encoding="utf-8")
    assert "/api/v1/sessions/live-logs" in monitor
    assert "session_id: sessionId" in monitor
