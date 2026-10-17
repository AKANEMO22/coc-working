"""
CÓC ĐI LÀM — Hard Policy Engine (§10)
Mã nguồn bằng code thuần túy luôn có quyền lực tối cao hơn tất cả các mô hình AI.

Ranh giới vai trò:
- Hard Policy Engine = constraint/validator: tạo tập hành động hợp lệ theo đúng giai đoạn.
- Laya = typed decision selector: chỉ được chọn một action nằm trong tập tương ứng.
"""

from app.shared.contracts import (
    StreamAction, ASRGateAction, NextAction,
    InterviewState, SessionStatus, AdaptationMode,
    LayaStreamingDecision, LayaASRGateDecision, LayaTurnDecision,
    EvaluationEnvelope,
)
from app.shared.config import get_settings
import logging
import math
import re

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
        self.min_speech_duration_for_interrupt = 20  # dài hơn mới được phép ngắt vì nói lan man
        self.min_speech_duration_for_clarification = 1.5

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

        # Clarification/repeat can be offered early, but only after enough
        # speech to give Laya useful context. A pause by itself is never an
        # interruption signal.
        if partial_duration_sec >= self.min_speech_duration_for_clarification:
            allowed.append(StreamAction.WAIT_FOR_CANDIDATE)
            allowed.append(StreamAction.CLARIFY_NOW)
            allowed.append(StreamAction.ASK_REPEAT)

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

        if decision.stream_action in {StreamAction.WAIT_FOR_CANDIDATE, StreamAction.CLARIFY_NOW, StreamAction.ASK_REPEAT} and decision.stream_confidence < 0.85:
            logger.info("Low-confidence streaming clarification blocked; keep listening")
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

    def resolve_asr_evidence(
        self,
        decision: LayaASRGateDecision,
        allowed_actions: list[ASRGateAction],
        transcript: str,
        evidence: dict | None,
        term_candidates: list[dict] | None = None,
    ) -> tuple[LayaASRGateDecision, str]:
        """Calibrate Laya's uncalibrated choice score against capture evidence.

        Laya's raw choice confidence is not an ASR probability: a clear local
        Vietnamese sample can score below 0.05. Never use that number alone to
        require an extra spoken turn, and never auto-accept critical term
        disagreements, poor audio, or visibly broken transcripts.
        """
        if not isinstance(evidence, dict) or evidence.get("source") != "qwen_microphone":
            return decision, "legacy_or_text_input"
        if ASRGateAction.ACCEPT_AS_IS not in allowed_actions:
            return decision, "critical_term_disagreement"
        if term_candidates:
            # A lexicon proposal alone has no calibrated acoustic probability.
            # Do not silently replace the candidate's technical words.
            return LayaASRGateDecision(
                transcript_safe=False,
                asr_gate_action=ASRGateAction.REQUEST_VERIFICATION,
                asr_confidence=decision.asr_confidence,
                term_rankings=decision.term_rankings,
            ), "unresolved_term_candidates"
        audio_ok = self.capture_audio_ok(evidence)
        words = re.findall(r"\w+", transcript, flags=re.UNICODE)
        text_ok = (
            len(words) >= 5
            and len(transcript.strip()) >= 18
            and not any(marker in transcript for marker in ("...", "…", "�", "???"))
        )
        if not audio_ok or not text_ok:
            verify_action = (
                ASRGateAction.ASK_CONFIRMATION if ASRGateAction.ASK_CONFIRMATION in allowed_actions
                else ASRGateAction.REQUEST_VERIFICATION
            )
            return LayaASRGateDecision(
                transcript_safe=False,
                asr_gate_action=verify_action,
                asr_confidence=decision.asr_confidence,
                term_rankings=decision.term_rankings,
            ), "capture_or_transcript_unclear"
        if decision.transcript_safe:
            return decision, "laya_accept"
        if decision.asr_confidence >= 0.80:
            return decision, "laya_high_confidence_verification"
        # The capture is intelligible and Laya is uncertain rather than
        # confidently disagreeing. Accept this turn to avoid a repeat loop.
        return LayaASRGateDecision(
            transcript_safe=True,
            asr_gate_action=ASRGateAction.ACCEPT_AS_IS,
            asr_confidence=0.0,  # No calibrated ASR probability is available.
            term_rankings=decision.term_rankings,
        ), "clear_capture_uncalibrated_laya"

    @staticmethod
    def capture_audio_ok(evidence: dict | None) -> bool:
        if not isinstance(evidence, dict) or evidence.get("source") != "qwen_microphone":
            return False
        try:
            duration = float(evidence.get("duration_sec", 0))
            rms = float(evidence.get("rms", 0))
            clipped = float(evidence.get("clipped_fraction", 1))
        except (TypeError, ValueError):
            duration, rms, clipped = 0.0, 0.0, 1.0
        return (
            evidence.get("audio_quality_ok") is True
            and all(math.isfinite(value) for value in (duration, rms, clipped))
            and duration >= 0.5 and 0.008 <= rms <= 0.6
            and 0 <= clipped < 0.12
        )

    def _detect_critical_disagreement(self, term_candidates: list[dict] | None) -> bool:
        """Phát hiện bất đồng thuật ngữ trọng yếu từ term candidates."""
        if not term_candidates:
            return False

        for candidate in term_candidates:
            if isinstance(candidate, dict):
                original = (
                    candidate.get("original")
                    or candidate.get("raw")
                    or ""
                ).lower()
                suggested = (
                    candidate.get("suggested")
                    or candidate.get("recovered")
                    or ""
                ).lower()
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
        1. time < 60s → wrap_up; after wrap_up → finish_interview
        2. transcript_safe == false → cấm tất cả (không vào đây)
        3. questions_on_current_concept >= 3 → loại probe
        4. Question budget hết → loại các action sinh scored question
        5. Legacy DEGRADED/PENDING states → chỉ deterministic Blueprint progression.
           The current live flow does not create per-answer rubric jobs.
        """
        # A wrap-up invitation is the terminal question. Once answered, only
        # finish the interview; never jump back to a technical stage.
        if state.current_topic == "wrap_up" or (state.current_question or {}).get("stage_name") == "wrap_up":
            return [NextAction.FINISH_INTERVIEW]

        if state.remaining_scored_question_budget <= 0:
            return [NextAction.WRAP_UP]

        # === Rule 1: Time constraint ===
        if state.time_remaining_sec < self.min_time_for_new_question:
            logger.info(f"Time remaining {state.time_remaining_sec}s < {self.min_time_for_new_question}s → wrap_up only")
            return [NextAction.WRAP_UP]

        # === Rule: PENDING_EVALUATION → deterministic only ===
        if state.pending_evaluation_count > 0 or state.adaptation_mode == AdaptationMode.DEGRADED_BLUEPRINT:
            logger.info("PENDING_EVALUATION or DEGRADED_BLUEPRINT → deterministic progression only")
            # Cho phép các action không cần evidence
            allowed = [
                NextAction.SAME_LEVEL,
                NextAction.SWITCH_TOPIC,
                NextAction.FINISH_TOPIC,
            ]
            return allowed

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
        ]

        # === Rule 3: Probe limit ===
        if state.questions_on_current_concept >= self.max_questions_per_concept:
            logger.info(f"Probe limit reached ({state.questions_on_current_concept} >= {self.max_questions_per_concept})")
            allowed = [a for a in allowed if a != NextAction.PROBE]

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

    def can_create_turn_decision(self, has_verified_answer: bool, state: InterviewState) -> bool:
        """Only a verified, committed answer may advance the live interview."""
        if not has_verified_answer or state.pending_stream_interruption:
            logger.info("Cannot advance before the answer is verified and committed")
            return False
        return state.status == SessionStatus.IN_PROGRESS

    def can_generate_report(self, state: InterviewState) -> bool:
        """A final rubric/report is forbidden while the live interview is active."""
        if state.status not in {SessionStatus.FINALIZING, SessionStatus.COMPLETED}:
            logger.info("Cannot generate final report before the interview ends")
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
