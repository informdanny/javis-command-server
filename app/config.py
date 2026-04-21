from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    service_name: str = "javis-command-server"
    log_level: str = "INFO"
    agent_api_key: str = "dev-local-key"
    duplicate_ttl_seconds: int = 60
    default_voice_provider: str = "xai"
    voice_system_prompt: str = (
        "You are Jarvis, a concise voice assistant for a home device. "
        "Be helpful, short, and action-oriented. When tools are available, use them instead of guessing."
    )
    realtime_audio_sample_rate: int = 16000

    openai_api_key: str | None = None
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime"
    openai_realtime_model: str = "gpt-realtime-mini"
    openai_voice: str = "cedar"
    openai_turn_detection_type: str = "semantic_vad"
    openai_semantic_vad_eagerness: str = "auto"

    xai_api_key: str | None = None
    xai_realtime_url: str = "wss://api.x.ai/v1/realtime"
    xai_stt_url: str = "https://api.x.ai/v1/stt"
    xai_voice: str = "ara"
    xai_vad_threshold: float = 0.85
    xai_vad_silence_duration_ms: int = 700
    xai_vad_prefix_padding_ms: int = 333


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
