"""
CÓC ĐI LÀM — Backend Configuration
Quản lý biến môi trường và cấu hình hệ thống.
"""

from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
from functools import lru_cache


class Settings(BaseSettings):
    """Cấu hình ứng dụng backend, đọc từ file .env"""

    # === Application ===
    app_env: Literal["development", "staging", "production"] = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_cors_origins: str = "http://localhost:3000,https://*.vercel.app,*"

    # === Authentication Profile ===
    auth_profile: Literal["PILOT_DEMO", "PRODUCTION"] = "PILOT_DEMO"

    # === Google Gemini AI ===
    google_gemini_api_key: str = ""
    gemini_flash_model: str = "gemini-2.5-flash"
    gemini_pro_model: str = "gemini-2.5-flash"

    @property
    def gemini_api_key(self) -> str:
        return self.google_gemini_api_key

    # === Database (Local PostgreSQL or Supabase) ===
    database_url: str = "postgresql://postgres:Syrex@X2606@127.0.0.1:5432/coc_di_lam"
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""

    # === Upstash Redis ===
    upstash_redis_url: str = ""
    upstash_redis_token: str = ""

    # === TypeSafe AI (Jev System-1 Controller) ===
    typesafe_api_key: str = "apikey_2122cd452d842eba4c8fb53ea1d4b7d69fbb_a9fe7ceb8fe9c9dee739224b7bd81d41fbf3bfef4f56d2ebb2f41a32eddd11a3"
    typesafe_model: str = "jev-latest"
    typesafe_enabled: bool = True
    typesafe_timeout_sec: float = 8.0

    # === Controller Legacy Aliases (Laya -> Jev) ===
    laya_model_path: str = "models/laya/checkpoint.pt"
    laya_device: str = "cpu"
    laya_enabled: bool = True

    # === Crawler ===
    crawl4ai_max_concurrent: int = 3
    crawl4ai_timeout: int = 30

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
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


@lru_cache()
def get_settings() -> Settings:
    """Singleton settings instance."""
    return Settings()
