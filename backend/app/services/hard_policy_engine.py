"""
CÓC ĐI LÀM — Hard Policy Engine (§10)
Mã nguồn bằng code thuần túy luôn có quyền lực tối cao hơn tất cả các mô hình AI.

Ranh giới vai trò:
- Hard Policy Engine = constraint/validator: tạo tập hành động hợp lệ theo đúng giai đoạn.
- Jev (TypeSafe AI) = decision selector: chỉ được chọn một action nằm trong tập tương ứng.
"""

from app.models.schemas import (
    StreamAction, ASRGateAction, NextAction,
    InterviewState, SessionStatus, AdaptationMode,
    JevStreamingDecision, JevASRGateDecision, JevTurnDecision,
    LayaStreamingDecision, LayaASRGateDecision, LayaTurnDecision,
    EvaluationEnvelope,
)
from app.core.config import get_settings
import logging

logger = logging.getLogger(__name__)

# Danh sách thuật ngữ nhạy cảm TUYỆT ĐỐI không tự sửa ngầm (§5.2)
CRITICAL_TERM_PAIRS = [
    ("can", "can't"),
    ("sync", "async"),
    ("mutable", "immutable"),
    ("authentication", "authorization"),
    ("INNER JOIN", "LEFT JOIN"),
    ("fine-tuning", "file tuning"),
    # Kinh tế (§20.2)
    ("B2B", "B2C"),
    ("CAC", "LTV"),
    ("ROI", "ROE"),
    ("KPI", "OKR"),
    ("Conversion Rate", "Click-through Rate"),
    ("Cash Flow", "Profit Margin"),
    ("Top-line", "Bottom-line"),
    ("Inbound", "Outbound"),
]


