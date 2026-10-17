"""Secrets must be injected from the environment, never committed defaults."""

from app.shared.config import Settings


def test_provider_credentials_have_empty_safe_defaults_and_laya_is_local():
    settings = Settings(_env_file=None)
    assert "elevenlabs_api_key" not in Settings.model_fields
    assert settings.tts_provider == "vieneu"
    assert settings.stt_model_id == "Qwen3-ASR-1.7B"
    assert settings.stt_device == "cuda"
    assert settings.vieneu_device == "cuda"
    assert settings.database_url == ""
    assert settings.laya_enabled is True
    assert settings.laya_model_path == "convaiinnovations/laya-multilingual"
    assert settings.laya_device == "cpu"


def test_gemini_interview_defaults_use_current_model_and_realistic_deadlines():
    settings = Settings(_env_file=None)
    assert settings.gemini_flash_model == "gemini-3.5-flash-lite"
    assert settings.gemini_pro_model == "gemini-3.5-flash-lite"
    assert settings.interview_question_timeout_sec == 12.0
    assert settings.interview_evaluation_timeout_sec == 20.0
