"""End-to-end WebSocket interview flow with deterministic offline model doubles."""

from contextlib import asynccontextmanager
from fastapi.testclient import TestClient

from app.domains.candidate import api as cv_api
from app.domains.interview.api import sessions as sessions_api
from app.domains.interview.services.evidence_evaluator import get_evidence_evaluator
from app.domains.interview.services.hard_policy_engine import HardPolicyEngine
from app.domains.interview.services.laya_controller import get_laya_controller
from app.domains.interview.websocket import ws_manager
from app.domains.interview.services.report_service import ReportService
from app.main import create_app
from app.shared.contracts import (
    AnswerIntent,
    DifficultyAction,
    EvaluationEnvelope,
    LayaASRGateDecision,
    LayaStreamingDecision,
    LayaTurnDecision,
    NextAction,
    Question,
    QuestionProvenance,
    ReportStatus,
    RubricType,
    SourceType,
    StreamAction,
    WSMessageType,
)
from app.shared.observability.activity import interview_logger
from app.shared.infrastructure.redis import RedisSessionManager
from app.shared.config import get_settings
import app.shared.infrastructure.redis as redis_core
import time


def _question(question_id: str, text: str) -> Question:
    return Question(
        question_id=question_id,
        question_text=text,
        rubric_type=RubricType.HR_MOTIVATION,
        difficulty=2,
        stage_name="hr_motivation",
        concepts=["động lực", "mục tiêu"],
        applicable_roles=["Java Backend Intern"],
        provenance=QuestionProvenance(
            source_type=SourceType.AI_GENERATED,
            verification_status="generated_not_source_copy",
        ),
    )


def test_recovered_critical_term_alias_requires_confirmation():
    policy = HardPolicyEngine()
    assert policy._detect_critical_disagreement([
        {"raw": "sync", "recovered": "async", "confidence": 0.9, "domain": "protocol"},
    ]) is True


