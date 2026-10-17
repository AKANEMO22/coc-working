"""An uncertain spoken answer gets a model-written repeat prompt, not a click gate."""
import asyncio

from app.domains.interview.websocket import InterviewWebSocketManager
from app.shared.contracts import (
    BlueprintStage, InterviewBlueprint, InterviewState, LayaASRGateDecision, RubricType,
)
from app.shared.infrastructure.redis import RedisSessionManager


def test_unclear_answer_is_spoken_back_and_consistent_repeat_is_accepted(monkeypatch):
    manager = InterviewWebSocketManager()
    state = InterviewState(
        session_id="ses_auto_repeat", student_id="TEST", candidate_name="Ứng viên",
        role="Java Backend Intern", company_target="TechLab",
        current_topic="hr_motivation",
        current_question={"question_id": "q1", "question_text": "Vì sao chọn Java?",
                          "rubric_type": "hr_motivation", "stage_name": "hr_motivation"},
    )
    blueprint = InterviewBlueprint(
        blueprint_id="bp1", session_id=state.session_id, student_id="TEST",
        candidate_name="Ứng viên", target_company="TechLab", target_role=state.role,
        domain_pack="it_software",
        stages=[BlueprintStage(stage_id=1, stage_name="hr_motivation", target_duration_sec=60,
                               rubric_type=RubricType.HR_MOTIVATION)],
    )
    monkeypatch.setattr(RedisSessionManager, "get_blueprint", lambda _self, _id: blueprint.model_dump())
    monkeypatch.setattr(manager.laya, "predict_asr_gate_decision", lambda *_args: LayaASRGateDecision(
        transcript_safe=False, asr_gate_action="REQUEST_VERIFICATION", asr_confidence=0.42,
    ))
    prompts = []

    async def generate(action, context, _blueprint, unclear_phrase=""):
        prompts.append((action, context.candidate_answer_draft))
        return "Em có thể nói lại ý về dự án Java vừa rồi cho rõ hơn không?"

    monkeypatch.setattr(manager.question_service, "generate_interruption_dialogue", generate)
    events = []
    committed = []

    async def send(_id, event):
        events.append(event)

    async def advance(_id, turn_id, text, _state, **_kwargs):
        committed.append((turn_id, text))

    monkeypatch.setattr(manager, "send_message", send)
    monkeypatch.setattr(manager, "_advance_conversation_after_answer", advance)
    answer = "Em chọn Java để học cách xây API và làm việc trong nhóm backend."

    async def exercise():
        await manager.handle_final_transcript(state.session_id, {"turn_id": "first", "text": answer}, state)
        assert [event["type"] for event in events] == ["asr_gate_result", "stream_interruption"]
        assert events[-1]["payload"]["action"] == "ASK_REPEAT"
        assert "nói lại" in events[-1]["payload"]["utterance"]
        assert state.pending_answer_transcript["retry_requested"] is True
        assert committed == []
        assert prompts == [("ASK_REPEAT", answer)]

        events.clear()
        await manager.handle_final_transcript(state.session_id, {"turn_id": "repeat", "text": answer}, state)
        assert [event["type"] for event in events] == ["asr_gate_result"]
        assert events[0]["payload"]["transcript_safe"] is True
        assert committed == [("repeat", answer)]
        assert state.pending_answer_transcript == {}

    asyncio.run(exercise())


