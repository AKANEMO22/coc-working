"""
CÓC ĐI LÀM — Backend Configuration
Quản lý biến môi trường và cấu hình hệ thống.
"""

from pydantic_settings import BaseSettings
from typing import Literal
from functools import lru_cache
from app.shared.paths import BACKEND_ROOT, PROJECT_ROOT


class Settings(BaseSettings):
    """Cấu hình ứng dụng backend, đọc từ file .env"""

    # === Application ===
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_cors_origins: str = "http://localhost:3000,https://*.vercel.app,*"
    # Read-only normalized CV/job/framework dataset; override per environment.
    normalized_data_dir: str = str(PROJECT_ROOT / "data" / "normalized")

    # === Authentication Profile ===
    auth_profile: Literal["PILOT_DEMO", "PRODUCTION"] = "PILOT_DEMO"

    # === Google Gemini AI ===
    google_gemini_api_key: str = ""
    gemini_flash_model: str = "gemini-3.5-flash-lite"
    # Kept as a configuration alias for older callers; current interview paths
    # use the same supported low-latency model unless explicitly overridden.
    gemini_pro_model: str = "gemini-3.5-flash-lite"
    interview_generation_timeout_sec: float = 12.0
    # Keep the live dialogue path bounded; the generic timeout above remains
    # available for non-realtime generation tasks.
    interview_question_timeout_sec: float = 12.0
    interview_clarification_timeout_sec: float = 12.0
    interview_evaluation_timeout_sec: float = 20.0

    # === Local speech models; adjust these in backend/.env ===
    tts_provider: Literal["vieneu"] = "vieneu"
    vieneu_voice: str = "Hải Đăng"
    vieneu_model_id: str = "vieneu-v3-turbo"
    vieneu_device: Literal["auto", "cpu", "cuda"] = "cuda"
    vieneu_max_batch_size: int = 32
    vieneu_max_streams: int = 16
    vieneu_temperature: float = 0.8
    vieneu_top_k: int = 25
    vieneu_top_p: float = 0.95
    stt_model_id: str = "Qwen3-ASR-1.7B"
    stt_model_path: str = "Qwen/Qwen3-ASR-1.7B"
    stt_device: Literal["auto", "cpu", "cuda"] = "cuda"
    preload_local_speech: bool = False

    @property
    def gemini_api_key(self) -> str:
        return self.google_gemini_api_key

    # === Database (Local PostgreSQL or Supabase) ===
    database_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # === Upstash Redis ===
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # === Local Laya System-1 interview decision controller ===
    # Public Apache-2.0 multilingual weights download from HF on first load and
    # are then reused from the local Hugging Face cache. No API key/paid call.
    laya_model_path: str = "convaiinnovations/laya-multilingual"
    laya_model_revision: str = "1720e3e3357cfe1e281542e223f8273b0890ca34"
    laya_device: str = "cpu"
    laya_fast: bool = False
    laya_enabled: bool = True
    laya_decision_timeout_sec: float = 2.0

    # === Session Config ===
    session_default_duration_sec: int = 1500  # 25 phút
    session_scored_question_budget: int = 8
    session_reconnect_timeout_sec: int = 120

    # === Policy Versions ===
    policy_version: str = "v1.0.0"
    schema_version: str = "v1.0.0"

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.app_cors_origins.split(",")]

    model_config = {
        "env_file": str(BACKEND_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
