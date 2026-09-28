"""
CÓC ĐI LÀM — WebSocket Interview Turn Manager (§4)
Quản lý luồng streaming WebSocket turn-by-turn.
Pipeline: Streaming → ASR Gate → Evaluation → Turn Decision.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.models.schemas import (
    WSMessage, WSMessageType, InterviewState,
    JevStreamingDecision, JevASRGateDecision, JevTurnDecision,
    LayaStreamingDecision, LayaASRGateDecision, LayaTurnDecision,
    SessionStatus, AdaptationMode, EventType, ValidationStatus,
)
from app.services.hard_policy_engine import get_hard_policy_engine
from app.services.jev_controller import get_jev_controller
from app.services.evidence_evaluator import get_evidence_evaluator
from app.services.question_service import get_question_service
from app.services.decision_audit import get_decision_audit
from app.services.evaluation_queue import get_evaluation_queue
from app.services.reverse_interview_service import get_reverse_interview_service
from app.core.redis import RedisSessionManager, get_redis_client
from app.core.config import get_settings
from app.services.interview_logger import interview_logger
import json
import logging
import uuid
import time
from datetime import datetime

logger = logging.getLogger(__name__)
router = APIRouter()


class InterviewWebSocketManager:
    """
    Quản lý WebSocket cho phiên phỏng vấn realtime.
    Thực thi pipeline Streaming → ASR Gate → Evaluation → Turn Decision
    với TypeSafe AI Jev Controller (§8).
    """

    def __init__(self):
        self.active_connections: dict[str, WebSocket] = {}
        self.policy = get_hard_policy_engine()
        self.jev = get_jev_controller()
        self.laya = self.jev  # Backward compatibility alias
        self.evaluator = get_evidence_evaluator()
        self.question_service = get_question_service()
        self.audit = get_decision_audit()
        self.eval_queue = get_evaluation_queue()
        self.reverse_service = get_reverse_interview_service()
        self._evaluating_sessions: set[str] = set()

    async def connect(self, websocket: WebSocket, session_id: str):
        """Kết nối WebSocket mới."""
        await websocket.accept()
        self.active_connections[session_id] = websocket
        logger.info(f"WebSocket connected: session={session_id}")

    def disconnect(self, session_id: str):
        """Ngắt kết nối."""
        self.active_connections.pop(session_id, None)
        logger.info(f"WebSocket disconnected: session={session_id}")

    async def send_message(self, session_id: str, message: dict):
        """Gửi message tới client."""
        ws = self.active_connections.get(session_id)
        if ws:
            await ws.send_json(message)

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
        turn_id = payload.get("turn_id", f"turn_{uuid.uuid4().hex[:8]}")
        partial_text = payload.get("text", "")
        stream_features = payload.get("features", {})

        # 1. Hard Policy tạo allowed_stream_actions
        allowed = self.policy.compute_allowed_stream_actions(
            state=state,
            partial_duration_sec=stream_features.get("duration_sec", 0),
            audio_quality_ok=stream_features.get("audio_quality_ok", True),
        )

        # 2. TypeSafe AI Jev Streaming Decision (hoặc fallback)
        decision = self.jev.predict_streaming_decision(
            partial_transcript=partial_text,
            stream_features=stream_features,
            allowed_actions=allowed,
            state=state,
        )

        # 3. Hard Policy hậu kiểm
        decision = self.policy.validate_stream_decision(decision, allowed)

        # 4. Audit
        self.audit.create_audit_record(
            event_type=EventType.JEV_STREAM_DECISION,
            session_id=session_id,
            turn_id=turn_id,
            model_version=self.jev.model_version if self.jev.is_available else "deterministic_fallback",
            confidence=decision.stream_confidence,
            input_refs=[f"partial:{turn_id}"],
        )

        # 5. Gửi kết quả về client
        await self.send_message(session_id, {
            "type": WSMessageType.STREAM_DECISION.value,
            "turn_id": turn_id,
            "payload": decision.model_dump(),
        })

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
        if session_id in self._evaluating_sessions:
            logger.warning(f"Session {session_id} is already evaluating an answer. Dropping duplicate turn request.")
            return

        self._evaluating_sessions.add(session_id)
        try:
            turn_id = payload.get("turn_id", f"turn_{uuid.uuid4().hex[:8]}")
            final_text = payload.get("text", "")
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

            # 2. TypeSafe AI Jev ASR Gate (hoặc user confirmation fallback)
            decision = self.jev.predict_asr_gate_decision(
                final_transcript=final_text,
                term_candidates=term_candidates,
                allowed_actions=allowed,
                state=state,
            )

            # 3. Hard Policy hậu kiểm
            decision = self.policy.validate_asr_decision(decision, allowed)

            # Log ASR_GATE
            raw_action = getattr(decision, "asr_gate_action", getattr(decision, "asr_action", "ACCEPT_AS_IS"))
            action_val = raw_action.value if hasattr(raw_action, "value") else str(raw_action)
            interview_logger.add_log(
                stage="ASR_GATE",
                message=f"ASR Gate kiểm định an toàn: safe={decision.transcript_safe}, action={action_val} (Tin cậy: {decision.asr_confidence:.2f})",
                session_id=session_id,
                turn_id=turn_id,
                details={
                    "transcript_safe": decision.transcript_safe,
                    "confidence": decision.asr_confidence,
                    "action": action_val,
                    "has_critical_disagreement": has_critical,
                },
            )

            # 4. Audit
            self.audit.create_audit_record(
                event_type=EventType.JEV_ASR_DECISION,
                session_id=session_id,
                turn_id=turn_id,
                model_version=self.jev.model_version if self.jev.is_available else "user_confirmed",
                confidence=decision.asr_confidence,
                input_refs=[f"final_transcript:{turn_id}"],
            )

            # 5. Gửi kết quả về client
            await self.send_message(session_id, {
                "type": WSMessageType.ASR_GATE_RESULT.value,
                "turn_id": turn_id,
                "payload": decision.model_dump(),
            })

            # 6. Nếu transcript safe hoặc user đã xác nhận → tiếp tục pipeline Evaluation
            if decision.transcript_safe or payload.get("verified", False):
                await self._run_evaluation_pipeline(
                    session_id, turn_id, final_text, state
                )
        finally:
            self._evaluating_sessions.discard(session_id)

    # ================================================================
    # EVALUATION + TURN DECISION PHASE
    # ================================================================

    async def _run_evaluation_pipeline(
        self,
        session_id: str,
        turn_id: str,
        verified_transcript: str,
        state: InterviewState,
    ):
        """Pipeline: Verified Transcript → Evaluation → Turn Decision."""
        # Lấy blueprint từ Redis
        redis = RedisSessionManager()
        blueprint = redis.get_blueprint(session_id)

        # Xác định rubric_type từ current stage
        current_stage = None
        if blueprint and blueprint.get("stages"):
            for stage in blueprint["stages"]:
                if stage["stage_name"] == state.current_topic:
                    current_stage = stage
                    break
            if not current_stage:
                current_stage = blueprint["stages"][0]

        rubric_type = current_stage.get("rubric_type", "technical_correctness") if current_stage else "technical_correctness"

        # 1. Scoring Gate check
        if not self.policy.can_evaluate(transcript_safe=True):
            return

        # 2. Evidence Evaluator
        from app.models.schemas import RubricType
        eval_start = time.perf_counter()
        evaluation = await self.evaluator.evaluate(
            turn_id=turn_id,
            rubric_type=RubricType(rubric_type),
            verified_transcript=verified_transcript,
            current_question=state.current_concept or "",
            candidate_context={
                "role": state.role,
                "company": state.company_target,
                "concepts": [state.current_concept] if state.current_concept else [],
            },
        )
        eval_latency_ms = round((time.perf_counter() - eval_start) * 1000, 1)

        # Xác định câu hỏi vừa được trả lời và giai đoạn hiện tại
        last_question = ""
        if state.asked_question_texts:
            last_question = state.asked_question_texts[-1]
        elif state.current_concept:
            last_question = state.current_concept
        else:
            last_question = "Câu hỏi đánh giá năng lực OJT"

        stage_name = current_stage.get("stage_name", state.current_topic or "technical_core") if current_stage else (state.current_topic or "technical_core")

        if evaluation is None:
            # All evaluators failed → PENDING_EVALUATION
            interview_logger.add_log(
                stage="RUBRIC_EVAL",
                message=f"Đánh giá Rubric [{rubric_type}] thất bại sau {eval_latency_ms}ms -> Chuyển DEGRADED_BLUEPRINT fallback",
                session_id=session_id,
                turn_id=turn_id,
                details={"status": "FAILED", "fallback": "DEGRADED_BLUEPRINT", "latency_ms": eval_latency_ms},
            )
            state.pending_evaluation_count += 1
            state.adaptation_mode = AdaptationMode.DEGRADED_BLUEPRINT
            await self.eval_queue.enqueue(turn_id, session_id, rubric_type, {})

            # Deterministic Blueprint progression
            allowed_turn = self.policy.compute_allowed_turn_actions(state)
            fallback = self.jev._turn_fallback(state, allowed_turn)

            await self.send_message(session_id, {
                "type": WSMessageType.STATE_SYNC.value,
                "payload": {"adaptation_mode": "DEGRADED_BLUEPRINT"},
            })

            # Get next question deterministically
            if fallback.next_action.value != "finish_interview":
                from app.models.schemas import InterviewBlueprint
                bp = InterviewBlueprint(**blueprint) if blueprint else None
                question = await self.question_service.get_next_question(
                    fallback.next_action, state, bp, evaluation=None
                )
                if question:
                    from app.services.conversational_service import get_conversational_service
                    conv_service = get_conversational_service()
                    question.question_text = await conv_service.bridge_turn_dialog(
                        last_question=last_question,
                        candidate_answer=verified_transcript,
                        evaluation=None,
                        next_action=fallback.next_action.value,
                        prev_stage=stage_name,
                        next_stage=state.current_topic or "technical_core",
                        raw_question=question.question_text,
                        role=state.role,
                        company=state.company_target,
                    )
                    if state.asked_question_texts:
                        state.asked_question_texts[-1] = question.question_text
                    else:
                        state.asked_question_texts.append(question.question_text)
                    await self.send_message(session_id, {
                        "type": WSMessageType.STATE_SYNC.value,
                        "payload": state.model_dump(),
                    })
                    await self.send_message(session_id, {
                        "type": WSMessageType.QUESTION_TEXT.value,
                        "turn_id": f"turn_{uuid.uuid4().hex[:8]}",
                        "payload": question.model_dump(),
                    })
                    q_stage = getattr(question, "stage_name", None) or getattr(question, "effective_stage", state.current_topic or "technical_core")
                    q_rubric = getattr(question, "target_rubric", None) or getattr(question, "effective_rubric", "technical_correctness")
                    interview_logger.add_log(
                        stage="QUESTION_ENGINE",
                        message=f"Question Engine xuất câu hỏi fallback: [{q_stage}] \"{question.question_text[:100]}...\"",
                        session_id=session_id,
                        turn_id=turn_id,
                        details={
                            "question_id": question.question_id,
                            "stage_name": q_stage,
                            "target_rubric": q_rubric,
                            "question_text": question.question_text,
                        },
                    )
            redis.set_hot_state(session_id, state.model_dump())
            return

        # 3. Evaluation success → update state
        score_val = getattr(evaluation, "score", 7.0)
        awarded_list = getattr(evaluation, "points_awarded", [])
        missed_list = getattr(evaluation, "points_missed", [])

        # Tạo candidate_summary và better_answer_hint từ payload thực tế
        if awarded_list:
            candidate_summary = "; ".join(awarded_list[:3])
        else:
            candidate_summary = "Ứng viên chưa nêu được các luận điểm chính hoặc câu trả lời chưa đúng trọng tâm."

        if missed_list:
            better_answer_hint = "Cần làm rõ và bổ sung: " + "; ".join(missed_list[:2])
        else:
            better_answer_hint = "Câu trả lời đã khá đầy đủ. Có thể mở rộng thêm kinh nghiệm tối ưu thực chiến và số liệu định lượng."

        # Lưu bản ghi đánh giá turn thực tế vào Redis & Disk Cache (§6, §14)
        turn_eval_record = {
            "turn_number": len(redis.get_turn_evaluations(session_id)) + 1,
            "turn_id": turn_id,
            "stage": stage_name,
            "rubric_type": rubric_type,
            "question": last_question,
            "candidate_answer": verified_transcript,
            "score": round(score_val, 1),
            "confidence": evaluation.evaluation_confidence,
            "candidate_summary": candidate_summary,
            "better_answer_hint": better_answer_hint,
            "points_awarded": awarded_list,
            "points_missed": missed_list,
            "payload": evaluation.payload,
            "evaluated_at": datetime.utcnow().isoformat(),
        }
        redis.save_turn_evaluation(session_id, turn_eval_record)

        interview_logger.add_log(
            stage="RUBRIC_EVAL",
            message=f"Bộ chấm điểm Rubric [{rubric_type}]: {score_val:.1f}/10.0 (Xử lý: {eval_latency_ms}ms)",
            session_id=session_id,
            turn_id=turn_id,
            details={
                "rubric_type": rubric_type,
                "score": score_val,
                "confidence": evaluation.evaluation_confidence,
                "eval_latency_ms": eval_latency_ms,
                "points_awarded": awarded_list,
                "points_missed": missed_list,
                "is_fast_path": eval_latency_ms < 50,
            },
        )
        state.remaining_scored_question_budget -= 1

        # Audit evaluation
        self.audit.create_audit_record(
            event_type=EventType.EVALUATION,
            session_id=session_id,
            turn_id=turn_id,
            model_version=self.evaluator.settings.gemini_flash_model,
            confidence=evaluation.evaluation_confidence,
            input_refs=[f"verified_transcript:{turn_id}"],
        )

        # 4. Turn Decision
        if self.policy.can_create_turn_decision(True, state):
            allowed_turn = self.policy.compute_allowed_turn_actions(state, evaluation)
            turn_decision = self.jev.predict_turn_decision(
                state=state,
                evaluation=evaluation.model_dump(),
                allowed_actions=allowed_turn,
            )
            turn_decision = self.policy.validate_turn_decision(turn_decision, allowed_turn, state)

            act_str = turn_decision.next_action.value if hasattr(turn_decision.next_action, "value") else str(turn_decision.next_action)
            interview_logger.add_log(
                stage="JEV_DECISION",
                message=f"TypeSafe AI Jev Controller quyết định: [{act_str}] (Độ tin cậy: {turn_decision.decision_confidence:.2f})",
                session_id=session_id,
                turn_id=turn_id,
                details={
                    "next_action": act_str,
                    "confidence": turn_decision.decision_confidence,
                    "current_stage": state.current_topic,
                    "remaining_budget": state.remaining_scored_question_budget,
                },
            )

            # Audit turn decision
            self.audit.create_audit_record(
                event_type=EventType.JEV_TURN_DECISION,
                session_id=session_id,
                turn_id=turn_id,
                model_version=self.jev.model_version if self.jev.is_available else "deterministic_fallback",
                confidence=turn_decision.decision_confidence,
                input_refs=[f"evaluation:{turn_id}"],
            )

            # Execute next action
            await self._execute_turn_action(
                session_id=session_id,
                decision=turn_decision,
                state=state,
                blueprint=blueprint,
                evaluation_data=evaluation.model_dump() if evaluation else None,
                turn_id=turn_id,
                last_question=last_question,
                candidate_answer=verified_transcript,
                prev_stage=stage_name,
            )

    async def _execute_turn_action(
        self,
        session_id: str,
        decision: LayaTurnDecision,
        state: InterviewState,
        blueprint: dict | None,
        evaluation_data: dict | None = None,
        turn_id: str = "",
        last_question: str = "",
        candidate_answer: str = "",
        prev_stage: str = "",
    ):
        """Thực thi action từ Turn Decision với lời thoại đàm thoại tự nhiên."""
        action = decision.next_action.value
        redis = RedisSessionManager()

        # finish_interview → FINALIZING, không gọi Question Service (§11.3)
        if action == "finish_interview":
            state.status = SessionStatus.FINALIZING
            redis.set_hot_state(session_id, state.model_dump())
            interview_logger.add_log(
                stage="JEV_DECISION",
                message="Phiên phỏng vấn hoàn tất! Đang chuyển sang giai đoạn tổng kết báo cáo.",
                session_id=session_id,
                turn_id=turn_id,
                details={"status": "FINALIZING"},
            )
            await self.send_message(session_id, {
                "type": WSMessageType.SESSION_ENDED.value,
                "payload": {"status": "FINALIZING", "reason": "interview_complete"},
            })
            return

        # wrap_up → closing template
        if action == "wrap_up":
            question = self.question_service._get_wrap_up_question(state)
            question.question_text = (
                "Rất cảm ơn sự nỗ lực và phần thể hiện của em qua các câu hỏi vừa rồi. "
                "Chúng ta đã hoàn thành tất cả các nội dung đánh giá chuyên môn hôm nay. "
                f"Bây giờ là thời gian dành cho em, em có câu hỏi hay thắc mắc nào muốn trao đổi thêm "
                f"với phía {state.company_target} về môi trường làm việc hoặc kỳ thực tập OJT sắp tới không?"
            )
            redis.set_hot_state(session_id, state.model_dump())
            await self.send_message(session_id, {
                "type": WSMessageType.QUESTION_TEXT.value,
                "turn_id": f"turn_{uuid.uuid4().hex[:8]}",
                "payload": question.model_dump(),
            })
            interview_logger.add_log(
                stage="QUESTION_ENGINE",
                message=f"Question Engine xuất câu hỏi wrap-up: \"{question.question_text[:100]}...\"",
                session_id=session_id,
                turn_id=turn_id,
                details={"type": "WRAP_UP", "question_text": question.question_text},
            )
            return

        # Các action tiếp tục phỏng vấn → Question Service
        from app.models.schemas import InterviewBlueprint, NextAction
        bp = InterviewBlueprint(**blueprint) if blueprint else None
        question = await self.question_service.get_next_question(
            NextAction(action), state, bp, evaluation=evaluation_data
        )
        if question:
            # Tạo lời dẫn thoại tự nhiên chuẩn mực đời thực
            from app.services.conversational_service import get_conversational_service
            conv_service = get_conversational_service()
            next_stage = getattr(question, "stage_name", None) or state.current_topic or "technical_core"

            conversational_text = await conv_service.bridge_turn_dialog(
                last_question=last_question,
                candidate_answer=candidate_answer,
                evaluation=evaluation_data,
                next_action=action,
                prev_stage=prev_stage,
                next_stage=next_stage,
                raw_question=question.question_text,
                role=state.role,
                company=state.company_target,
            )
            question.question_text = conversational_text
            if state.asked_question_texts:
                state.asked_question_texts[-1] = conversational_text
            else:
                state.asked_question_texts.append(conversational_text)

            # Gửi đồng bộ trạng thái mới (stage mới, concept mới) cho Client
            await self.send_message(session_id, {
                "type": WSMessageType.STATE_SYNC.value,
                "payload": state.model_dump(),
            })
            await self.send_message(session_id, {
                "type": WSMessageType.QUESTION_TEXT.value,
                "turn_id": f"turn_{uuid.uuid4().hex[:8]}",
                "payload": question.model_dump(),
            })
            q_stage = getattr(question, "stage_name", None) or getattr(question, "effective_stage", state.current_topic or "technical_core")
            q_rubric = getattr(question, "target_rubric", None) or getattr(question, "effective_rubric", "technical_correctness")
            q_concepts = getattr(question, "expected_concepts", None) or question.concepts or []
            interview_logger.add_log(
                stage="QUESTION_ENGINE",
                message=f"Question Engine xuất câu hỏi: [{q_stage}] \"{question.question_text[:100]}...\"",
                session_id=session_id,
                turn_id=turn_id,
                details={
                    "question_id": question.question_id,
                    "stage_name": q_stage,
                    "target_rubric": q_rubric,
                    "question_text": question.question_text,
                    "expected_concepts": q_concepts,
                },
            )
        redis.set_hot_state(session_id, state.model_dump())

    # ================================================================
    # EVENT HANDLERS
    # ================================================================

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
    await ws_manager.connect(websocket, session_id)

    try:
        # Load state từ Redis / Disk Cache
        redis = RedisSessionManager()
        state_data = redis.get_hot_state(session_id)
        if not state_data:
            # Self-healing: Tự động khôi phục session state & blueprint khi server vừa reload
            # để ứng viên không bao giờ bị văng kết nối hay gặp lỗi "Session not found"
            logger.info(f"Self-healing: session state not found in hot cache for {session_id}. Auto-reconstructing...")
            from app.api.v1.sessions import _generate_blueprint
            settings = get_settings()
            blueprint = _generate_blueprint(
                session_id=session_id,
                student_id="SE180000",
                company="FPT Software",
                role="Java Backend Intern",
                domain_pack="it_software",
            )
            state = InterviewState(
                session_id=session_id,
                candidate_name="Ứng viên",
                student_id="SE180000",
                role="Java Backend Intern",
                company_target="FPT Software",
                current_topic=blueprint.stages[0].stage_name if blueprint.stages else None,
                time_remaining_sec=settings.session_default_duration_sec,
                remaining_scored_question_budget=settings.session_scored_question_budget,
            )
            redis.set_hot_state(session_id, state.model_dump())
            redis.cache_blueprint(session_id, blueprint.model_dump())
            state_data = state.model_dump()

        state = InterviewState(**state_data)

        # Gửi state sync ban đầu
        await websocket.send_json({
            "type": WSMessageType.STATE_SYNC.value,
            "payload": state.model_dump(),
        })

        # Gửi câu hỏi mở đầu từ Blueprint (luôn bảo đảm client nhận được câu hỏi khi mới vào hoặc refresh trang)
        blueprint_data = redis.get_blueprint(session_id)
        if blueprint_data and blueprint_data.get("stages"):
            first_stage = blueprint_data["stages"][0]
            first_q = first_stage.get("seed_question")
            if first_q:
                from app.services.conversational_service import get_conversational_service
                conv_service = get_conversational_service()
                cand_name = getattr(state, "candidate_name", "") or ""
                if not cand_name:
                    try:
                        cand_memory = redis.get_cached_candidate_memory(state.student_id) or {}
                        cand_name = cand_memory.get("candidate_name", "")
                    except Exception:
                        pass

                opening_speech = conv_service.format_opening_question(
                    company=state.company_target,
                    role=state.role,
                    candidate_name=cand_name,
                    seed_question=first_q,
                )

                if opening_speech not in state.asked_question_texts:
                    state.asked_question_texts.append(opening_speech)
                state.questions_on_current_concept = max(1, state.questions_on_current_concept)
                redis.set_hot_state(session_id, state.model_dump())
                rubric_val = first_stage.get("rubric_type")
                if hasattr(rubric_val, "value"):
                    rubric_val = rubric_val.value
                stage_val = first_stage.get("stage_name")
                if hasattr(stage_val, "value"):
                    stage_val = stage_val.value

                await websocket.send_json({
                    "type": WSMessageType.QUESTION_TEXT.value,
                    "turn_id": f"turn_{uuid.uuid4().hex[:8]}",
                    "payload": {
                        "question_id": f"q_init_{session_id}",
                        "question_text": opening_speech,
                        "target_rubric": str(rubric_val or "hr_motivation"),
                        "stage_name": str(stage_val or "hr_motivation"),
                        "expected_concepts": first_stage.get("concepts", []),
                    },
                })
                interview_logger.add_log(
                    stage="QUESTION_ENGINE",
                    message=f"Khởi động câu hỏi mở đầu: [{stage_val or 'hr_motivation'}] \"{opening_speech[:100]}...\"",
                    session_id=session_id,
                    turn_id="turn_init",
                    details={
                        "question_id": f"q_init_{session_id}",
                        "stage_name": str(stage_val or "hr_motivation"),
                        "target_rubric": str(rubric_val or "hr_motivation"),
                        "question_text": opening_speech,
                        "type": "OPENING_QUESTION",
                    },
                )

        # Vòng lặp nhận message
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            payload = data.get("payload", {})

            if msg_type == WSMessageType.PARTIAL_TRANSCRIPT.value:
                await ws_manager.handle_partial_transcript(session_id, payload, state)

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

            elif msg_type == WSMessageType.SELF_REPORT.value:
                logger.info(f"Self-report received: session={session_id}")

            # Sync state back to Redis
            redis.set_hot_state(session_id, state.model_dump())

    except WebSocketDisconnect:
        ws_manager.disconnect(session_id)
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        ws_manager.disconnect(session_id)
