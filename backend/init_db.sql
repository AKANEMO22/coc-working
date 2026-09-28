-- ========================================================
-- CÓC ĐI LÀM — PostgreSQL 16+ Database Schema
-- Bảng dữ liệu theo kiến trúc hệ thống Cóc Đi Làm
-- ========================================================

-- Tạo extension pgvector nếu có
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'Extension vector not available, skipping.';
END $$;

-- 1. Bảng hồ sơ ứng viên (Candidate Profiles)
CREATE TABLE IF NOT EXISTS candidate_profiles (
    student_id VARCHAR(50) PRIMARY KEY,
    candidate_name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),
    major VARCHAR(100) DEFAULT 'Software Engineering',
    education JSONB DEFAULT '{}'::jsonb,
    skills JSONB DEFAULT '{}'::jsonb,
    experience JSONB DEFAULT '[]'::jsonb,
    certifications JSONB DEFAULT '[]'::jsonb,
    raw_cv_text TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Bảng phiên phỏng vấn (Sessions)
CREATE TABLE IF NOT EXISTS sessions (
    session_id VARCHAR(100) PRIMARY KEY,
    student_id VARCHAR(50) REFERENCES candidate_profiles(student_id) ON DELETE SET NULL,
    target_company VARCHAR(255) NOT NULL,
    target_role VARCHAR(255) NOT NULL,
    domain_pack VARCHAR(100) DEFAULT 'it_software',
    status VARCHAR(50) DEFAULT 'IN_PROGRESS',
    adaptation_mode VARCHAR(50) DEFAULT 'NORMAL',
    blueprint JSONB NOT NULL,
    current_topic VARCHAR(100),
    remaining_budget INT DEFAULT 8,
    time_remaining_sec INT DEFAULT 1500,
    interruption_count INT DEFAULT 0,
    started_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP WITH TIME ZONE
);

