from types import SimpleNamespace

import app.domains.interview.services.laya_controller as controller_module
from app.shared.contracts import (
    ASRGateAction,
    NextAction,
    StreamAction,
)


def test_missing_laya_weights_use_safe_local_fallback(monkeypatch):
    monkeypatch.setattr(
        controller_module,
        "get_settings",
        lambda: SimpleNamespace(
            laya_model_path="convaiinnovations/laya-multilingual",
            laya_model_revision="test-revision",
            laya_device="cpu",
            laya_enabled=True,
        ),
    )

    controller = controller_module.LayaController()

    assert controller.is_available is False
    assert controller.model_version == "local-deterministic-fallback-v1"
    assert controller.predict_streaming_decision(
        "answer", {}, [StreamAction.CONTINUE, StreamAction.END_TURN], None
    ).stream_action == StreamAction.CONTINUE
    asr = controller.predict_asr_gate_decision(
        "clear transcript", [], [ASRGateAction.ACCEPT_AS_IS, ASRGateAction.ASK_CONFIRMATION], None
    )
    assert asr.asr_gate_action == ASRGateAction.ASK_CONFIRMATION
    assert asr.transcript_safe is False
    assert controller.predict_turn_decision(
        None, {}, [NextAction.SAME_LEVEL]
    ).next_action == NextAction.SAME_LEVEL


def test_laya_typed_answers_are_mapped_to_existing_interview_contract(monkeypatch):
    monkeypatch.setattr(
        controller_module,
        "get_settings",
        lambda: SimpleNamespace(
            laya_model_path="convaiinnovations/laya-multilingual",
            laya_model_revision="test-revision",
            laya_device="cpu",
            laya_enabled=True,
        ),
    )
    controller = controller_module.LayaController()

    class FakeLayaAgent:
        def predict(self, state, questions):
            assert "Java Backend Intern" in state["text"]
            assert {"answer_intent", "next_action", "difficulty_action", "relevance", "escalate_to_strong_llm"} == set(questions)
            return {
                "answers": {
                    "answer_intent": {"choice": "direct_answer", "confidence": 0.9},
                    "next_action": {"choice": "probe", "confidence": 0.91},
                    "difficulty_action": {"choice": "increase", "confidence": 0.82},
                    "relevance": {"score": 3.5, "confidence": 0.8},
                    "escalate_to_strong_llm": {
                        "choice": "B",
                        "probabilities": {"A": 0.1, "B": 0.9},
                        "confidence": 0.9,
                    },
                }
            }

    controller.client = controller_module.LayaSystemOneClient(FakeLayaAgent())
    state = SimpleNamespace(
        role="Java Backend Intern",
        company_target="FPT Software",
        current_topic="technical_core",
        current_concept="Spring Boot REST API",
        remaining_scored_question_budget=5,
        current_question={},
    )

    result = controller.predict_turn_decision(state, {"payload": {"correctness": 0.9, "depth": 4}}, [NextAction.PROBE])

    assert result.next_action == NextAction.PROBE
    assert result.decision_confidence == 0.91
    assert result.difficulty_action.value == "increase"
    assert result.relevance == 0.875
    assert result.escalate_to_strong_llm is False
