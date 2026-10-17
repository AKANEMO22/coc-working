"""
CÓC ĐI LÀM — WebSocket Interview Turn Manager (§4)
Quản lý luồng streaming WebSocket turn-by-turn.
Luồng trực tiếp: Streaming/Laya → làm rõ nếu cần → ASR Gate → chọn câu tiếp.
Rubric chỉ chạy khi phiên đã kết thúc.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
from app.shared.contracts import (
    WSMessageType, InterviewState,
    LayaASRGateDecision, LayaTurnDecision,
    SessionStatus, EventType, ASRGateAction, StreamAction,
    InterviewBlueprint, NextAction, Question,
)
from app.domains.interview.services.hard_policy_engine import get_hard_policy_engine
from app.domains.interview.services.laya_controller import get_laya_controller
from app.domains.interview.services.questions import get_question_service
from app.domains.interview.services.decision_audit import get_decision_audit
from app.domains.interview.services.reverse_interview_service import get_reverse_interview_service
from app.shared.infrastructure.redis import RedisSessionManager
from app.shared.config import get_settings
from app.shared.observability.activity import interview_logger
from app.shared.observability.traffic import record_traffic_event
from app.domains.interview.services.guidance import QuestionGenerationUnavailable, normalized_text
import json
import logging
import re
import uuid
import time
from difflib import SequenceMatcher
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()


class TrafficTrackedWebSocket(WebSocket):
    """WebSocket adapter that records envelope metadata, never message values."""

    def __init__(self, websocket: WebSocket, session_id: str):
        super().__init__(websocket.scope, websocket.receive, websocket.send)
        self.session_id = session_id

    async def accept(self, *args, **kwargs):
        await super().accept(*args, **kwargs)
        record_traffic_event(
            kind="websocket",
            direction="connection",
            name="WebSocket connected",
            path="/ws/interview/{session_id}",
            session_id=self.session_id,
        )

    async def receive_json(self, *args, **kwargs):
        message = await super().receive_json(*args, **kwargs)
        message_type = message.get("type", "unknown") if isinstance(message, dict) else "unknown"
        record_traffic_event(
            kind="websocket",
            direction="Browser → API",
            name=f"WS receive: {message_type}",
            path="/ws/interview/{session_id}",
            session_id=self.session_id,
            message_type=str(message_type)[:80],
            payload=message.get("payload") if isinstance(message, dict) else None,
        )
        return message

    async def send_json(self, data, mode="text"):
        await super().send_json(data, mode=mode)
        message_type = data.get("type", "unknown") if isinstance(data, dict) else "unknown"
        record_traffic_event(
            kind="websocket",
            direction="API → Browser",
            name=f"WS send: {message_type}",
            path="/ws/interview/{session_id}",
            session_id=self.session_id,
            message_type=str(message_type)[:80],
            payload=data.get("payload") if isinstance(data, dict) else None,
        )


class InterviewWebSocketManager:
    """
    Quản lý WebSocket cho phiên phỏng vấn realtime.
    Thực thi pipeline Streaming → ASR Gate → Evaluation → Turn Decision
    với Laya local typed-decision controller và Hard Policy.
    """

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.policy = get_hard_policy_engine()
        self.laya = get_laya_controller()
        self.settings = get_settings()
        self.question_service = get_question_service()
        self.audit = get_decision_audit()
        self.reverse_service = get_reverse_interview_service()
        self._evaluating_sessions: set[str] = set()
        self._question_generation_timings: dict[str, float] = {}
        self._opening_locks: dict[str, asyncio.Lock] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Kết nối WebSocket mới."""
        await websocket.accept()
        previous = self.active_connections.get(session_id)
        self.active_connections[session_id] = websocket
        if previous is not None and previous is not websocket:
            try:
                await previous.close(code=4001, reason="Interview reconnected")
            except Exception:
                pass
        logger.info(f"WebSocket connected: session={session_id}")

    def disconnect(self, session_id: str, websocket: WebSocket | None = None):
        """Ngắt kết nối."""
        # A reconnect may already have installed a newer socket. Closing the
        # previous socket must not remove that replacement from the registry.
        if websocket is None or self.active_connections.get(session_id) is websocket:
            self.active_connections.pop(session_id, None)
        logger.info(f"WebSocket disconnected: session={session_id}")

    async def send_message(self, session_id: str, message: dict):
        """Gửi message tới client."""
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_json(message)

    async def _send_generation_error(self, session_id: str, error: QuestionGenerationUnavailable, latency_ms: float | None = None):
        await self.send_message(session_id, {
            "type": WSMessageType.ERROR.value,
            "payload": {"message": str(error), "code": "QUESTION_GENERATION_UNAVAILABLE", "retryable": True},
        })
        interview_logger.add_log(
            stage="QUESTION_GENERATION_ERROR",
            message=str(error),
            session_id=session_id,
            details={"latency_ms": latency_ms} if latency_ms is not None else None,
        )

    async def _deliver_question(self, session_id: str, state: InterviewState, question: Question):
        generation_latency_ms = self._question_generation_timings.pop(session_id, None)
        if question.stage_name:
            state.current_topic = question.stage_name
        state.current_question = question.model_dump(mode="json")
        state.pending_question_request = {}
        if question.question_text not in state.asked_question_texts:
            state.asked_question_texts.append(question.question_text)
        RedisSessionManager().set_hot_state(session_id, state.model_dump())
        await self.send_message(session_id, {"type": WSMessageType.STATE_SYNC.value, "payload": state.model_dump()})
        await self.send_message(session_id, {
            "type": WSMessageType.QUESTION_TEXT.value,
            "turn_id": f"turn_{uuid.uuid4().hex[:8]}", "payload": question.model_dump(),
        })
        interview_logger.add_log(
            stage="QUESTION_ENGINE", message="Model generated a question from framework/CV/JD guidance",
            session_id=session_id,
            details={"question_id": question.question_id, "stage_name": question.stage_name,
                     "question_text": question.question_text, "provenance": question.provenance.model_dump(mode="json"),
                     "generation_latency_ms": generation_latency_ms},
        )

    async def _generate_next_question(
        self, session_id: str, state: InterviewState, blueprint: InterviewBlueprint | None,
        next_action: NextAction, evaluation: dict | None, last_question: str, candidate_answer: str,
    ) -> Question | None:
        request = {"next_action": next_action.value, "evaluation": evaluation,
                   "last_question": last_question, "candidate_answer": candidate_answer}
        generation_started = time.perf_counter()
        try:
            question = await self.question_service.get_next_question(
                next_action, state, blueprint, evaluation=evaluation,
                last_question=last_question, candidate_answer=candidate_answer,
            )
            state.pending_question_request = {}
            self._question_generation_timings[session_id] = round((time.perf_counter() - generation_started) * 1000, 1)
            return question
        except QuestionGenerationUnavailable as error:
            generation_latency_ms = round((time.perf_counter() - generation_started) * 1000, 1)
            self._question_generation_timings[session_id] = generation_latency_ms
            state.pending_question_request = request
            RedisSessionManager().set_hot_state(session_id, state.model_dump())
            await self._send_generation_error(session_id, error, generation_latency_ms)
            return None

    async def open_or_resume_question(self, session_id: str, state: InterviewState, blueprint: InterviewBlueprint) -> InterviewState:
        # React StrictMode and reconnects can create two sockets almost at
        # once. Serialize the opening and re-read durable state under the lock.
        lock = self._opening_locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            fresh = RedisSessionManager().get_hot_state(session_id)
            if fresh:
                refreshed = InterviewState(**fresh)
                for field_name in InterviewState.model_fields:
                    setattr(state, field_name, getattr(refreshed, field_name))
            if state.current_question and not state.pending_question_request:
                await self.send_message(session_id, {"type": WSMessageType.STATE_SYNC.value, "payload": state.model_dump()})
                await self.send_message(session_id, {
                    "type": WSMessageType.QUESTION_TEXT.value,
                    "turn_id": f"turn_{uuid.uuid4().hex[:8]}",
                    "payload": state.current_question,
                })
                interview_logger.add_log(
                    stage="QUESTION_REPLAY", message="Replayed the current question after reconnect",
                    session_id=session_id,
                    details={"question_id": state.current_question.get("question_id")},
                )
                return state
            if state.pending_question_request and not state.pending_question_request.get("opening"):
                await self.retry_pending_question(session_id, state, blueprint)
                return state
            generation_started = time.perf_counter()
            try:
                question = await self.question_service.get_opening_question(state, blueprint)
                self._question_generation_timings[session_id] = round((time.perf_counter() - generation_started) * 1000, 1)
                await self._deliver_question(session_id, state, question)
            except QuestionGenerationUnavailable as error:
                generation_latency_ms = round((time.perf_counter() - generation_started) * 1000, 1)
                self._question_generation_timings[session_id] = generation_latency_ms
                state.pending_question_request = {"opening": True}
                RedisSessionManager().set_hot_state(session_id, state.model_dump())
                await self.send_message(session_id, {"type": WSMessageType.STATE_SYNC.value, "payload": state.model_dump()})
                await self._send_generation_error(session_id, error, generation_latency_ms)
            return state

    async def retry_pending_question(self, session_id: str, state: InterviewState, blueprint: InterviewBlueprint):
        if session_id in self._evaluating_sessions:
            return
        pending = dict(state.pending_question_request)
        self._evaluating_sessions.add(session_id)
        try:
            if not pending or pending.get("opening"):
                await self.open_or_resume_question(session_id, state, blueprint)
            else:
                question = await self._generate_next_question(
                    session_id, state, blueprint, NextAction(pending["next_action"]),
                    pending.get("evaluation"), pending.get("last_question", ""), pending.get("candidate_answer", ""),
                )
                if question:
                    await self._deliver_question(session_id, state, question)
        finally:
            self._evaluating_sessions.discard(session_id)

    # ================================================================
    # STREAMING PHASE (§4.1 — user đang nói)
    # ================================================================

    async def handle_partial_transcript(
        self,
        session_id: str,
        payload: dict,
        state: InterviewState,
    ):
        """Xử lý partial transcript khi ứng viên đang nói."""
        if state.pending_stream_interruption or state.status != SessionStatus.IN_PROGRESS:
            return
        turn_id = payload.get("turn_id", f"turn_{uuid.uuid4().hex[:8]}")
        partial_text = str(payload.get("text", "")).strip()
        if not partial_text:
            return
        stream_features = payload.get("features", {})
        if not isinstance(stream_features, dict):
            stream_features = {}
        now = time.time()
        if partial_text == state.last_stream_decision_text or now - state.last_stream_decision_at < 0.65:
            return
        state.last_stream_decision_text = partial_text
        state.last_stream_decision_at = now

        # 1. Hard Policy tạo allowed_stream_actions
        allowed = self.policy.compute_allowed_stream_actions(
            state=state,
            partial_duration_sec=stream_features.get("duration_sec", 0),
            audio_quality_ok=stream_features.get("audio_quality_ok", True),
        )

        # 2. Controller Streaming Decision (hoặc deterministic local fallback)
        decision_started = time.perf_counter()
        decision_timed_out = False
        try:
            decision = await asyncio.wait_for(
                asyncio.to_thread(
                    self.laya.predict_streaming_decision,
                    partial_text,
                    stream_features,
                    allowed,
                    state,
                ),
                timeout=self.settings.laya_decision_timeout_sec,
            )
        except asyncio.TimeoutError:
            decision_timed_out = True
            decision = self.laya._streaming_fallback(stream_features, allowed)
        decision_latency_ms = round((time.perf_counter() - decision_started) * 1000, 1)

        # 3. Hard Policy hậu kiểm
        decision = self.policy.validate_stream_decision(decision, allowed)

        action = decision.stream_action
        interview_logger.add_log(
            stage="LAYA_STREAM_DECISION",
            message=f"Laya streaming action: {action.value}.",
            session_id=session_id,
            turn_id=turn_id,
            details={"action": action.value, "latency_ms": decision_latency_ms, "timed_out": decision_timed_out},
        )
        self.audit.create_audit_record(
            event_type=EventType.LAYA_STREAM_DECISION,
            session_id=session_id,
            turn_id=turn_id,
            model_version=self.laya.model_version if self.laya.is_available else "deterministic_fallback",
            confidence=decision.stream_confidence,
            input_refs=[f"partial:{turn_id}"],
        )
        if action == StreamAction.WAIT_FOR_CANDIDATE:
            interview_logger.add_log(
                stage="CANDIDATE_PAUSE_DETECTED",
                message="Laya xác nhận ứng viên đang suy nghĩ; giữ mic mở và chưa chốt answer.",
                session_id=session_id,
                turn_id=turn_id,
                details={"action": action.value, "confidence": decision.stream_confidence, "latency_ms": decision_latency_ms},
            )
            await self.send_message(session_id, {
                "type": WSMessageType.STREAM_DECISION.value,
                "turn_id": turn_id,
                "payload": {"action": action.value, "confidence": decision.stream_confidence},
            })
            return

        if action in {StreamAction.CLARIFY_NOW, StreamAction.ASK_REPEAT, StreamAction.AI_SOFT_INTERRUPT}:
            decision_id = f"interrupt_{uuid.uuid4().hex[:12]}"
            state.pending_stream_interruption = {
                "decision_id": decision_id,
                "action": action.value,
                "transcript_preview": partial_text,
                "created_at": time.time(),
            }
            interview_logger.add_log(
                stage="STREAM_CLARIFICATION_DECISION",
                message=f"Laya đề nghị ngắt lời để {action.value.lower()} (confidence={decision.stream_confidence:.2f})",
                session_id=session_id,
                turn_id=turn_id,
                details={"action": action.value, "confidence": decision.stream_confidence, "decision_id": decision_id, "latency_ms": decision_latency_ms},
            )
            await self.send_message(session_id, {
                "type": WSMessageType.STREAM_DECISION.value,
                "turn_id": turn_id,
                "payload": {"action": action.value, "confidence": decision.stream_confidence, "decision_id": decision_id},
            })
            return

        # Gửi kết quả về client
        await self.send_message(session_id, {
            "type": WSMessageType.STREAM_DECISION.value,
            "turn_id": turn_id,
            "payload": {"action": action.value, "confidence": decision.stream_confidence},
        })

    @staticmethod
    def _append_answer_segment(existing: str, new_segment: str) -> str:
        """Join separate speech transcripts without duplicating repeated overlap."""
        old = " ".join((existing or "").split()).strip()
        new = " ".join((new_segment or "").split()).strip()
        if not old:
            return new
        if not new or old.casefold().endswith(new.casefold()):
            return old
        if new.casefold().startswith(old.casefold()):
            return new
        old_words, new_words = old.split(), new.split()
        max_overlap = min(len(old_words), len(new_words), 40)
        for count in range(max_overlap, 0, -1):
            if [w.casefold() for w in old_words[-count:]] == [w.casefold() for w in new_words[:count]]:
                return " ".join(old_words + new_words[count:]).strip()
        return f"{old} {new}".strip()

    async def handle_stream_segment(self, session_id: str, payload: dict, state: InterviewState):
        """Checkpoint a cut-off speech segment, ask dynamically, then resume the same answer."""
        pending = state.pending_stream_interruption
        decision_id = str(payload.get("decision_id", ""))
        if not pending or decision_id != pending.get("decision_id"):
            return

        segment = str(payload.get("text", "")).strip() or str(pending.get("transcript_preview", "")).strip()
        state.candidate_answer_draft = self._append_answer_segment(state.candidate_answer_draft, segment)
        action = str(pending.get("action", ""))
        state.pending_stream_interruption = {}
        redis = RedisSessionManager()
        redis.set_hot_state(session_id, state.model_dump())

        blueprint_data = redis.get_blueprint(session_id)
        blueprint = InterviewBlueprint(**blueprint_data) if blueprint_data else None
        generation_started = time.perf_counter()
        utterance = await self.question_service.generate_interruption_dialogue(action, state, blueprint) if blueprint else None
        generation_latency_ms = round((time.perf_counter() - generation_started) * 1000, 1)
        if not utterance:
            await self.send_message(session_id, {
                "type": WSMessageType.STREAM_INTERRUPTION_CANCELLED.value,
                "payload": {"decision_id": decision_id, "reason": "Không tạo được lời hỏi làm rõ; câu trả lời đã được giữ lại."},
            })
            interview_logger.add_log(
                stage="STREAM_CLARIFICATION_UNAVAILABLE",
                message="Orchestrator chưa tạo được lời hỏi; giữ bản nháp và tiếp tục lắng nghe, không chấm điểm.",
                session_id=session_id,
                details={"decision_id": decision_id, "action": action, "generation_latency_ms": generation_latency_ms},
            )
            return

        await self.send_message(session_id, {
            "type": WSMessageType.STREAM_INTERRUPTION.value,
            "turn_id": decision_id,
            "payload": {"decision_id": decision_id, "action": action, "utterance": utterance},
        })
        interview_logger.add_log(
            stage="STREAM_CLARIFICATION_DELIVERED",
            message="Orchestrator generated one contextual clarification; original answer remains open.",
            session_id=session_id,
            details={"decision_id": decision_id, "action": action, "utterance": utterance, "generation_latency_ms": generation_latency_ms},
        )

    # ================================================================
    # ASR GATE PHASE (§4.1 — sau Final Transcript)
    # ================================================================

    async def handle_final_transcript(
        self,
        session_id: str,
        payload: dict,
        state: InterviewState,
    ):
        """Xử lý Final Transcript qua ASR Gate."""
        if state.pending_question_request or not state.current_question:
            await self._send_generation_error(session_id, QuestionGenerationUnavailable())
            return
        if session_id in self._evaluating_sessions:
            logger.warning(f"Session {session_id} is already evaluating an answer. Dropping duplicate turn request.")
            return

        self._evaluating_sessions.add(session_id)
        try:
            pending_confirmation = dict(state.pending_answer_transcript)
            incoming_text = str(payload.get("text", "")).strip()
            retry_context = pending_confirmation if pending_confirmation.get("retry_requested") else {}
            draft_before_retry = str(retry_context.get("draft_before_retry", state.candidate_answer_draft))
            if payload.get("verified", False) and pending_confirmation:
                turn_id = payload.get("turn_id") or pending_confirmation.get("turn_id") or f"turn_{uuid.uuid4().hex[:8]}"
                final_text = str(payload.get("text") or pending_confirmation.get("text") or "").strip()
                state.pending_answer_transcript = {}
            else:
                turn_id = payload.get("turn_id", f"turn_{uuid.uuid4().hex[:8]}")
                pending_stream = state.pending_stream_interruption
                if pending_stream and payload.get("stream_interruption_id") == pending_stream.get("decision_id"):
                    await self.handle_stream_segment(session_id, {
                        "decision_id": payload.get("stream_interruption_id"), "text": incoming_text,
                    }, state)
                    return
                # A final answer can race with a stale mid-speech recommendation.
                # In that case, commit it as the answer and ignore the recommendation.
                state.pending_stream_interruption = {}
                # A short clarification belongs to the same answer. Preserve
                # the already-understood text and replace only the phrase
                # that the interviewer asked about.
                if retry_context and len(incoming_text.split()) <= 5:
                    prior_text = str(retry_context.get("text", ""))
                    phrase = str(retry_context.get("unclear_phrase", ""))
                    if phrase and re.search(re.escape(phrase), prior_text, flags=re.IGNORECASE):
                        final_text = re.sub(re.escape(phrase), lambda _match: incoming_text,
                                            prior_text, count=1, flags=re.IGNORECASE)
                    else:
                        final_text = self._append_answer_segment(prior_text, incoming_text)
                else:
                    final_text = self._append_answer_segment(draft_before_retry, incoming_text)
            term_candidates = payload.get("term_candidates", [])
            word_count = len(final_text.strip().split()) if final_text.strip() else 0

            # 0. Log CANDIDATE_INPUT
            interview_logger.add_log(
                stage="CANDIDATE_INPUT",
                message=f"Nhận câu trả lời từ ứng viên ({word_count} từ): \"{final_text[:120]}{'...' if len(final_text) > 120 else ''}\"",
                session_id=session_id,
                turn_id=turn_id,
                details={
                    "final_transcript": final_text,
                    "word_count": word_count,
                    "term_candidates": term_candidates,
                    "verified": payload.get("verified", False),
                },
            )

            # 1. Hard Policy tạo allowed_asr_actions
            has_critical = self.policy._detect_critical_disagreement(term_candidates)
            allowed = self.policy.compute_allowed_asr_actions(
                state=state,
                has_critical_term_disagreement=has_critical,
                term_candidates=term_candidates,
            )

            # A user's explicit confirmation is authoritative. Otherwise use
            # Laya, requiring confirmation when its transcript decision is unsure.
            evidence = payload.get("asr_evidence")
            unclear_capture = (
                isinstance(evidence, dict)
                and evidence.get("source") == "qwen_microphone"
                and (not incoming_text or evidence.get("audio_quality_ok") is not True)
            )
            if payload.get("verified", False):
                decision = LayaASRGateDecision(
                    transcript_safe=True,
                    asr_gate_action=ASRGateAction.ACCEPT_AS_IS,
                    asr_confidence=1.0,
                )
                allowed = [ASRGateAction.ACCEPT_AS_IS]
                asr_latency_ms = 0.0
                asr_timed_out = False
            elif unclear_capture:
                # Do not spend two seconds on Laya when Qwen returned no
                # intelligible text or the microphone capture was poor.
                decision = self.laya._asr_gate_fallback(allowed)
                asr_latency_ms = 0.0
                asr_timed_out = False
            else:
                asr_started = time.perf_counter()
                asr_timed_out = False
                try:
                    decision = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.laya.predict_asr_gate_decision,
                            final_text,
                            term_candidates,
                            allowed,
                            state,
                        ),
                        timeout=self.settings.laya_decision_timeout_sec,
                    )
                except asyncio.TimeoutError:
                    asr_timed_out = True
                    decision = self.laya._asr_gate_fallback(allowed)
                asr_latency_ms = round((time.perf_counter() - asr_started) * 1000, 1)

            # 3. Hard Policy hậu kiểm
            decision = self.policy.validate_asr_decision(decision, allowed)
            decision, evidence_reason = self.policy.resolve_asr_evidence(
                decision, allowed, incoming_text, payload.get("asr_evidence"), term_candidates
            )
            if (retry_context and retry_context.get("unclear_phrase") and incoming_text
                    and len(incoming_text.split()) <= 5 and not has_critical
                    and self.policy.capture_audio_ok(payload.get("asr_evidence"))):
                # Candidate explicitly restated the requested phrase. This is
                # a new audio capture, not a lexicon guess or manual click.
                decision = LayaASRGateDecision(
                    transcript_safe=True, asr_gate_action=ASRGateAction.ACCEPT_AS_IS,
                    asr_confidence=0.0, term_rankings=decision.term_rankings,
                )
                evidence_reason = "candidate_spoken_phrase_clarification"
            if retry_context and not has_critical and len(incoming_text.split()) >= 5 and evidence_reason != "capture_or_transcript_unclear":
                previous_fragment = str(retry_context.get("unverified_fragment", ""))
                similarity = SequenceMatcher(
                    None, normalized_text(previous_fragment).split(), normalized_text(incoming_text).split()
                ).ratio() if previous_fragment else 0.0
                if similarity >= 0.78:
                    # Two independent captures agree. Accept the repeated
                    # fragment instead of forcing a manual confirmation.
                    decision = LayaASRGateDecision(
                        transcript_safe=True,
                        asr_gate_action=ASRGateAction.ACCEPT_AS_IS,
                        asr_confidence=0.0,  # Similarity is not acoustic confidence.
                    )
                    interview_logger.add_log(
                        stage="ASR_REPEAT_CONSENSUS",
                        message="Repeated speech agrees with the earlier capture.",
                        session_id=session_id, turn_id=turn_id,
                        details={"similarity": round(similarity, 3)},
                    )

            # Log ASR_GATE
            raw_action = getattr(decision, "asr_gate_action", getattr(decision, "asr_action", "ACCEPT_AS_IS"))
            action_val = raw_action.value if hasattr(raw_action, "value") else str(raw_action)
            interview_logger.add_log(
                stage="ASR_GATE",
                message=f"ASR Gate: safe={decision.transcript_safe}, action={action_val}, basis={evidence_reason}; score chưa hiệu chuẩn={decision.asr_confidence:.2f}",
                session_id=session_id,
                turn_id=turn_id,
                details={
                    "transcript_safe": decision.transcript_safe,
                    "confidence": decision.asr_confidence,
                    "action": action_val,
                    "has_critical_disagreement": has_critical,
                    "decision_latency_ms": asr_latency_ms,
                    "timed_out": asr_timed_out,
                    "evidence_reason": evidence_reason,
                    "raw_transcript": incoming_text,
                    "term_candidates": term_candidates,
                    "term_rankings": decision.term_rankings,
                },
            )

            # 4. Audit
            self.audit.create_audit_record(
                event_type=EventType.LAYA_ASR_DECISION,
                session_id=session_id,
                turn_id=turn_id,
                model_version=(
                    "user_confirmed" if payload.get("verified", False)
                    else self.laya.model_version if self.laya.is_available
                    else "deterministic_fallback"
                ),
                confidence=decision.asr_confidence,
                input_refs=[f"final_transcript:{turn_id}"],
            )

            # 5. Gửi kết quả về client
            await self.send_message(session_id, {
                "type": WSMessageType.ASR_GATE_RESULT.value,
                "turn_id": turn_id,
                "payload": decision.model_dump(),
            })

            # 6. Commit only a safe transcript. Unclear speech triggers a
            # model-written, spoken repeat request without a confirmation click.
            if decision.transcript_safe or payload.get("verified", False):
                asr_audit = {
                    "raw_transcript": str(retry_context.get("text", incoming_text)),
                    "resolved_transcript": final_text,
                    "term_candidates": retry_context.get("term_candidates", term_candidates),
                    "term_rankings": retry_context.get("term_rankings", decision.term_rankings),
                    "resolution_reason": evidence_reason,
                }
                interview_logger.add_log(
                    stage="ASR_RESOLUTION", message="Committed the same answer after ASR verification.",
                    session_id=session_id, turn_id=turn_id, details=asr_audit,
                )
                state.pending_answer_transcript = {}
                state.candidate_answer_draft = ""
                await self._advance_conversation_after_answer(
                    session_id, turn_id, final_text, state, asr_audit=asr_audit
                )
            else:
                retry_count = int(retry_context.get("retry_count", 0)) + 1
                state.pending_answer_transcript = {
                    "turn_id": turn_id,
                    "text": final_text,
                    "unverified_fragment": incoming_text,
                    "draft_before_retry": draft_before_retry,
                    "retry_count": retry_count,
                    "retry_requested": True,
                    "unclear_phrase": next((str(item.get("raw", "")) for item in term_candidates
                                             if isinstance(item, dict) and item.get("raw")),
                                            str(retry_context.get("unclear_phrase", ""))),
                    "term_candidates": term_candidates or retry_context.get("term_candidates", []),
                    "term_rankings": decision.term_rankings or retry_context.get("term_rankings", []),
                }
                state.candidate_answer_draft = ""
                blueprint_data = RedisSessionManager().get_blueprint(session_id)
                blueprint = InterviewBlueprint(**blueprint_data) if blueprint_data else None
                guidance_state = state.model_copy(deep=True)
                guidance_state.candidate_answer_draft = final_text
                utterance = None
                if blueprint:
                    for _ in range(2):
                        utterance = await self.question_service.generate_interruption_dialogue(
                            StreamAction.ASK_REPEAT.value, guidance_state, blueprint,
                            unclear_phrase=", ".join(str(item.get("raw", "")) for item in term_candidates if isinstance(item, dict))[:160],
                        )
                        if utterance:
                            break
                decision_id = f"asr_repeat_{uuid.uuid4().hex[:10]}"
                if utterance:
                    await self.send_message(session_id, {
                        "type": WSMessageType.STREAM_INTERRUPTION.value,
                        "turn_id": decision_id,
                        "payload": {"decision_id": decision_id, "action": StreamAction.ASK_REPEAT.value,
                                    "utterance": utterance, "retry_count": retry_count},
                    })
                    interview_logger.add_log(
                        stage="ASR_AUTO_REPROMPT", message="Orchestrator asked candidate to repeat unclear speech.",
                        session_id=session_id, turn_id=turn_id,
                        details={"retry_count": retry_count, "decision_id": decision_id},
                    )
                else:
                    await self.send_message(session_id, {
                        "type": WSMessageType.STREAM_INTERRUPTION_CANCELLED.value,
                        "payload": {"decision_id": decision_id,
                                    "reason": "Chưa tạo được lời hỏi lại; micro sẽ tiếp tục nghe câu trả lời."},
                    })
                    interview_logger.add_log(
                        stage="ASR_REPROMPT_UNAVAILABLE", message="Gemini did not produce a spoken repeat request.",
                        session_id=session_id, turn_id=turn_id,
                        details={"retry_count": retry_count},
                    )
        finally:
            self._evaluating_sessions.discard(session_id)

    async def _advance_conversation_after_answer(
        self, session_id: str, turn_id: str, verified_transcript: str, state: InterviewState,
        *, asr_audit: dict | None = None,
    ) -> None:
        """Persist a verified answer and choose the next question without rubric scoring."""
        redis = RedisSessionManager()
        question = str((state.current_question or {}).get("question_text", ""))
        rubric_type = str((state.current_question or {}).get("rubric_type", "technical_correctness"))
        stage_name = str((state.current_question or {}).get("stage_name") or state.current_topic or "technical_core")
        if not any(answer.get("turn_id") == turn_id for answer in state.committed_answers):
            state.committed_answers.append({
                "turn_id": turn_id,
                "stage": stage_name,
                "rubric_type": rubric_type,
                "concept": state.current_concept,
                "question": question,
                "candidate_answer": verified_transcript,
                "asr_audit": asr_audit or {},
                "committed_at": datetime.utcnow().isoformat(),
            })
        else:
            return
        state.remaining_scored_question_budget = max(0, state.remaining_scored_question_budget - 1)
        state.last_stream_decision_text = ""
        state.last_stream_decision_at = 0.0
        blueprint = redis.get_blueprint(session_id)
        if not blueprint:
            await self._send_generation_error(session_id, QuestionGenerationUnavailable())
            return

        answer_started = time.perf_counter()
        allowed_turn = self.policy.compute_allowed_turn_actions(state)
        context = {"question": question, "candidate_answer": verified_transcript}
        laya_started = time.perf_counter()
        laya_timed_out = False
        try:
            decision = await asyncio.wait_for(
                asyncio.to_thread(self.laya.predict_turn_decision, state, context, allowed_turn),
                timeout=self.settings.laya_decision_timeout_sec,
            )
        except asyncio.TimeoutError:
            laya_timed_out = True
            decision = self.laya._turn_fallback(state, allowed_turn)
        laya_latency_ms = round((time.perf_counter() - laya_started) * 1000, 1)
        decision = self.policy.validate_turn_decision(decision, allowed_turn, state)
        action = decision.next_action.value
        interview_logger.add_log(
            stage="LIVE_ORCHESTRATION",
            message=f"Laya chọn {action} từ transcript đã xác nhận; chưa chạy rubric.",
            session_id=session_id,
            turn_id=turn_id,
            details={"next_action": action, "confidence": decision.decision_confidence, "laya_latency_ms": laya_latency_ms, "laya_timed_out": laya_timed_out},
        )
        self.audit.create_audit_record(
            event_type=EventType.LAYA_TURN_DECISION,
            session_id=session_id,
            turn_id=turn_id,
            model_version=self.laya.model_version if self.laya.is_available else "deterministic_fallback",
            confidence=decision.decision_confidence,
            input_refs=[f"verified_transcript:{turn_id}"],
        )
        previous_question_id = (state.current_question or {}).get("question_id")
        await self._execute_turn_action(
            session_id=session_id,
            decision=decision,
            state=state,
            blueprint=blueprint,
            evaluation_data=None,
            turn_id=turn_id,
            last_question=question,
            candidate_answer=verified_transcript,
            prev_stage=stage_name,
        )
        interview_logger.add_log(
            stage="ANSWER_TO_NEXT_QUESTION",
            message="Thời gian từ khi nhận câu trả lời đã xác nhận tới khi xong điều phối/sinh câu tiếp.",
            session_id=session_id,
            turn_id=turn_id,
            details={
                "latency_ms": round((time.perf_counter() - answer_started) * 1000, 1),
                "laya_latency_ms": laya_latency_ms,
                "laya_timed_out": laya_timed_out,
                "question_delivered": (state.current_question or {}).get("question_id") != previous_question_id,
            },
        )
        redis.set_hot_state(session_id, state.model_dump())

    # ================================================================
    # EVALUATION + TURN DECISION PHASE
    # ================================================================

    async def _execute_turn_action(
        self, session_id: str, decision: LayaTurnDecision, state: InterviewState,
        blueprint: dict | None, evaluation_data: dict | None = None, turn_id: str = "",
        last_question: str = "", candidate_answer: str = "", prev_stage: str = "",
    ):
        action = decision.next_action.value
        if action == "finish_interview":
            state.status = SessionStatus.FINALIZING
            RedisSessionManager().set_hot_state(session_id, state.model_dump())
            await self.send_message(session_id, {
                "type": WSMessageType.SESSION_ENDED.value,
                "payload": {"status": "FINALIZING", "reason": "interview_complete"},
            })
            return
        blueprint_model = InterviewBlueprint(**blueprint) if blueprint else None
        question = await self._generate_next_question(
            session_id, state, blueprint_model, NextAction(action), evaluation_data,
            last_question, candidate_answer,
        )
        if question:
            await self._deliver_question(session_id, state, question)

    async def handle_barge_in(self, session_id: str, payload: dict, state: InterviewState):
        """Xử lý USER_BARGE_IN event (§9, §12)."""
        logger.info(f"USER_BARGE_IN: session={session_id}")
        state.interruption_count += 1
        interview_logger.add_log(
            stage="USER_BARGE_IN",
            message=f"Ứng viên ngắt lời AI (Barge-in lần #{state.interruption_count}) -> Ngắt luồng phát giọng nói TTS ngay lập tức",
            session_id=session_id,
            details={"interruption_count": state.interruption_count, "action": "STOP_TTS_STREAM"},
        )
        # Client đã dừng Piper TTS tại local; server chỉ đồng bộ state
        await self.send_message(session_id, {
            "type": WSMessageType.STATE_SYNC.value,
            "payload": {"interruption_count": state.interruption_count},
        })

    async def handle_reverse_question(self, session_id: str, payload: dict):
        """Xử lý câu hỏi ngược từ ứng viên (§11.4)."""
        question = payload.get("question", "")
        answer = await self.reverse_service.answer_reverse_question(
            question=question,
            company_knowledge=payload.get("company_knowledge", {}),
            jd_context=payload.get("jd_context"),
        )
        await self.send_message(session_id, {
            "type": WSMessageType.REVERSE_ANSWER.value,
            "payload": answer,
        })


