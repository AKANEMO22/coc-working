"""Generation is framework-guided, not source replay; all provider calls are test doubles."""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.domains.candidate import api as cv_api
from app.main import create_app
from app.shared.contracts import BlueprintStage, EvaluationEnvelope, InterviewBlueprint, InterviewState, NextAction, RubricType
from app.domains.interview.services.evidence_evaluator import get_evidence_evaluator
from app.domains.interview.services.laya_controller import get_laya_controller
from app.domains.interview.services import questions as question_module
from app.domains.interview.services.dialogue import get_interview_dialogue
from app.domains.interview.services.guidance import QuestionGenerationUnavailable, copies_reference
from app.domains.interview.services.questions import get_question_service


SOURCE_EXAMPLE = "Hãy giải thích cách quản lý bộ nhớ và giải phóng tài nguyên trong hệ thống này?"


class ReferenceCatalog:
    def framework_question_bank(self, **_kwargs):
        return [{"question": SOURCE_EXAMPLE}]


def make_state_and_blueprint():
    state = InterviewState(session_id="guided", student_id="local", candidate_name="Local", role="Engineer", company_target="Local", current_topic="technical_core")
    blueprint = InterviewBlueprint(
        blueprint_id="guided", session_id="guided", student_id="local", candidate_name="Local",
        target_company="Local", target_role="Engineer", domain_pack="software", framework_id="IF_LOCAL",
        framework_context={"framework_id": "IF_LOCAL", "competencies": ["resource ownership"], "evaluation_matrix": [{"criteria": "justify the chosen trade-off"}], "technical_questions": [{"question": SOURCE_EXAMPLE}]},
        candidate_context={"projects": [{"name": "Queue project", "technologies": ["Java"], "results": "reduced latency"}]},
        job_context={"required_skills": ["Java", "concurrency"]},
        stages=[BlueprintStage(stage_id=1, stage_name="technical_core", target_duration_sec=60, rubric_type=RubricType.TECHNICAL_CORRECTNESS, seed_question=SOURCE_EXAMPLE)],
    )
    return state, blueprint


def test_framework_is_criteria_in_prompt_not_a_source_question(monkeypatch, generated_model):
    monkeypatch.setattr(question_module, "get_interview_catalog", lambda: ReferenceCatalog())
    state, blueprint = make_state_and_blueprint()
    result = asyncio.run(get_question_service().get_next_question(
        NextAction.PROBE, state, blueprint, evaluation={"score": 6},
        last_question="What bottleneck did you identify?", candidate_answer="The queue grew during bursts.",
    ))
    context = generated_model.calls[-1]["context"]
    assert context["framework"]["competencies"] == ["resource ownership"]
    assert "Queue project" in generated_model.calls[-1]["prompt"]
    assert context["candidate_answer"] == "The queue grew during bursts."
    assert SOURCE_EXAMPLE not in generated_model.calls[-1]["prompt"]
    assert "seed_question" not in context["stage"]
    assert result.provenance.source_type.value == "ai_generated"
    assert result.question_text != SOURCE_EXAMPLE


def test_copy_with_greeting_is_rejected_instead_of_played(monkeypatch, generated_model):
    monkeypatch.setattr(question_module, "get_interview_catalog", lambda: ReferenceCatalog())
    state, blueprint = make_state_and_blueprint()
    generated_model.fixed_text = "Chào bạn. " + SOURCE_EXAMPLE
    before = state.model_dump()
    with pytest.raises(QuestionGenerationUnavailable):
        asyncio.run(get_question_service().get_next_question(NextAction.SAME_LEVEL, state, blueprint))
    assert state.model_dump() == before


def test_missing_provider_does_not_fall_back_to_bank_or_legacy_seed(monkeypatch):
    monkeypatch.setattr(question_module, "get_interview_catalog", lambda: ReferenceCatalog())
    monkeypatch.setattr(get_question_service(), "gemini_client", None)
    state, blueprint = make_state_and_blueprint()
    with pytest.raises(QuestionGenerationUnavailable):
        asyncio.run(get_question_service().get_opening_question(state, blueprint))
    assert not state.asked_question_texts and not state.current_question
    monkeypatch.setattr(get_interview_dialogue(), "client", None)
    with pytest.raises(QuestionGenerationUnavailable):
        asyncio.run(get_interview_dialogue().format_opening_question(role="Engineer", seed_question=SOURCE_EXAMPLE))


