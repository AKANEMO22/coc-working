"""The local ASR gate distinguishes clear speech from actual uncertainty."""

from app.domains.interview.services.hard_policy_engine import HardPolicyEngine
from app.shared.contracts import ASRGateAction, LayaASRGateDecision
from app.domains.interview.services.laya_controller import LayaController
from types import SimpleNamespace


ALLOWED = [ASRGateAction.ACCEPT_AS_IS, ASRGateAction.REQUEST_VERIFICATION, ASRGateAction.ASK_CONFIRMATION]
CLEAR = "Em dùng React để làm giao diện và phối hợp review code với nhóm."
EVIDENCE = {
    "source": "qwen_microphone", "duration_sec": 5.0,
    "rms": 0.055, "clipped_fraction": 0.0, "audio_quality_ok": True,
}


def uncertain_laya():
    # Reproduces the real multilingual checkpoint's tiny, uncalibrated score.
    return LayaASRGateDecision(
        transcript_safe=False, asr_gate_action=ASRGateAction.REQUEST_VERIFICATION,
        asr_confidence=0.0337,
    )


def test_clear_microphone_capture_is_not_repeated_only_due_to_laya_score():
    decision, reason = HardPolicyEngine().resolve_asr_evidence(uncertain_laya(), ALLOWED, CLEAR, EVIDENCE)
    assert reason == "clear_capture_uncalibrated_laya"
    assert decision.transcript_safe is True
    assert decision.asr_gate_action == ASRGateAction.ACCEPT_AS_IS


def test_poor_or_empty_capture_is_asked_again_automatically():
    policy = HardPolicyEngine()
    for transcript, evidence in [
        (CLEAR, {**EVIDENCE, "audio_quality_ok": False}),
        ("", EVIDENCE),
        ("Em làm cái ... React hay red ...", EVIDENCE),
    ]:
        decision, reason = policy.resolve_asr_evidence(uncertain_laya(), ALLOWED, transcript, evidence)
        assert reason == "capture_or_transcript_unclear"
        assert decision.transcript_safe is False
        assert decision.asr_gate_action in {ASRGateAction.REQUEST_VERIFICATION, ASRGateAction.ASK_CONFIRMATION}


def test_critical_term_conflict_cannot_be_overridden_by_clear_audio():
    decision, reason = HardPolicyEngine().resolve_asr_evidence(
        uncertain_laya(), [ASRGateAction.REQUEST_VERIFICATION, ASRGateAction.ASK_CONFIRMATION], CLEAR, EVIDENCE
    )
    assert reason == "critical_term_disagreement"
    assert decision.transcript_safe is False


def test_high_confidence_laya_request_is_preserved():
    decision = LayaASRGateDecision(
        transcript_safe=False, asr_gate_action=ASRGateAction.REQUEST_VERIFICATION,
        asr_confidence=0.91,
    )
    resolved, reason = HardPolicyEngine().resolve_asr_evidence(decision, ALLOWED, CLEAR, EVIDENCE)
    assert reason == "laya_high_confidence_verification"
    assert resolved.transcript_safe is False


def test_dictionary_suggestion_is_not_silent_correction_or_fake_probability():
    decision, reason = HardPolicyEngine().resolve_asr_evidence(
        uncertain_laya(), ALLOWED,
        "Em có dùng ri ác cho dự án giao diện gần đây.", EVIDENCE,
        [{"raw": "ri ác", "recovered": "React", "source": "phonetic_lexicon"}],
    )
    assert reason == "unresolved_term_candidates"
    assert decision.transcript_safe is False
    assert decision.asr_gate_action == ASRGateAction.REQUEST_VERIFICATION


def test_laya_ranks_written_candidates_but_does_not_claim_audio_probability():
    controller = LayaController()

    class FakeClient:
        def system_one(self, *, model, state, questions):
            assert "term_choice_0" in questions
            assert "ri ác" in questions["term_choice_0"].criteria["A"]
            return SimpleNamespace(answers={
                "is_safe": SimpleNamespace(noul=0.02),
                "asr_gate_action": SimpleNamespace(choice="REQUEST_VERIFICATION", confidence=0.4),
                "term_choice_0": SimpleNamespace(choice="B", confidence=0.61),
            })

    controller.client = FakeClient()
    state = SimpleNamespace(current_topic="technical", current_concept="UI")
    decision = controller._laya_asr_gate_inference(
        "Em dùng ri ác cho giao diện.",
        [{"raw": "ri ác", "recovered": "React", "source": "phonetic_lexicon"}],
        ALLOWED, state,
    )
    assert decision.term_rankings == [{
        "raw": "ri ác", "suggested": "React", "selected": "suggested",
        "model_choice_score_uncalibrated": 0.61, "basis": "text_context_only",
    }]
    assert decision.transcript_safe is False
