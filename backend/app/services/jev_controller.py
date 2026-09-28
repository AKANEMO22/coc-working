"""
CÓC ĐI LÀM — TypeSafe AI Jev Controller (§8)
Mặt phẳng điều khiển System-1: phân loại, routing, ASR gating, quyết định hành động.
Thay thế Laya bằng TypeSafe AI Jev (https://typesafe.ai) với typed decisions token.

Jev chỉ sinh typed decision token trong schema tương ứng,
KHÔNG trực tiếp sinh câu chữ câu hỏi phỏng vấn.
"""

import logging
from typing import Optional
from app.models.schemas import (
    JevStreamingDecision, JevASRGateDecision, JevTurnDecision,
    StreamAction, ASRGateAction, NextAction, AnswerIntent,
    DifficultyAction, InterviewState, AdaptationMode,
)
from app.core.config import get_settings

try:
    from typesafe_sdk import TypeSafeClient, AsyncTypeSafeClient, Choice, Noul, Score
    HAS_TYPESAFE_SDK = True
except ImportError:
    HAS_TYPESAFE_SDK = False

logger = logging.getLogger(__name__)


class JevController:
    """
    Bộ điều khiển System-1 TypeSafe AI Jev.
    Gọi TypeSafe AI System-One API và dự đoán typed decisions.
    Có deterministic fallback (§15) khi API gặp sự cố hoặc timeout.
    """

    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.typesafe_api_key or ""
        self.model_name = self.settings.typesafe_model or "jev-latest"
        self.enabled = self.settings.typesafe_enabled
        self.model_version = f"typesafe-{self.model_name}"

        self.client: Optional[TypeSafeClient] = None
        self.async_client: Optional[AsyncTypeSafeClient] = None

        if self.is_available:
            try:
                self.client = TypeSafeClient(api_key=self.api_key)
                self.async_client = AsyncTypeSafeClient(api_key=self.api_key)
                logger.info(f"✅ TypeSafe AI Jev Controller initialized (model={self.model_name})")
            except Exception as e:
                logger.error(f"Failed to initialize TypeSafe AI client: {e}")

    @property
    def is_available(self) -> bool:
        """Kiểm tra TypeSafe AI Jev có sẵn sàng và có API key hay không."""
        return HAS_TYPESAFE_SDK and self.enabled and bool(self.api_key.strip())

    # ================================================================
    # §8.1 — Streaming Decision
    # ================================================================

    def predict_streaming_decision(
        self,
        partial_transcript: str,
        stream_features: dict,
        allowed_actions: list[StreamAction],
        state: InterviewState,
    ) -> JevStreamingDecision:
        """
        Dự đoán streaming decision khi ứng viên đang nói.
        Nếu chỉ có 1 action hợp lệ hoặc thỏa mãn fast boundary rule -> trả về ngay.
        Nếu không -> gọi Jev System-One API (với fallback).
        """
        if not self.is_available:
            return self._streaming_fallback(stream_features, allowed_actions)

        # 1. Fast path: nếu chỉ có 1 hành động duy nhất được phép
        if len(allowed_actions) == 1:
            return JevStreamingDecision(
                stream_action=allowed_actions[0],
                stream_confidence=1.0,
            )

        duration = stream_features.get("duration_sec", 0)
        silence_ratio = stream_features.get("silence_ratio", 0)
        audio_ok = stream_features.get("audio_quality_ok", True)

        # 2. Fast audio quality / silence checks
        if not audio_ok and StreamAction.ASK_REPEAT in allowed_actions:
            return JevStreamingDecision(
                stream_action=StreamAction.ASK_REPEAT,
                stream_confidence=0.98,
            )

        if silence_ratio > 0.75 and duration > 3.0 and StreamAction.END_TURN in allowed_actions:
            return JevStreamingDecision(
                stream_action=StreamAction.END_TURN,
                stream_confidence=0.95,
            )

        # 3. Quá dài (>90s) và đang nói miên man -> AI_SOFT_INTERRUPT
        if duration > 90 and StreamAction.AI_SOFT_INTERRUPT in allowed_actions:
            word_count = len(partial_transcript.split())
            if word_count > 160:
                return JevStreamingDecision(
                    stream_action=StreamAction.AI_SOFT_INTERRUPT,
                    stream_confidence=0.92,
                )

        # 4. Gọi TypeSafe AI Jev để phân loại ngữ cảnh streaming
        try:
            return self._jev_streaming_inference(
                partial_transcript, stream_features, allowed_actions, state
            )
        except Exception as e:
            logger.warning(f"TypeSafe Jev streaming call failed, using fallback: {e}")
            return self._streaming_fallback(stream_features, allowed_actions)

    def _jev_streaming_inference(
        self,
        partial_transcript: str,
        stream_features: dict,
        allowed_actions: list[StreamAction],
        state: InterviewState,
    ) -> JevStreamingDecision:
        """Thực hiện inference streaming qua TypeSafe AI Jev."""
        criteria_map = {
            "CONTINUE": "Candidate is answering coherently and still speaking normally. Keep listening.",
            "AI_SOFT_INTERRUPT": "Candidate is rambling or repeating without value for >90s. Courteously intervene.",
            "CLARIFY_NOW": "Candidate explicitly stopped to ask a clarifying question about the prompt.",
            "ASK_REPEAT": "Audio is corrupt or completely incomprehensible.",
            "END_TURN": "Candidate has completed their response or stopped speaking.",
        }

        action_criteria = {
            a.value: criteria_map.get(a.value, f"Perform {a.value}")
            for a in allowed_actions
        }

        # Tránh gọi Jev nếu transcript quá ngắn (< 3 từ) -> CONTINUE
        if len(partial_transcript.strip().split()) < 3 and StreamAction.CONTINUE in allowed_actions:
            return JevStreamingDecision(
                stream_action=StreamAction.CONTINUE,
                stream_confidence=0.99,
            )

        state_summary = (
            f"Candidate is speaking in response to concept: '{state.current_concept or 'General'}'. "
            f"Current duration: {stream_features.get('duration_sec', 0):.1f}s. "
            f"Partial transcript: \"{partial_transcript[-300:]}\""
        )

        resp = self.client.system_one(
            model=self.model_name,
            state=state_summary,
            questions={
                "stream_action": Choice(
                    instructions="Select the immediate turn streaming action for the interview audio pipeline",
                    criteria=action_criteria,
                )
            },
        )

        ans = resp.answers.get("stream_action")
        if ans and ans.choice in [a.value for a in allowed_actions]:
            return JevStreamingDecision(
                stream_action=StreamAction(ans.choice),
                stream_confidence=float(ans.confidence or 0.85),
            )

        return self._streaming_fallback(stream_features, allowed_actions)

    def _streaming_fallback(
        self,
        stream_features: dict,
        allowed_actions: list[StreamAction],
    ) -> JevStreamingDecision:
        """Deterministic streaming fallback (§15)."""
        audio_ok = stream_features.get("audio_quality_ok", True)
        if not audio_ok and StreamAction.ASK_REPEAT in allowed_actions:
            return JevStreamingDecision(
                stream_action=StreamAction.ASK_REPEAT,
                stream_confidence=1.0,
            )

        default_action = StreamAction.CONTINUE if StreamAction.CONTINUE in allowed_actions else allowed_actions[0]
        return JevStreamingDecision(
            stream_action=default_action,
            stream_confidence=1.0,
        )

    # ================================================================
    # §8.2 — ASR Gate Decision
    # ================================================================

    def predict_asr_gate_decision(
        self,
        final_transcript: str,
        term_candidates: list[dict],
        allowed_actions: list[ASRGateAction],
        state: InterviewState,
    ) -> JevASRGateDecision:
        """
        Dự đoán ASR Gate decision - xác minh Final Transcript qua TypeSafe AI Jev.
        Nếu Jev không khả dụng → deterministic user confirmation fallback.
        """
        if not self.is_available:
            return self._asr_gate_fallback(allowed_actions)

        try:
            return self._jev_asr_gate_inference(
                final_transcript, term_candidates, allowed_actions, state
            )
        except Exception as e:
            logger.warning(f"TypeSafe Jev ASR Gate prediction failed, using fallback: {e}")
            return self._asr_gate_fallback(allowed_actions)

    def _jev_asr_gate_inference(
        self,
        final_transcript: str,
        term_candidates: list[dict],
        allowed_actions: list[ASRGateAction],
        state: InterviewState,
    ) -> JevASRGateDecision:
        """ASR Gate inference using TypeSafe AI Jev."""
        criteria_map = {
            "ACCEPT_AS_IS": "Transcript is technically clear, grammatically sound, and safe without critical terms missing.",
            "ACCEPT_CORRECTION": "Transcript has recognized domain terms with high-confidence corrections.",
            "REQUEST_VERIFICATION": "Transcript contains ambiguous technical terms that need quick verification.",
            "ASK_CONFIRMATION": "Transcript is distorted, truncated, or highly doubtful; ask candidate to confirm.",
        }

        action_criteria = {
            a.value: criteria_map.get(a.value, f"Execute {a.value}")
            for a in allowed_actions
        }

        state_summary = (
            f"Topic: '{state.current_topic}'. Concept: '{state.current_concept}'.\n"
            f"Final Transcript: \"{final_transcript}\"\n"
            f"Term Candidates: {term_candidates}"
        )

        resp = self.client.system_one(
            model=self.model_name,
            state=state_summary,
            questions={
                "is_safe": Noul(
                    instructions="Is the final transcript coherent, understandable, and free from critical transcription noise?"
                ),
                "asr_gate_action": Choice(
                    instructions="Decide the verification gate action for this ASR transcript",
                    criteria=action_criteria,
                ),
            },
        )

        is_safe_ans = resp.answers.get("is_safe")
        is_safe = (is_safe_ans.noul >= 0.5) if is_safe_ans else True

        gate_ans = resp.answers.get("asr_gate_action")
        if gate_ans and gate_ans.choice in [a.value for a in allowed_actions]:
            chosen_action = ASRGateAction(gate_ans.choice)
            confidence = float(gate_ans.confidence or 0.85)
        else:
            chosen_action = allowed_actions[0]
            confidence = 0.7

        return JevASRGateDecision(
            transcript_safe=is_safe and chosen_action in [ASRGateAction.ACCEPT_AS_IS, ASRGateAction.ACCEPT_CORRECTION],
            asr_gate_action=chosen_action,
            asr_confidence=confidence,
        )

    def _asr_gate_fallback(
        self,
        allowed_actions: list[ASRGateAction],
    ) -> JevASRGateDecision:
        """Deterministic ASR Gate fallback (§15)."""
        action = ASRGateAction.ASK_CONFIRMATION if ASRGateAction.ASK_CONFIRMATION in allowed_actions else allowed_actions[0]
        return JevASRGateDecision(
            transcript_safe=False,
            asr_gate_action=action,
            asr_confidence=0.0,
        )

    # ================================================================
    # §8.3 — Turn Decision
    # ================================================================

    def predict_turn_decision(
        self,
        state: InterviewState,
        evaluation: dict,
        allowed_actions: list[NextAction],
    ) -> JevTurnDecision:
        """
        Dự đoán turn decision qua TypeSafe AI Jev - chọn bước phỏng vấn tiếp theo.
        Chỉ gọi SAU KHI đã có Verified Canonical Transcript + EvaluationEnvelope hợp lệ.
        """
        if not self.is_available:
            return self._turn_fallback(state, allowed_actions)

        try:
            return self._jev_turn_inference(state, evaluation, allowed_actions)
        except Exception as e:
            logger.warning(f"TypeSafe Jev Turn Decision failed, using fallback: {e}")
            return self._turn_fallback(state, allowed_actions)

    def _jev_turn_inference(
        self,
        state: InterviewState,
        evaluation: dict,
        allowed_actions: list[NextAction],
    ) -> JevTurnDecision:
        """Turn decision inference using TypeSafe AI Jev."""
        payload = evaluation.get("payload", {})
        correctness = float(payload.get("correctness", 0.5))
        depth = int(payload.get("depth", 2))
        feedback = payload.get("quick_feedback", "")

        intent_criteria = {
            "direct_answer": "Candidate gave a direct substantive answer to the question.",
            "clarification_question": "Candidate asked clarifying questions about requirements or definitions.",
            "give_up": "Candidate expressed inability to answer or gave up on this question.",
            "irrelevant": "Candidate response was completely off-topic.",
            "pause": "Candidate asked for extra thinking time or paused.",
        }

        action_criteria_all = {
            "probe": "Candidate gave a promising answer; probe deeper into technical details or edge cases.",
            "same_level": "Candidate answered acceptably; maintain current difficulty with another relevant question.",
            "harder": "Candidate demonstrated strong mastery and deep knowledge; progress to harder challenge.",
            "easier": "Candidate struggled or demonstrated gaps; provide an easier foundational question.",
            "switch_topic": "Current stage/topic is sufficiently covered; advance to the next technical topic.",
            "clarify_answer": "Candidate statement had ambiguities; request clarification of specific details.",
            "verify_reasoning": "Ask candidate to explain why they chose their architectural or technical approach.",
            "finish_topic": "Candidate finished this specific topic; wrap up stage.",
            "wrap_up": "Interview session is concluding; move to final closing phase.",
            "finish_interview": "All interview requirements satisfied; end session.",
        }

        action_criteria = {
            a.value: action_criteria_all.get(a.value, f"Execute {a.value}")
            for a in allowed_actions
        }

        state_summary = (
            f"Interview Role: {state.role}. Company Target: {state.company_target}.\n"
            f"Current Topic: {state.current_topic}. Concept: {state.current_concept}.\n"
            f"Evaluation: correctness={correctness:.2f}, depth={depth}/4.\n"
            f"Evaluator Feedback: {feedback}\n"
            f"Remaining Budget: {state.remaining_scored_question_budget} questions."
        )

        resp = self.client.system_one(
            model=self.model_name,
            state=state_summary,
            questions={
                "answer_intent": Choice(
                    instructions="Identify the candidate's primary answer intent",
                    criteria=intent_criteria,
                ),
                "next_action": Choice(
                    instructions="Select the next turn action from allowed policy actions",
                    criteria=action_criteria,
                ),
                "difficulty_action": Choice(
                    instructions="Adjust technical difficulty level",
                    criteria={
                        "increase": "Increase question difficulty.",
                        "maintain": "Keep current difficulty.",
                        "decrease": "Lower question difficulty.",
                    },
                ),
                "relevance": Score(
                    instructions="Score the relevance of candidate response to the target role",
                    criteria=["irrelevant", "poor", "acceptable", "good", "excellent"],
                ),
                "escalate_to_strong_llm": Noul(
                    instructions="Does this turn require strong LLM reasoning escalation due to complex architecture claims?"
                ),
            },
        )

        intent_ans = resp.answers.get("answer_intent")
        intent = AnswerIntent(intent_ans.choice) if (intent_ans and intent_ans.choice in [i.value for i in AnswerIntent]) else AnswerIntent.DIRECT_ANSWER

        action_ans = resp.answers.get("next_action")
        if action_ans and action_ans.choice in [a.value for a in allowed_actions]:
            next_act = NextAction(action_ans.choice)
            confidence = float(action_ans.confidence or 0.85)
        else:
            next_act = allowed_actions[0]
            confidence = 0.75

        diff_ans = resp.answers.get("difficulty_action")
        diff = DifficultyAction(diff_ans.choice) if (diff_ans and diff_ans.choice in [d.value for d in DifficultyAction]) else DifficultyAction.MAINTAIN

        rel_ans = resp.answers.get("relevance")
        relevance = float(rel_ans.score / 4.0) if rel_ans and rel_ans.score is not None else 0.85
        relevance = max(0.0, min(1.0, relevance))

        esc_ans = resp.answers.get("escalate_to_strong_llm")
        escalate = (esc_ans.noul >= 0.75) if esc_ans else False

        return JevTurnDecision(
            answer_intent=intent,
            relevance=relevance,
            decision_confidence=confidence,
            next_action=next_act,
            difficulty_action=diff,
            escalate_to_strong_llm=escalate,
        )

    def _turn_fallback(
        self,
        state: InterviewState,
        allowed_actions: list[NextAction],
    ) -> JevTurnDecision:
        """Deterministic Blueprint Turn Fallback (§15)."""
        priority_order = [
            NextAction.SAME_LEVEL,
            NextAction.SWITCH_TOPIC,
            NextAction.FINISH_TOPIC,
            NextAction.WRAP_UP,
            NextAction.FINISH_INTERVIEW,
        ]

        next_action = None
        for action in priority_order:
            if action in allowed_actions:
                next_action = action
                break

        if next_action is None:
            next_action = allowed_actions[0] if allowed_actions else NextAction.WRAP_UP

        return JevTurnDecision(
            answer_intent=AnswerIntent.DIRECT_ANSWER,
            relevance=0.8,
            decision_confidence=1.0,
            next_action=next_action,
            difficulty_action=DifficultyAction.MAINTAIN,
            escalate_to_strong_llm=False,
        )


# Singleton instance
_jev_controller_instance: Optional[JevController] = None


def get_jev_controller() -> JevController:
    """Lấy hoặc khởi tạo Jev Controller singleton."""
    global _jev_controller_instance
    if _jev_controller_instance is None:
        _jev_controller_instance = JevController()
    return _jev_controller_instance


# Backward compatibility aliases
get_laya_controller = get_jev_controller
LayaController = JevController
