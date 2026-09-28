"""
CÓC ĐI LÀM — Pydantic Schemas
Tất cả data models cho Streaming/ASR/Turn Decisions, EvaluationEnvelope, State, Blueprint.
Tuân thủ nghiêm ngặt kiến trúc §6, §7, §8, §16, §21, §23.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


# ============================================================
# ============================================================
# §8.1 — Jev / Laya Streaming Decision
# ============================================================

class StreamAction(str, Enum):
    CONTINUE = "CONTINUE"
    AI_SOFT_INTERRUPT = "AI_SOFT_INTERRUPT"
    CLARIFY_NOW = "CLARIFY_NOW"
    ASK_REPEAT = "ASK_REPEAT"
    END_TURN = "END_TURN"


class JevStreamingDecision(BaseModel):
    """Quyết định streaming khi ứng viên đang nói (TypeSafe AI Jev)."""
    stream_action: StreamAction
    stream_confidence: float = Field(ge=0.0, le=1.0)


# Backward compatibility alias
LayaStreamingDecision = JevStreamingDecision


# ============================================================
# §8.2 — Jev / Laya ASR Gate Decision
# ============================================================

class ASRGateAction(str, Enum):
    ACCEPT_AS_IS = "ACCEPT_AS_IS"
    ACCEPT_CORRECTION = "ACCEPT_CORRECTION"
    REQUEST_VERIFICATION = "REQUEST_VERIFICATION"
    ASK_CONFIRMATION = "ASK_CONFIRMATION"


class JevASRGateDecision(BaseModel):
    """Quyết định ASR Gate - xác minh Final Transcript (TypeSafe AI Jev)."""
    transcript_safe: bool
    asr_gate_action: ASRGateAction
    asr_confidence: float = Field(ge=0.0, le=1.0)

    @property
    def asr_action(self) -> ASRGateAction:
        return self.asr_gate_action


# Backward compatibility alias
LayaASRGateDecision = JevASRGateDecision


# ============================================================
# §8.3 — Jev / Laya Turn Decision
# ============================================================

class AnswerIntent(str, Enum):
    DIRECT_ANSWER = "direct_answer"
    CLARIFICATION_QUESTION = "clarification_question"
    GIVE_UP = "give_up"
    IRRELEVANT = "irrelevant"
    PAUSE = "pause"


class NextAction(str, Enum):
    PROBE = "probe"
    SAME_LEVEL = "same_level"
    HARDER = "harder"
    EASIER = "easier"
    SWITCH_TOPIC = "switch_topic"
    CLARIFY_ANSWER = "clarify_answer"
    VERIFY_REASONING = "verify_reasoning"
    FINISH_TOPIC = "finish_topic"
    WRAP_UP = "wrap_up"
    FINISH_INTERVIEW = "finish_interview"


class DifficultyAction(str, Enum):
    INCREASE = "increase"
    MAINTAIN = "maintain"
    DECREASE = "decrease"


class JevTurnDecision(BaseModel):
    """Quyết định sau lượt - chọn bước phỏng vấn tiếp theo (TypeSafe AI Jev)."""
    answer_intent: AnswerIntent
    relevance: float = Field(ge=0.0, le=1.0)
    decision_confidence: float = Field(ge=0.0, le=1.0)
    next_action: NextAction
    difficulty_action: Optional[DifficultyAction] = None
    escalate_to_strong_llm: Optional[bool] = False


# Backward compatibility alias
LayaTurnDecision = JevTurnDecision


# ============================================================
# §6.1 — EvaluationEnvelope
# ============================================================

class RubricType(str, Enum):
    HR_MOTIVATION = "hr_motivation"
    STAR_FRAMEWORK = "star_framework"
    TECHNICAL_CORRECTNESS = "technical_correctness"
    CASE_STUDY = "case_study"


class EvaluationEnvelope(BaseModel):
    """Bọc mọi evaluation output."""
    turn_id: str
    rubric_type: RubricType
    payload_schema: str
    evaluation_confidence: float = Field(ge=0.0, le=1.0)
    payload: dict

    @property
    def score(self) -> float:
        """Tính điểm số chuẩn hóa 0.0 - 10.0 dựa trên payload."""
        p = self.payload or {}
        if self.rubric_type == RubricType.TECHNICAL_CORRECTNESS:
            return round(float(p.get("correctness", 0.7)) * 10.0, 1)
        elif self.rubric_type == RubricType.HR_MOTIVATION:
            dims = [
                p.get("role_motivation_specificity"),
                p.get("company_understanding_evidence"),
                p.get("learning_goal_clarity"),
            ]
            valid = [float(d) for d in dims if d is not None]
            return round((sum(valid) / max(1, len(valid))) * 10.0, 1) if valid else 7.5
        elif self.rubric_type == RubricType.STAR_FRAMEWORK:
            dims = [
                p.get("situation_clarity"),
                p.get("task_definition"),
                p.get("action_depth"),
                p.get("result_quantification"),
                p.get("ownership_evidence_strength"),
            ]
            valid = [float(d) for d in dims if d is not None]
            return round((sum(valid) / max(1, len(valid))) * 10.0, 1) if valid else 7.0
        elif self.rubric_type == RubricType.CASE_STUDY:
            dims = [
                p.get("problem_structuring"),
                p.get("root_cause_identification"),
                p.get("solution_feasibility"),
                p.get("business_impact_awareness"),
            ]
            valid = [float(d) for d in dims if d is not None]
            return round((sum(valid) / max(1, len(valid))) * 10.0, 1) if valid else 7.0
        return 7.0

    @property
    def points_awarded(self) -> list[str]:
        p = self.payload or {}
        if self.rubric_type == RubricType.TECHNICAL_CORRECTNESS:
            return p.get("covered", []) or ["Nêu được kiến thức kỹ thuật cơ bản"]
        elif self.rubric_type == RubricType.HR_MOTIVATION:
            return p.get("observed_points", []) or ["Thể hiện động lực ứng tuyển"]
        elif self.rubric_type == RubricType.STAR_FRAMEWORK:
            res = [f"Khai thác tốt {k}" for k, v in p.items() if isinstance(v, (int, float)) and v >= 0.6]
            return res or ["Trình bày mạch lạc theo cấu trúc STAR"]
        elif self.rubric_type == RubricType.CASE_STUDY:
            res = [f"Xử lý tốt {k}" for k, v in p.items() if isinstance(v, (int, float)) and v >= 0.6]
            return res or ["Tiếp cận bài toán có logic"]
        return []

    @property
    def points_missed(self) -> list[str]:
        p = self.payload or {}
        if self.rubric_type == RubricType.TECHNICAL_CORRECTNESS:
            return p.get("missing", []) + p.get("misconceptions", [])
        elif self.rubric_type == RubricType.HR_MOTIVATION:
            return p.get("missing_points", [])
        elif self.rubric_type == RubricType.STAR_FRAMEWORK:
            return [f"Chưa làm rõ {c}" for c in p.get("missing_star_components", [])]
        elif self.rubric_type == RubricType.CASE_STUDY:
            return [f"Cần cải thiện {k}" for k, v in p.items() if isinstance(v, (int, float)) and v < 0.6]
        return []


# ============================================================
# §6.2 — TechnicalEvidenceOutput
# ============================================================

class TechnicalEvidenceOutput(BaseModel):
    """Evidence đánh giá kỹ thuật."""
    correctness: float = Field(ge=0.0, le=1.0)
    covered: list[str]
    missing: list[str]
    misconceptions: list[str]
    depth: int = Field(ge=0, le=5, description="0=không đủ nội dung; 1..5=nhận biết → hiểu sâu")


# ============================================================
# §6.3 — HRMotivation_EvaluationOutput
# ============================================================

class HRDimension(str, Enum):
    ROLE_MOTIVATION_SPECIFICITY = "role_motivation_specificity"
    COMPANY_UNDERSTANDING_EVIDENCE = "company_understanding_evidence"
    LEARNING_GOAL_CLARITY = "learning_goal_clarity"
    COLLABORATION_EXAMPLE_QUALITY = "collaboration_example_quality"


class HRMotivationEvaluationOutput(BaseModel):
    """Evidence đánh giá HR/Động lực ứng tuyển."""
    role_motivation_specificity: Optional[float] = Field(None, ge=0.0, le=1.0)
    company_understanding_evidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    learning_goal_clarity: Optional[float] = Field(None, ge=0.0, le=1.0)
    collaboration_example_quality: Optional[float] = Field(None, ge=0.0, le=1.0)
    assessed_dimensions: list[HRDimension]
    observed_points: list[str]
    missing_points: list[str]


# ============================================================
# §21.2 — STAR_EvaluationOutput
# ============================================================

class RoleOwnership(str, Enum):
    PRIMARY_BUILDER = "primary_builder"
    CONTRIBUTOR = "contributor"
    OBSERVER = "observer"
    UNCLEAR = "unclear"


class STARComponent(str, Enum):
    SITUATION = "situation"
    TASK = "task"
    ACTION = "action"
    RESULT = "result"


class STAREvaluationOutput(BaseModel):
    """Evidence đánh giá STAR framework cho dự án CV."""
    situation_clarity: float = Field(ge=0.0, le=1.0)
    task_definition: float = Field(ge=0.0, le=1.0)
    action_depth: float = Field(ge=0.0, le=1.0)
    result_quantification: float = Field(ge=0.0, le=1.0)
    ownership_evidence_strength: float = Field(ge=0.0, le=1.0)
    role_ownership: RoleOwnership
    missing_star_components: list[STARComponent]


# ============================================================
# §21.3 — CaseStudy_EvaluationOutput
# ============================================================

class CaseStudyEvaluationOutput(BaseModel):
    """Evidence đánh giá tình huống Case Study."""
    problem_structuring: float = Field(ge=0.0, le=1.0)
    root_cause_identification: float = Field(ge=0.0, le=1.0)
    solution_feasibility: float = Field(ge=0.0, le=1.0)
    business_impact_awareness: float = Field(ge=0.0, le=1.0)
    structured_framework_used: Optional[str] = None


# ============================================================
# §7.2 — Interview State Schema
# ============================================================

class SessionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"


class AdaptationMode(str, Enum):
    ADAPTIVE = "ADAPTIVE"
    DEGRADED_BLUEPRINT = "DEGRADED_BLUEPRINT"


class ReportStatus(str, Enum):
    NOT_READY = "NOT_READY"
    PENDING_EVALUATION = "PENDING_EVALUATION"
    PENDING_GENERATION = "PENDING_GENERATION"
    READY = "READY"


class SkillEstimate(BaseModel):
    """Điểm ước lượng năng lực + độ tin cậy tách biệt."""
    estimate: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=0)


class InterviewState(BaseModel):
    """Trạng thái phiên phỏng vấn đầy đủ (§7.2)."""
    session_id: str
    candidate_name: str
    student_id: str
    role: str
    company_target: str
    current_topic: Optional[str] = None
    current_concept: Optional[str] = None
    current_difficulty: int = Field(default=2, ge=1, le=5)
    topic_coverage: dict[str, float] = Field(default_factory=dict)
    skill_estimates: dict[str, SkillEstimate] = Field(default_factory=dict)
    questions_on_current_concept: int = Field(default=0, ge=0)
    time_remaining_sec: int = Field(default=1500)
    interruption_count: int = Field(default=0, ge=0)
    status: SessionStatus = SessionStatus.IN_PROGRESS
    adaptation_mode: AdaptationMode = AdaptationMode.ADAPTIVE
    pending_evaluation_count: int = Field(default=0, ge=0)
    remaining_scored_question_budget: int = Field(default=8, ge=0)
    report_status: ReportStatus = ReportStatus.NOT_READY
    asked_question_texts: list[str] = Field(default_factory=list)


# ============================================================
# §16.1 — Audit Record
# ============================================================

class EventType(str, Enum):
    JEV_TURN_DECISION = "jev_turn_decision"
    JEV_ASR_DECISION = "jev_asr_decision"
    JEV_STREAM_DECISION = "jev_stream_decision"
    LAYA_TURN_DECISION = "laya_turn_decision"
    LAYA_ASR_DECISION = "laya_asr_decision"
    LAYA_STREAM_DECISION = "laya_stream_decision"
    EVALUATION = "evaluation"


class ValidationStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    PENDING = "PENDING"


class AuditRecord(BaseModel):
    """Bản ghi kiểm toán cho typed decisions (§16.1)."""
    event_type: EventType
    session_id: str
    turn_id: str
    model_version: str
    policy_version: str
    schema_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    input_refs: list[str]
    validation_status: ValidationStatus
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ============================================================
# §23.2 — Interview Blueprint
# ============================================================

class BlueprintStage(BaseModel):
    """Một giai đoạn trong đề cương phỏng vấn."""
    stage_id: int
    stage_name: str
    target_duration_sec: int
    rubric_type: RubricType
    seed_question: Optional[str] = None
    source_cv_project: Optional[str] = None
    concepts: Optional[list[str]] = None
    question_budget: int = Field(default=2, ge=1)


class InterviewBlueprint(BaseModel):
    """Đề cương phỏng vấn tự động (§23.2)."""
    blueprint_id: str
    session_id: str
    candidate_name: str
    student_id: str
    target_company: str
    target_role: str
    domain_pack: str
    total_planned_questions: int = Field(default=8)
    stages: list[BlueprintStage]


# ============================================================
# §7.3 — Long-Term Candidate Memory
# ============================================================

class CandidateSkillMemory(BaseModel):
    """Skill Memory xuyên phiên (§7.3.2A)."""
    student_id: str
    skill: str
    estimate: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    trend: Literal["improving", "stagnant", "declining"] = "stagnant"
    evidence_count: int = Field(default=0, ge=0)
    last_verified_at: Optional[datetime] = None
    evidence_refs: list[str] = Field(default_factory=list)


class ConceptMemory(BaseModel):
    """Concept Memory theo concept (§7.3.2B)."""
    student_id: str
    concept: str
    status: Literal["strong", "moderate", "weak"] = "weak"
    confidence: float = Field(ge=0.0, le=1.0)
    last_result: Optional[str] = None
    retry_priority: float = Field(default=0.5, ge=0.0, le=1.0)
    last_seen_at: Optional[datetime] = None
    evidence_refs: list[str] = Field(default_factory=list)


class CompactMemoryContext(BaseModel):
    """Compact Memory Context cho Interview Blueprint (§7.3.4)."""
    student_id: str
    recent_strengths: list[str] = Field(default_factory=list)
    weak_concepts: list[str] = Field(default_factory=list)
    retry_queue: list[str] = Field(default_factory=list)
    skill_trend: dict[str, str] = Field(default_factory=dict)
    last_session_at: Optional[datetime] = None


# ============================================================
# §12.1 — Communication Behavior
# ============================================================

class DeliverySignals(BaseModel):
    """Chỉ báo giao tiếp quan sát được (§12.1.1)."""
    response_latency_ms: Optional[int] = None
    speech_rate_wpm: Optional[int] = None
    pause_ratio: Optional[float] = None
    long_pause_count: Optional[int] = None
    filler_word_count: Optional[int] = None
    restart_count: Optional[int] = None
    self_correction_count: Optional[int] = None
    answer_duration_sec: Optional[float] = None
    repetition_score: Optional[float] = None
    too_quiet_or_clipped: Optional[bool] = None
    barge_in_count: Optional[int] = None


class DeliveryPattern(str, Enum):
    DELIVERY_FLUENT = "delivery_fluent"
    DELIVERY_HESITANT_PATTERN = "delivery_hesitant_pattern"
    DELIVERY_RAMBLING_PATTERN = "delivery_rambling_pattern"
    DELIVERY_TOO_BRIEF = "delivery_too_brief"
    AUDIO_QUALITY_PROBLEM = "audio_quality_problem"


class CommunicationFeatures(BaseModel):
    """Kết quả phân tích giao tiếp cho một turn."""
    turn_id: str
    session_id: str
    delivery_signals: DeliverySignals
    delivery_patterns: list[DeliveryPattern] = Field(default_factory=list)


# ============================================================
# §11.2 — Question Provenance
# ============================================================

class SourceType(str, Enum):
    OFFICIAL_JD = "official_jd"
    TECH_BLOG = "tech_blog"
    DOCS = "docs"
    THIRD_PARTY = "third_party"
    CURATED = "curated"
    TEMPLATE_GENERATED = "template_generated"
    AI_GENERATED = "ai_generated"


class QuestionProvenance(BaseModel):
    """Metadata nguồn gốc câu hỏi (§11.2)."""
    source_type: SourceType
    source_url: Optional[str] = None
    source_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    fetched_at: Optional[datetime] = None
    verification_status: str = "verified"
    expiry: Optional[datetime] = None
    generation_model: Optional[str] = None
    generation_context_refs: list[str] = Field(default_factory=list)


class Question(BaseModel):
    """Câu hỏi với provenance tracking."""
    question_id: str
    question_text: str
    rubric_type: RubricType
    difficulty: int = Field(ge=1, le=5)
    concepts: list[str] = Field(default_factory=list)
    applicable_roles: list[str] = Field(default_factory=list)
    provenance: QuestionProvenance
    stage_name: Optional[str] = None
    target_rubric: Optional[str] = None
    expected_concepts: Optional[list[str]] = None

    @property
    def effective_stage(self) -> str:
        return self.stage_name or (self.rubric_type.value if hasattr(self.rubric_type, "value") else str(self.rubric_type))

    @property
    def effective_rubric(self) -> str:
        return self.target_rubric or (self.rubric_type.value if hasattr(self.rubric_type, "value") else str(self.rubric_type))


# ============================================================
# §23.4 — Reverse Interview Turn
# ============================================================

class ReverseTurnContract(BaseModel):
    """Hợp đồng Reverse Interview Turn (§23.4)."""
    turn_type: Literal["reverse_interview"] = "reverse_interview"
    scored: bool = False
    requires_asr_verification: bool = True
    uses_evidence_evaluator: bool = False
    updates_skill_state: bool = False
    updates_candidate_memory: bool = False


# ============================================================
# §3.1 — Interview Experience
# ============================================================

class InterviewExperience(BaseModel):
    """Kinh nghiệm phỏng vấn đã chuẩn hóa (§3.1.3)."""
    experience_id: str
    company: str
    role: str
    seniority: str
    location: Optional[str] = None
    interview_stage: str
    reported_topics: list[str] = Field(default_factory=list)
    reported_questions: list[dict] = Field(default_factory=list)
    process_signals: dict = Field(default_factory=dict)
    advice: list[str] = Field(default_factory=list)
    source_type: str = "third_party_candidate_report"
    source_url: Optional[str] = None
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None
    official: bool = False


# ============================================================
# WebSocket Message Types
# ============================================================

class WSMessageType(str, Enum):
    """Các loại message WebSocket giữa Client và Server."""
    # Client → Server
    PARTIAL_TRANSCRIPT = "partial_transcript"
    FINAL_TRANSCRIPT = "final_transcript"
    USER_BARGE_IN = "user_barge_in"
    USER_CONFIRMED_TRANSCRIPT = "user_confirmed_transcript"
    SELF_REPORT = "self_report"
    REVERSE_QUESTION = "reverse_question"
    COMMUNICATION_FEATURES = "communication_features"
    RECONNECT = "reconnect"

    # Server → Client
    STREAM_DECISION = "stream_decision"
    ASR_GATE_RESULT = "asr_gate_result"
    QUESTION_TEXT = "question_text"
    EVALUATION_COMPLETE = "evaluation_complete"
    STATE_SYNC = "state_sync"
    SESSION_PAUSED = "session_paused"
    SESSION_ENDED = "session_ended"
    REVERSE_ANSWER = "reverse_answer"
    ERROR = "error"


class WSMessage(BaseModel):
    """Cấu trúc message WebSocket."""
    type: WSMessageType
    session_id: str
    turn_id: Optional[str] = None
    payload: dict = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ============================================================
# API Request/Response Models
# ============================================================

class GuestLoginRequest(BaseModel):
    """PILOT_DEMO: Đăng nhập bằng MSSV."""
    student_id: str = Field(min_length=2, max_length=20)
    candidate_name: str = Field(min_length=2, max_length=100)


class GuestLoginResponse(BaseModel):
    """Response đăng nhập guest."""
    student_id: str
    candidate_name: str
    has_existing_profile: bool
    session_count: int = 0


class CreateSessionRequest(BaseModel):
    """Yêu cầu tạo phiên phỏng vấn mới."""
    student_id: str
    target_company: str
    target_role: str
    domain_pack: str = "software_engineering"
    jd_text: Optional[str] = None
    skill_gaps: Optional[list[str]] = None


class CreateSessionResponse(BaseModel):
    """Response tạo phiên."""
    session_id: str
    blueprint: InterviewBlueprint
    state: InterviewState


class CVUploadResponse(BaseModel):
    """Response phân tích CV."""
    student_id: str
    file_url: str
    parsed_profile: dict
    ats_score: Optional[float] = None
    xyz_scores: Optional[dict] = None
    skill_gaps: Optional[list[dict]] = None


class ReportResponse(BaseModel):
    """Response báo cáo tổng kết."""
    session_id: str
    report_status: ReportStatus
    report: Optional[dict] = None
    radar_scores: Optional[dict] = None
