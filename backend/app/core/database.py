"""
CÓC ĐI LÀM — Supabase Database Client
Kết nối Supabase PostgreSQL 16 + pgvector.
"""

from supabase import create_client, Client
from supabase._async.client import create_client as create_async_client, AsyncClient
from app.core.config import get_settings
from functools import lru_cache
import logging

logger = logging.getLogger(__name__)


@lru_cache()
def get_supabase_client() -> Client:
    """Tạo Supabase sync client (dùng cho REST API đơn giản)."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("Supabase credentials not configured. Database operations will fail.")
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")

    client = create_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    logger.info("Supabase sync client initialized successfully.")
    return client


async def get_async_supabase_client() -> AsyncClient:
    """Tạo Supabase async client (dùng cho WebSocket và async services)."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        logger.warning("Supabase credentials not configured.")
        raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")

    client = await create_async_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
    )
    logger.info("Supabase async client initialized successfully.")
    return client


class SupabaseService:
    """Service wrapper cho các thao tác database phổ biến."""

    def __init__(self, client: Client):
        self.client = client

    # --- Candidate Profiles ---

    async def get_candidate_by_student_id(self, student_id: str) -> dict | None:
        """Truy xuất hồ sơ ứng viên theo student_id (PRIMARY KEY)."""
        response = self.client.table("candidate_profiles").select("*").eq(
            "student_id", student_id
        ).execute()
        if response.data:
            return response.data[0]
        return None

    async def upsert_candidate_profile(self, profile: dict) -> dict:
        """Tạo hoặc cập nhật hồ sơ ứng viên."""
        response = self.client.table("candidate_profiles").upsert(
            profile, on_conflict="student_id"
        ).execute()
        return response.data[0] if response.data else {}

    # --- Sessions ---

    async def create_session(self, session_data: dict) -> dict:
        """Tạo phiên phỏng vấn mới."""
        response = self.client.table("sessions").insert(session_data).execute()
        return response.data[0] if response.data else {}

    async def get_session(self, session_id: str) -> dict | None:
        """Truy xuất phiên theo session_id."""
        response = self.client.table("sessions").select("*").eq(
            "session_id", session_id
        ).execute()
        if response.data:
            return response.data[0]
        return None

    async def update_session(self, session_id: str, updates: dict) -> dict:
        """Cập nhật trạng thái phiên."""
        response = self.client.table("sessions").update(updates).eq(
            "session_id", session_id
        ).execute()
        return response.data[0] if response.data else {}

    # --- Turns ---

    async def create_turn(self, turn_data: dict) -> dict:
        """Tạo turn mới trong phiên."""
        response = self.client.table("turns").insert(turn_data).execute()
        return response.data[0] if response.data else {}

    # --- Transcripts ---

    async def save_raw_transcript(self, transcript_data: dict) -> dict:
        """Lưu ASR raw transcript (không dùng cho scoring)."""
        response = self.client.table("turn_transcripts_raw").insert(transcript_data).execute()
        return response.data[0] if response.data else {}

    async def save_verified_transcript(self, transcript_data: dict) -> dict:
        """Lưu Verified Canonical Transcript."""
        response = self.client.table("turn_transcripts_verified").insert(transcript_data).execute()
        return response.data[0] if response.data else {}

    # --- Evidence ---

    async def save_evidence(self, evidence_data: dict) -> dict:
        """Lưu EvaluationEnvelope + rubric payload."""
        response = self.client.table("evidence").insert(evidence_data).execute()
        return response.data[0] if response.data else {}

    # --- Questions ---

    async def get_questions_by_role(self, role: str, limit: int = 20) -> list[dict]:
        """Truy xuất câu hỏi từ Question Bank theo role."""
        response = (
            self.client.table("questions")
            .select("*")
            .contains("applicable_roles", [role])
            .limit(limit)
            .execute()
        )
        return response.data or []

    # --- Company Knowledge ---

    async def get_company_knowledge(self, company_id: str) -> list[dict]:
        """Truy xuất tri thức doanh nghiệp."""
        response = (
            self.client.table("company_knowledge")
            .select("*")
            .eq("company_id", company_id)
            .execute()
        )
        return response.data or []

    # --- Audit Logs ---

    async def create_audit_log(self, audit_data: dict) -> dict:
        """Ghi audit record cho typed decisions."""
        response = self.client.table("audit_logs").insert(audit_data).execute()
        return response.data[0] if response.data else {}

    # --- Reports ---

    async def save_report(self, report_data: dict) -> dict:
        """Lưu báo cáo đánh giá tổng kết."""
        response = self.client.table("reports").insert(report_data).execute()
        return response.data[0] if response.data else {}

    async def get_report(self, session_id: str) -> dict | None:
        """Truy xuất báo cáo theo session_id."""
        response = (
            self.client.table("reports")
            .select("*")
            .eq("session_id", session_id)
            .execute()
        )
        if response.data:
            return response.data[0]
        return None

    # --- Candidate Memory ---

    async def get_candidate_memory(self, student_id: str) -> dict | None:
        """Truy xuất Long-Term Candidate Memory."""
        response = (
            self.client.table("candidate_memory_profiles")
            .select("*")
            .eq("student_id", student_id)
            .execute()
        )
        if response.data:
            return response.data[0]
        return None

    async def get_candidate_skill_memory(self, student_id: str) -> list[dict]:
        """Truy xuất Skill Memory xuyên phiên."""
        response = (
            self.client.table("candidate_skill_memory")
            .select("*")
            .eq("student_id", student_id)
            .execute()
        )
        return response.data or []

    async def get_candidate_retry_queue(self, student_id: str) -> list[dict]:
        """Truy xuất Retry Queue."""
        response = (
            self.client.table("candidate_retry_queue")
            .select("*")
            .eq("student_id", student_id)
            .order("retry_priority", desc=True)
            .execute()
        )
        return response.data or []