def test_clear_qwen_capture_skips_unnecessary_repeat_and_advances(monkeypatch):
    manager = InterviewWebSocketManager()
    state = InterviewState(
        session_id="ses_clear_capture", student_id="TEST", candidate_name="Ứng viên",
        role="Frontend Intern", company_target="TechLab", current_topic="hr_motivation",
        current_question={"question_id": "q1", "question_text": "Bạn đã làm gì với React?",
                          "rubric_type": "hr_motivation", "stage_name": "hr_motivation"},
    )
    monkeypatch.setattr(manager.laya, "predict_asr_gate_decision", lambda *_args: LayaASRGateDecision(
        transcript_safe=False, asr_gate_action="REQUEST_VERIFICATION", asr_confidence=0.0337,
    ))
    events, committed = [], []

    async def send(_id, event):
        events.append(event)

    async def advance(_id, turn_id, text, _state, **_kwargs):
        committed.append((turn_id, text))

    monkeypatch.setattr(manager, "send_message", send)
    monkeypatch.setattr(manager, "_advance_conversation_after_answer", advance)
    answer = "Em dùng React để làm giao diện và phối hợp review code với nhóm."
    asyncio.run(manager.handle_final_transcript(state.session_id, {
        "turn_id": "clear", "text": answer,
        "asr_evidence": {"source": "qwen_microphone", "duration_sec": 5.0,
                         "rms": 0.055, "clipped_fraction": 0.0, "audio_quality_ok": True},
    }, state))
    assert [event["type"] for event in events] == ["asr_gate_result"]
    assert events[0]["payload"]["transcript_safe"] is True
    assert committed == [("clear", answer)]


def test_short_spoken_term_clarification_preserves_rest_of_original_answer(monkeypatch):
    manager = InterviewWebSocketManager()
    state = InterviewState(
        session_id="ses_term_clarification", student_id="TEST", candidate_name="Ứng viên",
        role="Frontend Intern", company_target="TechLab", current_topic="technical",
        current_question={"question_id": "q1", "question_text": "Em dùng gì làm giao diện?",
                          "rubric_type": "technical_correctness", "stage_name": "technical"},
    )
    blueprint = InterviewBlueprint(
        blueprint_id="bp_term", session_id=state.session_id, student_id="TEST",
        candidate_name="Ứng viên", target_company="TechLab", target_role=state.role,
        domain_pack="it", stages=[BlueprintStage(stage_id=1, stage_name="technical",
        target_duration_sec=60, rubric_type=RubricType.TECHNICAL_CORRECTNESS)],
    )
    monkeypatch.setattr(RedisSessionManager, "get_blueprint", lambda _self, _id: blueprint.model_dump())
    monkeypatch.setattr(manager.laya, "predict_asr_gate_decision", lambda *_args: LayaASRGateDecision(
        transcript_safe=False, asr_gate_action="REQUEST_VERIFICATION", asr_confidence=0.03,
    ))
    prompts, committed, events = [], [], []

    async def generate(_action, _state, _blueprint, unclear_phrase=""):
        prompts.append(unclear_phrase)
        return 'Em vừa nói "ri ác" là thuật ngữ nào ạ?'

    async def send(_sid, event):
        events.append(event)

    async def advance(_sid, _turn, text, _state, *, asr_audit=None):
        committed.append((text, asr_audit))

    monkeypatch.setattr(manager.question_service, "generate_interruption_dialogue", generate)
    monkeypatch.setattr(manager, "send_message", send)
    monkeypatch.setattr(manager, "_advance_conversation_after_answer", advance)
    evidence = {"source": "qwen_microphone", "duration_sec": 3.0,
                "rms": 0.05, "clipped_fraction": 0.0, "audio_quality_ok": True}
    original = "Em dùng ri ác để xây giao diện và phối hợp nhóm."

    async def exercise():
        await manager.handle_final_transcript(state.session_id, {
            "turn_id": "first", "text": original, "asr_evidence": evidence,
            "term_candidates": [{"raw": "ri ác", "recovered": "React", "source": "phonetic_lexicon"}],
        }, state)
        assert prompts == ["ri ác"]
        assert events[-1]["type"] == "stream_interruption"
        assert committed == []
        events.clear()
        await manager.handle_final_transcript(state.session_id, {
            "turn_id": "repeat", "text": "React",
            "asr_evidence": {**evidence, "duration_sec": 1.0},
        }, state)
        assert events[-1]["type"] == "asr_gate_result"
        assert events[-1]["payload"]["transcript_safe"] is True
        assert committed[0][0] == "Em dùng React để xây giao diện và phối hợp nhóm."
        assert committed[0][1]["raw_transcript"] == original
        assert committed[0][1]["resolution_reason"] == "candidate_spoken_phrase_clarification"
        assert state.pending_answer_transcript == {}

    asyncio.run(exercise())
