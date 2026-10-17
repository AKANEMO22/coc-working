from app.domains.interview.services.hard_policy_engine import HardPolicyEngine
import asyncio
from app.domains.interview.api.sessions import get_live_logs
from app.shared.contracts import InterviewState, LayaStreamingDecision, SessionStatus, StreamAction
from app.shared.observability.activity import interview_logger
from app.domains.interview.services.laya_controller import get_laya_controller
from app.domains.interview.websocket import InterviewWebSocketManager
from app.shared.contracts import BlueprintStage, InterviewBlueprint, RubricType
from app.shared.infrastructure.redis import RedisSessionManager


def _state() -> InterviewState:
    return InterviewState(
        session_id="stream-policy-test",
        candidate_name="Candidate",
        student_id="STUDENT_TEST",
        role="Java Backend Intern",
        company_target="FPT Software",
        current_question={"question_text": "Bạn đã xử lý cache thế nào?"},
    )


def test_clarification_is_allowed_after_context_but_pause_alone_is_not_enough():
    policy = HardPolicyEngine()
    too_early = policy.compute_allowed_stream_actions(_state(), partial_duration_sec=1.49)
    enough_context = policy.compute_allowed_stream_actions(_state(), partial_duration_sec=1.5)

    assert StreamAction.CLARIFY_NOW not in too_early
    assert StreamAction.ASK_REPEAT not in too_early
    assert StreamAction.WAIT_FOR_CANDIDATE not in too_early
    assert StreamAction.CLARIFY_NOW in enough_context
    assert StreamAction.ASK_REPEAT in enough_context
    assert StreamAction.WAIT_FOR_CANDIDATE in enough_context
    assert StreamAction.AI_SOFT_INTERRUPT not in enough_context


def test_low_confidence_clarification_keeps_listening_and_high_confidence_can_interrupt():
    policy = HardPolicyEngine()
    allowed = policy.compute_allowed_stream_actions(_state(), partial_duration_sec=2.0)
    low = policy.validate_stream_decision(
        LayaStreamingDecision(stream_action=StreamAction.CLARIFY_NOW, stream_confidence=0.84),
        allowed,
    )
    high = policy.validate_stream_decision(
        LayaStreamingDecision(stream_action=StreamAction.ASK_REPEAT, stream_confidence=0.9),
        allowed,
    )

    assert low.stream_action == StreamAction.CONTINUE
    assert high.stream_action == StreamAction.ASK_REPEAT


def test_poor_audio_can_trigger_early_spoken_repeat_without_waiting_for_final():
    state = _state()
    features = {"duration_sec": 2.0, "audio_quality_ok": False}
    policy = HardPolicyEngine()
    allowed = policy.compute_allowed_stream_actions(state, partial_duration_sec=2.0, audio_quality_ok=False)
    decision = get_laya_controller().predict_streaming_decision(
        "Em đang giải thích phần cache nhưng tiếng bị rè", features, allowed, state,
    )
    validated = policy.validate_stream_decision(decision, allowed)
    assert validated.stream_action == StreamAction.ASK_REPEAT
    assert validated.stream_confidence >= 0.85


def test_mid_speech_bad_audio_generates_contextual_question_without_scoring(monkeypatch):
    state = _state()
    blueprint = InterviewBlueprint(
        blueprint_id="bp_ask_repeat", session_id=state.session_id, student_id=state.student_id,
        candidate_name=state.candidate_name, target_company=state.company_target,
        target_role=state.role, domain_pack="it_software",
        stages=[BlueprintStage(stage_id=1, stage_name="hr_motivation", target_duration_sec=60,
                               rubric_type=RubricType.HR_MOTIVATION)],
    )
    monkeypatch.setattr(RedisSessionManager, "get_blueprint", lambda _self, _sid: blueprint.model_dump())
    manager = InterviewWebSocketManager()
    sent = []
    generated = []

    async def send(_session_id, message):
        sent.append(message)

    async def ask(action, context, _blueprint):
        generated.append((action, context.candidate_answer_draft))
        return "Em nói lại giúp anh ý về cache vừa rồi được không?"

    monkeypatch.setattr(manager, "send_message", send)
    monkeypatch.setattr(manager.question_service, "generate_interruption_dialogue", ask)

    async def exercise():
        await manager.handle_partial_transcript(state.session_id, {
            "turn_id": "partial1", "text": "Em có xử lý cache nhưng tiếng bị rè",
            "features": {"duration_sec": 2.0, "audio_quality_ok": False},
        }, state)
        assert sent[-1]["type"] == "stream_decision"
        assert sent[-1]["payload"]["action"] == "ASK_REPEAT"
        decision_id = sent[-1]["payload"]["decision_id"]
        assert state.committed_answers == []
        await manager.handle_stream_segment(state.session_id, {
            "decision_id": decision_id, "text": "Em có xử lý cache",
        }, state)
        assert sent[-1]["type"] == "stream_interruption"
        assert "nói lại" in sent[-1]["payload"]["utterance"]
        assert generated == [("ASK_REPEAT", "Em có xử lý cache")]
        assert state.committed_answers == []

    asyncio.run(exercise())


def test_interview_cannot_advance_while_stream_clarification_is_pending():
    policy = HardPolicyEngine()
    state = _state()
    state.pending_stream_interruption = {"decision_id": "interrupt-1"}

    assert policy.can_create_turn_decision(has_verified_answer=True, state=state) is False


def test_rubric_report_is_not_allowed_until_the_session_ends():
    policy = HardPolicyEngine()
    state = _state()
    assert policy.can_generate_report(state) is False
    state.status = SessionStatus.FINALIZING
    assert policy.can_generate_report(state) is True


def test_live_debug_logs_expose_p50_p95_and_max_latency():
    session_id = "latency-summary-test"
    for latency in (100, 200, 300):
        interview_logger.add_log(
            stage="QUESTION_GENERATION",
            message="test generation timing",
            session_id=session_id,
            details={"latency_ms": latency},
        )

    result = asyncio.run(get_live_logs(limit=10, session_id=session_id))
    assert result["timing_summary"]["QUESTION_GENERATION"] == {
        "samples": 3,
        "p50_ms": 200,
        "p95_ms": 300,
        "max_ms": 300,
    }
