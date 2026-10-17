"""Local Laya System-1 controller for typed interview decisions.

The multilingual weights are loaded from Hugging Face (then reused from the
local HF cache). If Laya cannot be loaded, the
controller degrades to deterministic policy fallbacks and never writes questions.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
from threading import RLock
from types import SimpleNamespace
from typing import Any, Optional

from app.shared.contracts import (
    LayaStreamingDecision, LayaASRGateDecision, LayaTurnDecision,
    StreamAction, ASRGateAction, NextAction, AnswerIntent,
    DifficultyAction, InterviewState, AdaptationMode,
)
from app.shared.config import get_settings

try:
    from laya import load as load_laya
    HAS_LAYA = True
except ImportError:
    load_laya = None
    HAS_LAYA = False

logger = logging.getLogger(__name__)


@dataclass
class Choice:
    instructions: str
    criteria: dict | list


@dataclass
class Noul:
    instructions: str


@dataclass
class Score:
    instructions: str
    criteria: list


class LayaSystemOneClient:
    """Small adapter preserving the old typed-decision call shape for Laya."""

    def __init__(self, agent: Any):
        self.agent = agent
        self._predict_lock = RLock()

    def system_one(self, *, model: str, state: str, questions: dict) -> SimpleNamespace:
        del model  # Laya's Agent is already bound to one checkpoint.
        laya_questions: dict[str, dict] = {}
        question_kinds: dict[str, str] = {}

        for key, question in questions.items():
            if isinstance(question, Choice):
                laya_questions[key] = {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": question.criteria,
                }
                question_kinds[key] = "choice"
            elif isinstance(question, Score):
                laya_questions[key] = {
                    "type": "score",
                    "instructions": question.instructions,
                    "criteria": question.criteria,
                }
                question_kinds[key] = "score"
            elif isinstance(question, Noul):
                # Laya's own model card recommends a neutral two-option choice
                # rather than its `noul` primitive for safety-sensitive gates.
                laya_questions[key] = {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": {
                        "A": "Yes / Có: the statement in the question is true.",
                        "B": "No / Không: the statement in the question is false.",
                    },
                }
                question_kinds[key] = "noul"
            else:
                raise TypeError(f"Unsupported Laya question type: {type(question).__name__}")

        with self._predict_lock:
            result = self.agent.predict({"text": state}, laya_questions)

        raw_answers = result.get("answers", {}) if isinstance(result, dict) else {}
        answers = {}
        for key, kind in question_kinds.items():
            raw = raw_answers.get(key, {})
            if not isinstance(raw, dict):
                raw = {}
            confidence = raw.get("confidence")
            if confidence is None:
                confidence = raw.get("answer_confidence", 0.0)

            if kind == "choice":
                answer = SimpleNamespace(choice=raw.get("choice"), confidence=float(confidence or 0.0))
            elif kind == "score":
                answer = SimpleNamespace(score=raw.get("score"), confidence=float(confidence or 0.0))
            else:
                probabilities = raw.get("probabilities", {})
                yes_probability = probabilities.get("A") if isinstance(probabilities, dict) else None
                if yes_probability is None:
                    yes_probability = 1.0 if raw.get("choice") == "A" else 0.0
                answer = SimpleNamespace(noul=float(yes_probability), confidence=float(confidence or 0.0))
            answers[key] = answer

        return SimpleNamespace(answers=answers, routing=result.get("routing", {}) if isinstance(result, dict) else {})


class LayaController:
    """
    Local Laya multilingual controller. Hard Policy remains authoritative and
    validates every returned action before execution.
    """

    def __init__(self):
        self.settings = get_settings()
        self.model_name = self.settings.laya_model_path or "convaiinnovations/laya-multilingual"
        self.model_revision = self.settings.laya_model_revision
        self.device = self.settings.laya_device or "cpu"
        self.enabled = self.settings.laya_enabled
        self.client: Optional[LayaSystemOneClient] = None
        self.model_version = "local-deterministic-fallback-v1"
        self.load_error: Optional[str] = None
        self._load_lock = RLock()

    def load_model(self) -> bool:
        """Load the pinned multilingual checkpoint once; weights stay in HF cache."""
        if not self.enabled:
            return False
        with self._load_lock:
            if self.client is not None:
                return True
            if not HAS_LAYA or load_laya is None:
                self.load_error = "Python package `laya` is not installed"
                logger.error("Laya decision model unavailable: %s", self.load_error)
                return False
            try:
                local_path = Path(self.model_name)
                revision = None if local_path.exists() else self.model_revision
                agent = load_laya(
                    self.model_name,
                    device=self.device,
                    revision=revision,
                    fast=self.settings.laya_fast,
                )
                self.client = LayaSystemOneClient(agent)
                revision_tag = f"@{self.model_revision[:12]}" if revision else "@local"
                self.model_version = f"{self.model_name}{revision_tag}"
                self.load_error = None
                logger.info("✅ Laya local decision model ready (%s, device=%s)", self.model_version, self.device)
                return True
            except Exception as exc:
                self.load_error = f"{type(exc).__name__}: {exc}"
                logger.exception("Laya model load failed; using deterministic decision fallback")
                self.client = None
                self.model_version = "local-deterministic-fallback-v1"
                return False

    @property
    def is_available(self) -> bool:
        """True only after the local Laya weights have loaded successfully."""
        return self.enabled and self.client is not None

    # ================================================================
    # §8.1 — Streaming Decision
    # ================================================================

    def predict_streaming_decision(
        self,
        partial_transcript: str,
        stream_features: dict,
        allowed_actions: list[StreamAction],
        state: InterviewState,
    ) -> LayaStreamingDecision:
        """
        Dự đoán streaming decision khi ứng viên đang nói.
        Nếu chỉ có 1 action hợp lệ hoặc thỏa mãn fast boundary rule -> trả về ngay.
        Nếu không -> chạy Laya local (với fallback).
        """
        if not self.is_available:
            return self._streaming_fallback(stream_features, allowed_actions)

        # 1. Fast path: nếu chỉ có 1 hành động duy nhất được phép
        if len(allowed_actions) == 1:
            return LayaStreamingDecision(
                stream_action=allowed_actions[0],
                stream_confidence=1.0,
            )

        duration = stream_features.get("duration_sec", 0)
        silence_ratio = stream_features.get("silence_ratio", 0)
        audio_ok = stream_features.get("audio_quality_ok", True)

        # 2. Fast audio quality / silence checks
        if not audio_ok and StreamAction.ASK_REPEAT in allowed_actions:
            return LayaStreamingDecision(
                stream_action=StreamAction.ASK_REPEAT,
                stream_confidence=0.98,
            )

        if silence_ratio > 0.75 and duration > 3.0 and StreamAction.END_TURN in allowed_actions:
            return LayaStreamingDecision(
                stream_action=StreamAction.END_TURN,
                stream_confidence=0.95,
            )

        # 3. Quá dài (>90s) và đang nói miên man -> AI_SOFT_INTERRUPT
        if duration > 90 and StreamAction.AI_SOFT_INTERRUPT in allowed_actions:
            word_count = len(partial_transcript.split())
            if word_count > 160:
                return LayaStreamingDecision(
                    stream_action=StreamAction.AI_SOFT_INTERRUPT,
                    stream_confidence=0.92,
                )

        # 4. Local Laya typed decision for the streaming context
        try:
            return self._laya_streaming_inference(
                partial_transcript, stream_features, allowed_actions, state
            )
        except Exception as e:
            logger.warning(f"Laya streaming decision failed, using fallback: {e}")
            return self._streaming_fallback(stream_features, allowed_actions)

    def _laya_streaming_inference(
        self,
        partial_transcript: str,
        stream_features: dict,
        allowed_actions: list[StreamAction],
        state: InterviewState,
    ) -> LayaStreamingDecision:
        """Run local Laya streaming inference."""
        criteria_map = {
            "CONTINUE": "Candidate is answering coherently and still speaking normally. Keep listening.",
            "WAIT_FOR_CANDIDATE": "Candidate explicitly asked for thinking time or said they are still formulating the answer. Keep the microphone open, do not commit the answer, and wait for them to continue or finish.",
            "AI_SOFT_INTERRUPT": "Candidate is rambling or repeating without value for >90s. Courteously intervene.",
            "CLARIFY_NOW": "Candidate's spoken meaning is ambiguous; interrupt politely and ask one short question to disambiguate, without evaluating or replacing the answer.",
            "ASK_REPEAT": "The recognized speech itself is unclear or corrupted; ask the candidate to repeat only the unclear part, preserving already understandable content.",
            "END_TURN": "Candidate has completed their response or stopped speaking.",
        }

        action_criteria = {
            a.value: criteria_map.get(a.value, f"Perform {a.value}")
            for a in allowed_actions
        }

        # Tránh gọi Laya nếu transcript quá ngắn (< 3 từ) -> CONTINUE
        if len(partial_transcript.strip().split()) < 3 and StreamAction.CONTINUE in allowed_actions:
            return LayaStreamingDecision(
                stream_action=StreamAction.CONTINUE,
                stream_confidence=0.99,
            )

        state_summary = (
            f"Candidate is speaking in response to concept: '{state.current_concept or 'General'}'. "
            f"Current duration: {stream_features.get('duration_sec', 0):.1f}s. "
            f"Original interview question: \"{(state.current_question or {}).get('question_text', '')[:500]}\". "
            f"Previously heard answer context: \"{getattr(state, 'candidate_answer_draft', '')[-500:]}\". "
            f"Latest partial transcript: \"{partial_transcript[-300:]}\""
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
            return LayaStreamingDecision(
                stream_action=StreamAction(ans.choice),
                stream_confidence=float(ans.confidence or 0.85),
            )

        return self._streaming_fallback(stream_features, allowed_actions)

    def _streaming_fallback(
        self,
        stream_features: dict,
        allowed_actions: list[StreamAction],
    ) -> LayaStreamingDecision:
        """Deterministic streaming fallback (§15)."""
        audio_ok = stream_features.get("audio_quality_ok", True)
        if not audio_ok and StreamAction.ASK_REPEAT in allowed_actions:
            return LayaStreamingDecision(
                stream_action=StreamAction.ASK_REPEAT,
                stream_confidence=1.0,
            )

        default_action = StreamAction.CONTINUE if StreamAction.CONTINUE in allowed_actions else allowed_actions[0]
        return LayaStreamingDecision(
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
    ) -> LayaASRGateDecision:
        """
        Predict the ASR Gate decision with local Laya. If unavailable or unsure,
        require the candidate to confirm the transcript before scoring.
        """
        if not self.is_available:
            return self._asr_gate_fallback(allowed_actions)

        try:
            return self._laya_asr_gate_inference(
                final_transcript, term_candidates, allowed_actions, state
            )
        except Exception as e:
            logger.warning(f"Laya ASR Gate prediction failed, using confirmation fallback: {e}")
            return self._asr_gate_fallback(allowed_actions)

    def _laya_asr_gate_inference(
        self,
        final_transcript: str,
        term_candidates: list[dict],
        allowed_actions: list[ASRGateAction],
        state: InterviewState,
    ) -> LayaASRGateDecision:
        """Run local Laya ASR gate inference and fail closed on uncertainty."""
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

        questions = {
            "is_safe": Noul(
                instructions="Is the final transcript coherent, understandable, and free from critical transcription noise?"
            ),
            "asr_gate_action": Choice(
                instructions="Decide the verification gate action for this ASR transcript",
                criteria=action_criteria,
            ),
        }
        proposed = [candidate for candidate in term_candidates if isinstance(candidate, dict)][:3]
        for index, candidate in enumerate(proposed):
            raw = str(candidate.get("raw") or candidate.get("original") or "")
            suggested = str(candidate.get("recovered") or candidate.get("suggested") or "")
            if raw and suggested:
                questions[f"term_choice_{index}"] = Choice(
                    instructions="Rank the two written readings using interview context only. No audio or calibrated ASR likelihood is supplied; never invent one.",
                    criteria={"A": f"Retain Qwen's literal words: {raw}",
                              "B": f"Possible alternative (not verified): {suggested}"},
                )

        resp = self.client.system_one(
            model=self.model_name,
            state=state_summary,
            questions=questions,
        )

        term_rankings = []
        for index, candidate in enumerate(proposed):
            answer = resp.answers.get(f"term_choice_{index}")
            term_rankings.append({
                "raw": candidate.get("raw") or candidate.get("original"),
                "suggested": candidate.get("recovered") or candidate.get("suggested"),
                "selected": "suggested" if answer and answer.choice == "B" else "raw",
                "model_choice_score_uncalibrated": float(answer.confidence or 0.0) if answer else 0.0,
                "basis": "text_context_only",
            })

        is_safe_ans = resp.answers.get("is_safe")
        safe_probability = float(is_safe_ans.noul) if is_safe_ans else 0.0
        is_safe = safe_probability >= 0.80

        gate_ans = resp.answers.get("asr_gate_action")
        if gate_ans and gate_ans.choice in [a.value for a in allowed_actions]:
            chosen_action = ASRGateAction(gate_ans.choice)
            confidence = float(gate_ans.confidence or 0.0)
        else:
            chosen_action = self._verification_action(allowed_actions)
            confidence = 0.0

        # This output contract does not carry an edited transcript, so a model
        # suggestion to correct wording can never silently alter or accept it.
        if chosen_action == ASRGateAction.ACCEPT_CORRECTION:
            is_safe = False
            chosen_action = self._verification_action(allowed_actions)
        elif not is_safe and chosen_action == ASRGateAction.ACCEPT_AS_IS:
            chosen_action = self._verification_action(allowed_actions)

        return LayaASRGateDecision(
            transcript_safe=is_safe and chosen_action == ASRGateAction.ACCEPT_AS_IS,
            asr_gate_action=chosen_action,
            asr_confidence=confidence,
            term_rankings=term_rankings,
        )

    def _asr_gate_fallback(
        self,
        allowed_actions: list[ASRGateAction],
    ) -> LayaASRGateDecision:
        """No model means no silent acceptance; request explicit confirmation."""
        action = self._verification_action(allowed_actions)
        return LayaASRGateDecision(
            transcript_safe=False,
            asr_gate_action=action,
            asr_confidence=0.0,
        )

    @staticmethod
    def _verification_action(allowed_actions: list[ASRGateAction]) -> ASRGateAction:
        if ASRGateAction.ASK_CONFIRMATION in allowed_actions:
            return ASRGateAction.ASK_CONFIRMATION
        if ASRGateAction.REQUEST_VERIFICATION in allowed_actions:
            return ASRGateAction.REQUEST_VERIFICATION
        return allowed_actions[0] if allowed_actions else ASRGateAction.ASK_CONFIRMATION

    # ================================================================
    # §8.3 — Turn Decision
    # ================================================================

    def predict_turn_decision(
        self,
        state: InterviewState,
        evaluation: dict | None,
        allowed_actions: list[NextAction],
    ) -> LayaTurnDecision:
        """
        Predict the next interview action from a verified answer, without scoring it.
        """
        if not self.is_available:
            return self._turn_fallback(state, allowed_actions)

        try:
            return self._laya_turn_inference(state, evaluation, allowed_actions)
        except Exception as e:
            logger.warning(f"Laya turn decision failed, using fallback: {e}")
            return self._turn_fallback(state, allowed_actions)

    def _laya_turn_inference(
        self,
        state: InterviewState,
        evaluation: dict | None,
        allowed_actions: list[NextAction],
    ) -> LayaTurnDecision:
        """Run local Laya turn-decision inference."""
        context = evaluation or {}
        current_question = state.current_question.get("question_text", "") if isinstance(state.current_question, dict) else ""
        question = str(context.get("question") or current_question)[:1200]
        candidate_answer = str(context.get("candidate_answer") or "")[:2400]

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
            f"Current question: {question}\n"
            f"Verified candidate answer: {candidate_answer}\n"
            "Choose how to continue the conversation from the verified answer and framework coverage. "
            "Do not assign or infer a rubric score in this decision.\n"
            f"Remaining interview question budget: {state.remaining_scored_question_budget}."
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
        diff_confidence = float(diff_ans.confidence or 0.0) if diff_ans else 0.0
        diff = (
            DifficultyAction(diff_ans.choice)
            if diff_ans and diff_confidence >= 0.45 and diff_ans.choice in [d.value for d in DifficultyAction]
            else DifficultyAction.MAINTAIN
        )

        rel_ans = resp.answers.get("relevance")
        relevance = float(rel_ans.score / 4.0) if rel_ans and rel_ans.score is not None else 0.85
        relevance = max(0.0, min(1.0, relevance))

        esc_ans = resp.answers.get("escalate_to_strong_llm")
        escalate = (esc_ans.noul >= 0.75) if esc_ans else False

        return LayaTurnDecision(
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
    ) -> LayaTurnDecision:
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

        return LayaTurnDecision(
            answer_intent=AnswerIntent.DIRECT_ANSWER,
            relevance=0.8,
            decision_confidence=1.0,
            next_action=next_action,
            difficulty_action=DifficultyAction.MAINTAIN,
            escalate_to_strong_llm=False,
        )


# Singleton instance
_laya_controller_instance: Optional[LayaController] = None


def get_laya_controller() -> LayaController:
    """Return the local Laya controller singleton."""
    global _laya_controller_instance
    if _laya_controller_instance is None:
        _laya_controller_instance = LayaController()
    return _laya_controller_instance