-- 3. Bảng các lượt trao đổi (Turns)
CREATE TABLE IF NOT EXISTS turns (
    turn_id VARCHAR(100) PRIMARY KEY,
    session_id VARCHAR(100) REFERENCES sessions(session_id) ON DELETE CASCADE,
    turn_number INT NOT NULL,
    stage_name VARCHAR(100) NOT NULL,
    question_text TEXT NOT NULL,
    rubric_type VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Bảng ASR Raw Transcripts (Chỉ lưu vết, không dùng để scoring)
CREATE TABLE IF NOT EXISTS turn_transcripts_raw (
    id SERIAL PRIMARY KEY,
    turn_id VARCHAR(100) REFERENCES turns(turn_id) ON DELETE CASCADE,
    session_id VARCHAR(100) REFERENCES sessions(session_id) ON DELETE CASCADE,
    raw_text TEXT NOT NULL,
    audio_features JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 5. Bảng Verified Canonical Transcripts (Bắt buộc dùng cho scoring)
CREATE TABLE IF NOT EXISTS turn_transcripts_verified (
    id SERIAL PRIMARY KEY,
    turn_id VARCHAR(100) REFERENCES turns(turn_id) ON DELETE CASCADE,
    session_id VARCHAR(100) REFERENCES sessions(session_id) ON DELETE CASCADE,
    verified_text TEXT NOT NULL,
    verification_source VARCHAR(50) DEFAULT 'ASR_GATE', -- ASR_GATE hoặc USER_CONFIRMED
    confidence NUMERIC(4, 2) DEFAULT 1.0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 6. Bảng bằng chứng đánh giá (Evidence Envelopes)
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id VARCHAR(100) PRIMARY KEY,
    turn_id VARCHAR(100) REFERENCES turns(turn_id) ON DELETE CASCADE,
    session_id VARCHAR(100) REFERENCES sessions(session_id) ON DELETE CASCADE,
    rubric_type VARCHAR(100) NOT NULL,
    overall_score NUMERIC(4, 2) NOT NULL,
    evaluation_confidence NUMERIC(4, 2) NOT NULL,
    evaluator_model VARCHAR(100) NOT NULL,
    rubric_payload JSONB NOT NULL,
    candidate_summary TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 7. Bảng ngân hàng câu hỏi (Questions)
CREATE TABLE IF NOT EXISTS questions (
    question_id VARCHAR(100) PRIMARY KEY,
    question_text TEXT NOT NULL,
    category VARCHAR(100) NOT NULL,
    applicable_roles JSONB DEFAULT '[]'::jsonb,
    target_concepts JSONB DEFAULT '[]'::jsonb,
    difficulty VARCHAR(50) DEFAULT 'MEDIUM',
    rubric_type VARCHAR(100) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 8. Bảng tri thức doanh nghiệp (Company Knowledge)
CREATE TABLE IF NOT EXISTS company_knowledge (
    id SERIAL PRIMARY KEY,
    company_id VARCHAR(100) NOT NULL,
    company_name VARCHAR(255) NOT NULL,
    domain VARCHAR(100),
    culture_highlights JSONB DEFAULT '[]'::jsonb,
    tech_stack JSONB DEFAULT '[]'::jsonb,
    interview_process JSONB DEFAULT '[]'::jsonb,
    source_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 9. Bảng nhật ký quyết định (Audit Logs - §16)
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id VARCHAR(100) PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    session_id VARCHAR(100),
    turn_id VARCHAR(100),
    model_version VARCHAR(100) NOT NULL,
    policy_version VARCHAR(50) NOT NULL,
    confidence NUMERIC(4, 2) NOT NULL,
    validation_status VARCHAR(50) DEFAULT 'VALID',
    input_refs JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 10. Bảng báo cáo đánh giá tổng kết (Reports - §14)
CREATE TABLE IF NOT EXISTS reports (
    report_id VARCHAR(100) PRIMARY KEY,
    session_id VARCHAR(100) UNIQUE REFERENCES sessions(session_id) ON DELETE CASCADE,
    student_id VARCHAR(50) REFERENCES candidate_profiles(student_id) ON DELETE SET NULL,
    overall_score NUMERIC(4, 2) NOT NULL,
    radar_scores JSONB NOT NULL,
    strengths JSONB DEFAULT '[]'::jsonb,
    weaknesses JSONB DEFAULT '[]'::jsonb,
    turn_evaluations JSONB DEFAULT '[]'::jsonb,
    learning_roadmap JSONB DEFAULT '[]'::jsonb,
    retry_recommendations JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 11. Bảng bộ nhớ ứng viên dài hạn (Candidate Memory Profiles - §7.3)
CREATE TABLE IF NOT EXISTS candidate_memory_profiles (
    student_id VARCHAR(50) PRIMARY KEY REFERENCES candidate_profiles(student_id) ON DELETE CASCADE,
    total_sessions_completed INT DEFAULT 0,
    overall_average_score NUMERIC(4, 2) DEFAULT 0.0,
    last_session_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 12. Bảng bộ nhớ kỹ năng xuyên phiên (Candidate Skill Memory)
CREATE TABLE IF NOT EXISTS candidate_skill_memory (
    id SERIAL PRIMARY KEY,
    student_id VARCHAR(50) REFERENCES candidate_profiles(student_id) ON DELETE CASCADE,
    skill_name VARCHAR(100) NOT NULL,
    rolling_average_score NUMERIC(4, 2) NOT NULL,
    assessment_count INT DEFAULT 1,
    last_tested_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(student_id, skill_name)
);

-- 13. Bảng hàng đợi luyện tập lại (Candidate Retry Queue - §7.3)
CREATE TABLE IF NOT EXISTS candidate_retry_queue (
    id SERIAL PRIMARY KEY,
    student_id VARCHAR(50) REFERENCES candidate_profiles(student_id) ON DELETE CASCADE,
    question_id VARCHAR(100) NOT NULL,
    concept VARCHAR(100) NOT NULL,
    last_score NUMERIC(4, 2) NOT NULL,
    retry_priority INT DEFAULT 5,
    is_resolved BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes tối ưu truy vấn
CREATE INDEX IF NOT EXISTS idx_sessions_student_id ON sessions(student_id);
CREATE INDEX IF NOT EXISTS idx_turns_session_id ON turns(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_turn_id ON evidence(turn_id);
CREATE INDEX IF NOT EXISTS idx_transcripts_verified_turn ON turn_transcripts_verified(turn_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_session ON audit_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_retry_queue_student ON candidate_retry_queue(student_id);