def test_speech_e2e_laya_interrupts_and_rubric_runs_only_after_end(monkeypatch):
    """Exercises setup → WS partial → Laya interrupt → segment checkpoint → TTS text → answer → final report."""
    monkeypatch.setattr(redis_core, "get_redis_client", lambda: None)
    controller = get_laya_controller()
    monkeypatch.setattr(controller, "enabled", False)
    monkeypatch.setattr(get_settings(), "laya_enabled", False)
    stream_decisions = iter([
        LayaStreamingDecision(stream_action=StreamAction.WAIT_FOR_CANDIDATE, stream_confidence=0.96),
        LayaStreamingDecision(stream_action=StreamAction.CLARIFY_NOW, stream_confidence=0.96),
        LayaStreamingDecision(stream_action=StreamAction.CONTINUE, stream_confidence=0.95),
    ])
    monkeypatch.setattr(controller, "predict_streaming_decision", lambda *_args: next(stream_decisions))
    monkeypatch.setattr(controller, "predict_asr_gate_decision", lambda *_args: LayaASRGateDecision(
        transcript_safe=True,
        asr_gate_action="ACCEPT_AS_IS",
        asr_confidence=0.99,
    ))
    monkeypatch.setattr(controller, "predict_turn_decision", lambda _state, _context, _allowed: LayaTurnDecision(
        answer_intent=AnswerIntent.DIRECT_ANSWER,
        relevance=0.9,
        decision_confidence=0.9,
        next_action=NextAction.SAME_LEVEL,
        difficulty_action=DifficultyAction.MAINTAIN,
    ))

    question_service = ws_manager.question_service
    original_methods = (
        question_service.get_opening_question,
        question_service.get_next_question,
        question_service.generate_interruption_dialogue,
    )
    generated_dialogues = []

    async def opening(state, _blueprint):
        return _question("e2e_opening", f"Chào {state.candidate_name}, bạn muốn học được điều gì ở vị trí này?")

    async def next_question(_action, _state, _blueprint, *, evaluation=None, **_kwargs):
        assert evaluation is None, "Live orchestration must not depend on a rubric score"
        return _question("e2e_next", "Bạn có thể chia sẻ một ví dụ cụ thể từ dự án của mình không?")

    async def generated_clarification(action, state, _blueprint):
        generated_dialogues.append((action, state.candidate_answer_draft))
        return "Bạn vừa nhắc đến Redis; bạn dùng Redis để lưu cache hay làm hàng đợi công việc?"

    monkeypatch.setattr(question_service, "get_opening_question", opening)
    monkeypatch.setattr(question_service, "get_next_question", next_question)
    monkeypatch.setattr(question_service, "generate_interruption_dialogue", generated_clarification)
    evaluator = get_evidence_evaluator()
    evaluation_calls = []

    async def final_evaluate(*, turn_id, rubric_type, **_kwargs):
        evaluation_calls.append((turn_id, rubric_type))
        return EvaluationEnvelope(
            turn_id=turn_id,
            rubric_type=rubric_type,
            payload_schema="HRMotivation_EvaluationOutput",
            evaluation_confidence=0.91,
            payload={
                "role_motivation_specificity": 0.8,
                "company_understanding_evidence": 0.7,
                "learning_goal_clarity": 0.9,
                "collaboration_example_quality": None,
                "assessed_dimensions": ["role_motivation_specificity", "company_understanding_evidence", "learning_goal_clarity"],
                "observed_points": ["Nêu được động lực cụ thể"],
                "missing_points": [],
            },
        )

    monkeypatch.setattr(evaluator, "evaluate", final_evaluate)
    monkeypatch.setattr(cv_api.get_cv_analyzer(), "gemini_client", None)
    monkeypatch.setattr(sessions_api, "get_report_service", lambda: ReportService(RedisSessionManager()))

    app = create_app()
    app.state.debug_traffic_enabled = False
    @asynccontextmanager
    async def offline_lifespan(_app):
        yield

    app.router.lifespan_context = offline_lifespan
    with TestClient(app) as client:
        student_id = "E2E_LAYA_INTERRUPT"
        assert client.post("/api/v1/sessions/guest-login", json={
            "student_id": student_id, "candidate_name": "Ứng viên E2E",
        }).status_code == 200
        upload = client.post(
            "/api/v1/cv/upload",
            data={"student_id": student_id},
            files={"file": ("e2e-cv.txt", "Java, Spring Boot, REST API, Redis", "text/plain")},
        )
        assert upload.status_code == 200, upload.text
        created = client.post("/api/v1/sessions/create", json={
            "student_id": student_id,
            "target_company": "FPT Software",
            "target_role": "Java Backend Intern",
            "domain_pack": "it_software",
        })
        assert created.status_code == 200, created.text
        session_id = created.json()["session_id"]

        with client.websocket_connect(f"/ws/interview/{session_id}") as websocket:
            assert websocket.receive_json()["type"] == WSMessageType.STATE_SYNC.value
            assert websocket.receive_json()["type"] == WSMessageType.QUESTION_TEXT.value

            websocket.send_json({
                "type": WSMessageType.PARTIAL_TRANSCRIPT.value,
                "payload": {
                    "text": "Để em suy nghĩ một chút về phần xử lý cache",
                    "features": {"duration_sec": 2.0, "audio_quality_ok": True},
                },
            })
            pause = websocket.receive_json()
            assert pause["type"] == WSMessageType.STREAM_DECISION.value
            assert pause["payload"]["action"] == StreamAction.WAIT_FOR_CANDIDATE.value
            assert evaluation_calls == []

            time.sleep(0.7)
            websocket.send_json({
                "type": WSMessageType.PARTIAL_TRANSCRIPT.value,
                "payload": {
                    "text": "Em dùng Redis để xử lý cache nhưng luồng ghi chưa rõ",
                    "features": {"duration_sec": 3.2, "audio_quality_ok": True},
                },
            })
            interrupt = websocket.receive_json()
            assert interrupt["type"] == WSMessageType.STREAM_DECISION.value
            assert interrupt["payload"]["action"] == StreamAction.CLARIFY_NOW.value
            decision_id = interrupt["payload"]["decision_id"]
            assert evaluation_calls == []

            # This is the client-side commit handshake after it stops mic capture.
            websocket.send_json({
                "type": WSMessageType.STREAM_SEGMENT.value,
                "payload": {"decision_id": decision_id, "text": "Em dùng Redis để xử lý cache"},
            })
            clarification = websocket.receive_json()
            assert clarification["type"] == WSMessageType.STREAM_INTERRUPTION.value
            assert "Redis" in clarification["payload"]["utterance"]
            assert generated_dialogues == [(StreamAction.CLARIFY_NOW.value, "Em dùng Redis để xử lý cache")]
            assert evaluation_calls == []

            time.sleep(0.7)  # exercise the stream-decision throttle, not a timing race
            websocket.send_json({
                "type": WSMessageType.PARTIAL_TRANSCRIPT.value,
                "payload": {"text": "Em dùng Redis để xử lý cache và bảo đảm các job không bị mất", "features": {"duration_sec": 4.1}},
            })
            assert websocket.receive_json()["type"] == WSMessageType.STREAM_DECISION.value
            websocket.send_json({
                "type": WSMessageType.USER_CONFIRMED_TRANSCRIPT.value,
                "payload": {
                    "turn_id": "e2e_answer_1",
                    "text": "Em dùng Redis để xử lý cache và bảo đảm các job không bị mất.",
                    "term_candidates": [],
                },
            })
            assert websocket.receive_json()["type"] == WSMessageType.ASR_GATE_RESULT.value
            assert websocket.receive_json()["type"] == WSMessageType.STATE_SYNC.value
            next_question = websocket.receive_json()
            assert next_question["type"] == WSMessageType.QUESTION_TEXT.value
            assert evaluation_calls == [], "Rubric must not run between interview questions"

        pending = client.get(f"/api/v1/sessions/{session_id}/report")
        assert pending.status_code == 200
        assert pending.json()["report_status"] == "IN_PROGRESS"
        assert "overall_score" not in pending.json()
        assert evaluation_calls == []
        assert not any(
            log["stage"] == "RUBRIC_EVAL"
            for log in interview_logger.get_logs(limit=300, session_id=session_id)
        )

        ended = client.post(f"/api/v1/sessions/{session_id}/end")
        assert ended.status_code == 200, ended.text
        report = ended.json()["report"]
        assert report["report_status"] == ReportStatus.READY.value
        assert len(evaluation_calls) == 1
        assert len(report["turn_evaluations"]) == 1
        assert report["overall_score"] > 0
        saved_answers = RedisSessionManager().get_turn_evaluations(session_id)
        assert saved_answers[0]["candidate_answer"] == "Em dùng Redis để xử lý cache và bảo đảm các job không bị mất."
        assert client.get(f"/api/v1/sessions/{session_id}/report").json()["report_status"] == ReportStatus.READY.value
        assert client.post(f"/api/v1/sessions/{session_id}/end").json()["report"]["report_status"] == ReportStatus.READY.value
        assert len(evaluation_calls) == 1, "Repeated reads/end requests must not rescore a completed report"

    ws_manager.disconnect(session_id)


