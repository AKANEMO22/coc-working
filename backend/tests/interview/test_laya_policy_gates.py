from app.domains.interview.services.hard_policy_engine import HardPolicyEngine
from app.shared.contracts import (
    AnswerIntent,
    DifficultyAction,
    InterviewState,
    LayaTurnDecision,
    NextAction,
)


def _state(remaining_budget: int) -> InterviewState:
    return InterviewState(
        session_id="laya-policy-test",
        candidate_name="Candidate",
        student_id="STUDENT_TEST",
        role="Java Backend Intern",
        company_target="FPT Software",
        remaining_scored_question_budget=remaining_budget,
    )


def test_laya_cannot_finish_before_scored_question_budget_is_exhausted():
    policy = HardPolicyEngine()
    state = _state(remaining_budget=3)
    allowed = policy.compute_allowed_turn_actions(state)

    assert NextAction.FINISH_INTERVIEW not in allowed
    assert NextAction.WRAP_UP not in allowed
    model_decision = LayaTurnDecision(
        answer_intent=AnswerIntent.DIRECT_ANSWER,
        relevance=0.9,
        decision_confidence=0.99,
        next_action=NextAction.FINISH_INTERVIEW,
        difficulty_action=DifficultyAction.MAINTAIN,
    )
    validated = policy.validate_turn_decision(model_decision, allowed, state)
    assert validated.next_action == NextAction.SAME_LEVEL


def test_wrap_up_is_forbidden_while_multiple_scored_questions_remain():
    state = _state(remaining_budget=2)
    state.current_topic = "applied_scenario"
    allowed = HardPolicyEngine().compute_allowed_turn_actions(state)
    assert NextAction.WRAP_UP not in allowed
    assert NextAction.FINISH_INTERVIEW not in allowed


def test_wrap_up_is_required_after_budget_is_exhausted():
    allowed = HardPolicyEngine().compute_allowed_turn_actions(_state(remaining_budget=0))
    assert allowed == [NextAction.WRAP_UP]


def test_answering_wrap_up_can_only_finish_even_with_budget_remaining():
    policy = HardPolicyEngine()
    state = _state(remaining_budget=2)
    state.current_topic = "wrap_up"
    state.current_question = {"stage_name": "wrap_up", "question_text": "Bạn có câu hỏi nào?"}
    allowed = policy.compute_allowed_turn_actions(state)
    assert allowed == [NextAction.FINISH_INTERVIEW]

    model_decision = LayaTurnDecision(
        answer_intent=AnswerIntent.DIRECT_ANSWER,
        relevance=0.8,
        decision_confidence=0.8,
        next_action=NextAction.SWITCH_TOPIC,
    )
    assert policy.validate_turn_decision(model_decision, allowed, state).next_action == NextAction.FINISH_INTERVIEW