# Singleton manager
ws_manager = InterviewWebSocketManager()


@router.websocket("/ws/interview/{session_id}")
async def websocket_interview(websocket: WebSocket, session_id: str):
    """WebSocket endpoint cho phiên phỏng vấn realtime."""
    tracked_websocket = TrafficTrackedWebSocket(websocket, session_id)
    await ws_manager.connect(tracked_websocket, session_id)

    try:
        # Load state từ Redis / Disk Cache
        redis = RedisSessionManager()
        state_data = redis.get_hot_state(session_id)
        if not state_data:
            logger.warning("Interview session was not found: %s", session_id)
            await tracked_websocket.send_json({"type": WSMessageType.ERROR.value, "payload": {"message": "Session not found", "retryable": False}})
            ws_manager.disconnect(session_id, tracked_websocket)
            await tracked_websocket.close(code=4404, reason="Interview session was not found")
            return

        state = InterviewState(**state_data)

        # Generate from framework criteria + CV/JD, or replay an existing generated
        # question on reconnect. Never read seed/example text into the interview.
        blueprint_data = redis.get_blueprint(session_id)
        if blueprint_data:
            state = await ws_manager.open_or_resume_question(session_id, state, InterviewBlueprint(**blueprint_data))
        else:
            await tracked_websocket.send_json({"type": WSMessageType.ERROR.value, "payload": {"message": "Session not found: missing interview blueprint", "retryable": False}})
            ws_manager.disconnect(session_id, tracked_websocket)
            await tracked_websocket.close(code=4404, reason="Interview blueprint was not found")
            return

        # Vòng lặp nhận message
        while True:
            data = await tracked_websocket.receive_json()
            msg_type = data.get("type", "")
            payload = data.get("payload", {})

            if msg_type == WSMessageType.RECONNECT.value and payload.get("retry_question"):
                blueprint_data = redis.get_blueprint(session_id)
                if blueprint_data:
                    await ws_manager.retry_pending_question(session_id, state, InterviewBlueprint(**blueprint_data))

            elif msg_type == WSMessageType.PARTIAL_TRANSCRIPT.value:
                await ws_manager.handle_partial_transcript(session_id, payload, state)

            elif msg_type == WSMessageType.STREAM_SEGMENT.value:
                await ws_manager.handle_stream_segment(session_id, payload, state)

            elif msg_type == WSMessageType.FINAL_TRANSCRIPT.value:
                await ws_manager.handle_final_transcript(session_id, payload, state)

            elif msg_type == WSMessageType.USER_BARGE_IN.value:
                await ws_manager.handle_barge_in(session_id, payload, state)

            elif msg_type == WSMessageType.USER_CONFIRMED_TRANSCRIPT.value:
                # User xác nhận transcript → tạo Verified Canonical Transcript
                payload["verified"] = True
                await ws_manager.handle_final_transcript(session_id, payload, state)

            elif msg_type == WSMessageType.REVERSE_QUESTION.value:
                await ws_manager.handle_reverse_question(session_id, payload)

            elif msg_type == WSMessageType.COMMUNICATION_FEATURES.value:
                # Lưu communication features (không ảnh hưởng score)
                logger.info(f"Communication features received: session={session_id}")

            elif msg_type == WSMessageType.CLIENT_TIMING.value:
                phase = str(payload.get("phase", ""))[:48]
                latency_ms = payload.get("latency_ms")
                if phase in {"first_audio_started", "answer_to_first_audio", "speech_to_partial_text", "speech_end_to_final_text"} and isinstance(latency_ms, (int, float)) and 0 <= latency_ms <= 120_000:
                    interview_logger.add_log(
                        stage=("VOICE_TURN_LATENCY" if phase == "answer_to_first_audio"
                               else "VOICE_ASR_TIMING" if phase in {"speech_to_partial_text", "speech_end_to_final_text"}
                               else "VOICE_CLIENT_TIMING"),
                        message=f"Thời gian phía trình duyệt: {phase} = {round(float(latency_ms), 1)}ms.",
                        session_id=session_id,
                        turn_id=str(payload.get("turn_id", "")),
                        details={"phase": phase, "latency_ms": round(float(latency_ms), 1)},
                    )

            elif msg_type == WSMessageType.SELF_REPORT.value:
                logger.info(f"Self-report received: session={session_id}")

            # Sync state back to Redis
            redis.set_hot_state(session_id, state.model_dump())

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, tracked_websocket)
        logger.info(f"WebSocket disconnected: session={session_id}")
        record_traffic_event(
            kind="websocket",
            direction="connection",
            name="WebSocket disconnected",
            path="/ws/interview/{session_id}",
            session_id=session_id,
        )
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(session_id, tracked_websocket)
        record_traffic_event(
            kind="websocket",
            direction="connection",
            name="WebSocket error",
            path="/ws/interview/{session_id}",
            session_id=session_id,
            error=type(e).__name__,
        )