def test_final_rubric_failure_never_returns_temporary_zero_or_heuristic_score(monkeypatch):
    monkeypatch.setattr(redis_core, "get_redis_client", lambda: None)
    redis = RedisSessionManager()
    session_id = "ses_final_eval_pending_test"
    redis.set_hot_state(session_id, {
        "session_id": session_id,
        "status": "IN_PROGRESS",
        "report_status": "NOT_READY",
        "student_id": "STUDENT_PENDING",
        "role": "Java Backend Intern",
        "company_target": "FPT Software",
        "committed_answers": [{
            "turn_id": "pending_turn_1",
            "stage": "hr_motivation",
            "rubric_type": RubricType.HR_MOTIVATION.value,
            "question": "Vì sao ứng tuyển?",
            "candidate_answer": "Em muốn học quy trình phát triển phần mềm thực tế.",
        }],
    })
    evaluator = get_evidence_evaluator()
    calls = []

    async def unavailable_evaluation(**_kwargs):
        calls.append("attempt")
        return None

    monkeypatch.setattr(evaluator, "evaluate", unavailable_evaluation)
    app = create_app()
    app.state.debug_traffic_enabled = False

    @asynccontextmanager
    async def offline_lifespan(_app):
        yield

    app.router.lifespan_context = offline_lifespan
    with TestClient(app) as client:
        ended = client.post(f"/api/v1/sessions/{session_id}/end")
        assert ended.status_code == 200
        report = ended.json()["report"]
        assert report["report_status"] == ReportStatus.PENDING_EVALUATION.value
        assert "overall_score" not in report

        read_again = client.get(f"/api/v1/sessions/{session_id}/report").json()
        assert read_again["report_status"] == ReportStatus.PENDING_EVALUATION.value
        assert "overall_score" not in read_again
        assert len(calls) == 1, "Reading a pending report must not silently retry a provider call"

        retry = client.post(f"/api/v1/sessions/{session_id}/report/retry")
        assert retry.status_code == 200
        assert retry.json()["report_status"] == ReportStatus.PENDING_EVALUATION.value
        assert "overall_score" not in retry.json()
        assert len(calls) == 2, "Only the explicit retry action may run evaluation again"