class HardPolicyEngine:
    """
    Bộ chính sách cứng bất di bất dịch (§10).
    Tạo tập action hợp lệ cho từng phase:
    - Streaming → allowed_stream_actions
    - ASR Gate → allowed_asr_actions
    - Turn → allowed_turn_actions
    """

    def __init__(self):
        settings = get_settings()
        self.policy_version = settings.policy_version

        # Cấu hình thresholds
        self.min_time_for_new_question = 60  # giây
        self.max_questions_per_concept = 3
        self.soft_interrupt_min_confidence = 0.85
        self.min_speech_duration_for_interrupt = 5  # giây, không ngắt khi mới nói 1-2 từ

    # ================================================================
    # STREAMING PHASE — allowed_stream_actions (§10)
    # ================================================================

    def compute_allowed_stream_actions(
        self,
        state: InterviewState,
        partial_duration_sec: float = 0.0,
        audio_quality_ok: bool = True,
    ) -> list[StreamAction]:
        """
        Tính tập hành động streaming hợp lệ.
        Chỉ áp dụng khi ứng viên đang nói (partial transcript).
        """
        allowed = [StreamAction.CONTINUE]

        # Luôn cho phép END_TURN (timer/VAD rule tất định)
        allowed.append(StreamAction.END_TURN)

        # ASK_REPEAT: audio quality không ổn
        if not audio_quality_ok:
            allowed.append(StreamAction.ASK_REPEAT)

        # AI_SOFT_INTERRUPT: chỉ khi đã nói đủ lâu
        if partial_duration_sec >= self.min_speech_duration_for_interrupt:
            allowed.append(StreamAction.AI_SOFT_INTERRUPT)
            allowed.append(StreamAction.CLARIFY_NOW)

        # Nếu phiên đang FINALIZING → chỉ END_TURN
        if state.status == SessionStatus.FINALIZING:
            return [StreamAction.END_TURN]

        return allowed

    def validate_stream_decision(
        self,
        decision: LayaStreamingDecision,
        allowed_actions: list[StreamAction],
    ) -> LayaStreamingDecision:
        """
        Hậu kiểm streaming decision.
        Nếu action không nằm trong allowed → fallback CONTINUE.
        """
        if decision.stream_action not in allowed_actions:
            logger.warning(
                f"Policy violation: stream_action={decision.stream_action} "
                f"not in allowed={allowed_actions}. Falling back to CONTINUE."
            )
            return LayaStreamingDecision(
                stream_action=StreamAction.CONTINUE,
                stream_confidence=1.0,
            )

        # AI_SOFT_INTERRUPT yêu cầu confidence >= threshold
        if (
            decision.stream_action == StreamAction.AI_SOFT_INTERRUPT
            and decision.stream_confidence < self.soft_interrupt_min_confidence
        ):
            logger.info(
                f"AI_SOFT_INTERRUPT blocked: confidence {decision.stream_confidence} "
                f"< threshold {self.soft_interrupt_min_confidence}"
            )
            return LayaStreamingDecision(
                stream_action=StreamAction.CONTINUE,
                stream_confidence=decision.stream_confidence,
            )

        return decision

    # ================================================================
    # ASR GATE PHASE — allowed_asr_actions (§10)
    # ================================================================

    def compute_allowed_asr_actions(
        self,
        state: InterviewState,
        has_critical_term_disagreement: bool = False,
        term_candidates: list[dict] | None = None,
    ) -> list[ASRGateAction]:
        """
        Tính tập hành động ASR Gate hợp lệ.
        Critical ASR disagreement → chỉ REQUEST_VERIFICATION / ASK_CONFIRMATION.
        """
        # Kiểm tra bất đồng thuật ngữ trọng yếu (§5.2)
        if has_critical_term_disagreement or self._detect_critical_disagreement(term_candidates):
            logger.info("Critical ASR disagreement detected → restricting to verification actions only")
            return [ASRGateAction.REQUEST_VERIFICATION, ASRGateAction.ASK_CONFIRMATION]

        # Bình thường: cho phép tất cả
        return [
            ASRGateAction.ACCEPT_AS_IS,
            ASRGateAction.ACCEPT_CORRECTION,
            ASRGateAction.REQUEST_VERIFICATION,
            ASRGateAction.ASK_CONFIRMATION,
        ]

    def validate_asr_decision(
        self,
        decision: LayaASRGateDecision,
        allowed_actions: list[ASRGateAction],
    ) -> LayaASRGateDecision:
        """Hậu kiểm ASR Gate decision."""
        if decision.asr_gate_action not in allowed_actions:
            logger.warning(
                f"Policy violation: asr_gate_action={decision.asr_gate_action} "
                f"not in allowed={allowed_actions}. Forcing ASK_CONFIRMATION."
            )
            return LayaASRGateDecision(
                transcript_safe=False,
                asr_gate_action=ASRGateAction.ASK_CONFIRMATION,
                asr_confidence=decision.asr_confidence,
            )
        return decision

    def _detect_critical_disagreement(self, term_candidates: list[dict] | None) -> bool:
        """Phát hiện bất đồng thuật ngữ trọng yếu từ term candidates."""
        if not term_candidates:
            return False

        for candidate in term_candidates:
            if isinstance(candidate, dict):
                original = candidate.get("original", "").lower()
                suggested = candidate.get("suggested", "").lower()
            elif isinstance(candidate, str):
                original = candidate.lower()
                suggested = ""
            else:
                continue

            for pair in CRITICAL_TERM_PAIRS:
                term_a, term_b = pair[0].lower(), pair[1].lower()
                if (
                    (original == term_a and suggested == term_b)
                    or (original == term_b and suggested == term_a)
                ):
                    logger.warning(
                        f"Critical term pair detected: '{original}' ↔ '{suggested}'"
                    )
                    return True

        return False

    # ================================================================
    # TURN PHASE — allowed_turn_actions (§10)
    # ================================================================

    def compute_allowed_turn_actions(
        self,
        state: InterviewState,
        evaluation: EvaluationEnvelope | None = None,
    ) -> list[NextAction]:
        """
        Tính tập hành động turn hợp lệ.
        Quy tắc cứng bất di bất dịch:
        1. time < 60s → chỉ wrap_up / finish_interview
        2. transcript_safe == false → cấm tất cả (không vào đây)
        3. questions_on_current_concept >= 3 → loại probe
        4. Question budget hết → loại các action sinh scored question
        5. PENDING_EVALUATION → chỉ deterministic Blueprint
        """
        # === Rule 1: Time constraint ===
        if state.time_remaining_sec < self.min_time_for_new_question:
            logger.info(f"Time remaining {state.time_remaining_sec}s < {self.min_time_for_new_question}s → wrap_up/finish only")
            return [NextAction.WRAP_UP, NextAction.FINISH_INTERVIEW]

        # === Rule: PENDING_EVALUATION → deterministic only ===
        if state.pending_evaluation_count > 0 or state.adaptation_mode == AdaptationMode.DEGRADED_BLUEPRINT:
            logger.info("PENDING_EVALUATION or DEGRADED_BLUEPRINT → deterministic progression only")
            # Cho phép các action không cần evidence
            return [
                NextAction.SAME_LEVEL,
                NextAction.SWITCH_TOPIC,
                NextAction.FINISH_TOPIC,
                NextAction.WRAP_UP,
                NextAction.FINISH_INTERVIEW,
            ]

        # === Build full action set ===
        allowed = [
            NextAction.PROBE,
            NextAction.SAME_LEVEL,
            NextAction.HARDER,
            NextAction.EASIER,
            NextAction.SWITCH_TOPIC,
            NextAction.CLARIFY_ANSWER,
            NextAction.VERIFY_REASONING,
            NextAction.FINISH_TOPIC,
            NextAction.WRAP_UP,
            NextAction.FINISH_INTERVIEW,
        ]

        # === Rule 3: Probe limit ===
        if state.questions_on_current_concept >= self.max_questions_per_concept:
            logger.info(f"Probe limit reached ({state.questions_on_current_concept} >= {self.max_questions_per_concept})")
            allowed = [a for a in allowed if a != NextAction.PROBE]

        # === Rule 4: Question budget ===
        if state.remaining_scored_question_budget <= 0:
            logger.info("Question budget exhausted → removing scored question actions")
            scored_actions = {
                NextAction.PROBE,
                NextAction.SAME_LEVEL,
                NextAction.HARDER,
                NextAction.EASIER,
            }
            allowed = [a for a in allowed if a not in scored_actions]

        # Đảm bảo luôn có wrap_up và finish_interview
        for required in [NextAction.WRAP_UP, NextAction.FINISH_INTERVIEW]:
            if required not in allowed:
                allowed.append(required)

        return allowed

    def validate_turn_decision(
        self,
        decision: LayaTurnDecision,
        allowed_actions: list[NextAction],
        state: InterviewState,
    ) -> LayaTurnDecision:
        """
        Hậu kiểm turn decision.
        finish_interview → FINALIZING, không gọi Question Service.
        """
        if decision.next_action not in allowed_actions:
            logger.warning(
                f"Policy violation: next_action={decision.next_action} "
                f"not in allowed={allowed_actions}. Falling back to SAME_LEVEL."
            )
            fallback_action = NextAction.SAME_LEVEL
            if NextAction.SAME_LEVEL not in allowed_actions:
                fallback_action = allowed_actions[0] if allowed_actions else NextAction.WRAP_UP

            return LayaTurnDecision(
                answer_intent=decision.answer_intent,
                relevance=decision.relevance,
                decision_confidence=1.0,
                next_action=fallback_action,
            )

        return decision

    # ================================================================
    # SCORING GATE (§10)
    # ================================================================

    def can_evaluate(self, transcript_safe: bool) -> bool:
        """
        Scoring gate: transcript_safe == false → cấm Evidence Evaluator,
        cấm cập nhật skill_estimates, cấm Long-Term Memory.
        """
        if not transcript_safe:
            logger.warning("Scoring gate blocked: transcript_safe=false")
        return transcript_safe

    def can_create_turn_decision(
        self,
        has_valid_evaluation: bool,
        state: InterviewState,
    ) -> bool:
        """
        Evaluation-before-adaptation: adaptive LayaTurnDecision chỉ tồn tại
        khi turn hiện tại đã có EvaluationEnvelope hợp lệ (§16 invariant 7).
        """
        if not has_valid_evaluation:
            logger.info("Cannot create adaptive turn decision: no valid evaluation")
            return False
        return True

    def can_generate_report(self, state: InterviewState) -> bool:
        """
        Final report is evidence-complete: không phát hành nếu còn
        scored turn PENDING_EVALUATION (§16 invariant 9).
        """
        if state.pending_evaluation_count > 0:
            logger.info(
                f"Cannot generate final report: {state.pending_evaluation_count} "
                f"turns still PENDING_EVALUATION"
            )
            return False
        return True

    def should_finish_interview(self, state: InterviewState) -> bool:
        """Kiểm tra điều kiện tự động kết thúc phỏng vấn."""
        if state.time_remaining_sec <= 0:
            return True
        if state.remaining_scored_question_budget <= 0 and state.status == SessionStatus.IN_PROGRESS:
            return True
        return False


# Singleton instance
_engine_instance: HardPolicyEngine | None = None


def get_hard_policy_engine() -> HardPolicyEngine:
    """Get or create Hard Policy Engine singleton."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = HardPolicyEngine()
    return _engine_instance