def test_copy_guard_ignores_punctuation_but_rejects_embedded_source():
    assert copies_reference(SOURCE_EXAMPLE.upper().replace("?", "."), [SOURCE_EXAMPLE])
    assert copies_reference("Được rồi, " + SOURCE_EXAMPLE, [SOURCE_EXAMPLE])
    assert not copies_reference("Với dự án queue của bạn, chỉ số nào cho thấy nút nghẽn đã được loại bỏ?", [SOURCE_EXAMPLE])


def test_cv_prep_reports_missing_model_instead_of_returning_example_questions(monkeypatch):
    monkeypatch.setattr(cv_api.get_cv_analyzer(), "gemini_client", None)
    app = create_app()
    app.state.debug_traffic_enabled = False
    with TestClient(app) as client:
        result = client.post("/api/v1/cv/interview-seeds", data={"student_id": "LOCAL", "profile": "{}", "framework_id": "IF_FE"})
        assert result.status_code == 503
        assert "interview_seeds" not in result.json()


def test_generation_failure_can_retry_without_scoring_answer(monkeypatch, generated_model):
    monkeypatch.setattr(get_laya_controller(), "enabled", False)
    evaluations = []

    async def local_evaluate(*, turn_id, rubric_type, current_question, **_kwargs):
        evaluations.append(current_question)
        return EvaluationEnvelope(
            turn_id=turn_id, rubric_type=rubric_type, payload_schema="HRMotivation_EvaluationOutput",
            evaluation_confidence=0.9,
            payload={"role_motivation_specificity": 0.8, "company_understanding_evidence": 0.7, "learning_goal_clarity": 0.9, "observed_points": ["clear goal"], "missing_points": []},
        )

    monkeypatch.setattr(get_evidence_evaluator(), "evaluate", local_evaluate)
    app = create_app()
    app.state.debug_traffic_enabled = False
    with TestClient(app) as client:
        created = client.post("/api/v1/sessions/create", json={"student_id": "GUIDED_RETRY", "target_company": "Local", "target_role": "Java Backend Intern"})
        assert created.status_code == 200
        session_id = created.json()["session_id"]
        generated_model.enabled = False
        with client.websocket_connect(f"/ws/interview/{session_id}") as ws:
            assert ws.receive_json()["type"] == "state_sync"
            assert ws.receive_json()["payload"]["code"] == "QUESTION_GENERATION_UNAVAILABLE"
            initial = client.get(f"/api/v1/sessions/{session_id}/state").json()
            assert not initial["asked_question_texts"]
            generated_model.enabled = True
            ws.send_json({"type": "reconnect", "payload": {"retry_question": True}})
            assert ws.receive_json()["type"] == "state_sync"
            opening = ws.receive_json()
            assert opening["type"] == "question_text"

            generated_model.enabled = False
            answer = "Tôi muốn áp dụng kinh nghiệm vào dự án Java và học cách kiểm chứng hiệu năng thực tế."
            ws.send_json({"type": "final_transcript", "payload": {"turn_id": "retry_turn", "text": answer, "term_candidates": []}})
            gate = ws.receive_json()
            assert gate["type"] == "asr_gate_result"
            if not gate["payload"]["transcript_safe"]:
                follow_up = ws.receive_json()
                assert follow_up["type"] in {"stream_interruption", "stream_interruption_cancelled"}
            assert gate["payload"]["transcript_safe"] is False
            ws.send_json({"type": "user_confirmed_transcript", "payload": {"text": answer}})
            confirmed = ws.receive_json()
            assert confirmed["type"] == "asr_gate_result"
            assert confirmed["payload"]["transcript_safe"] is True
            for _ in range(8):
                event = ws.receive_json()
                if event["type"] == "error":
                    break
            assert event["payload"]["code"] == "QUESTION_GENERATION_UNAVAILABLE"
            failed = client.get(f"/api/v1/sessions/{session_id}/state").json()
            assert failed["pending_question_request"]["candidate_answer"] == answer
            assert failed["committed_answers"][0]["candidate_answer"] == answer
            assert evaluations == []

            generated_model.enabled = True
            ws.send_json({"type": "reconnect", "payload": {"retry_question": True}})
            resumed = ws.receive_json()
            question = ws.receive_json()
            assert resumed["type"] == "state_sync" and question["type"] == "question_text"
            assert not resumed["payload"]["pending_question_request"]
            assert resumed["payload"]["remaining_scored_question_budget"] == failed["remaining_scored_question_budget"]
            assert evaluations == []
            assert generated_model.calls[-1]["context"]["candidate_answer"] == answer
