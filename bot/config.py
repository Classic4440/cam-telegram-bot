"""Typed, validated runtime configuration.

All configuration comes from environment variables so secrets never live in the repository.
Required: TELEGRAM_TOKEN, AI_API_KEY.  Everything else has a safe default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_MODEL_FAST = "openai/gpt-oss-20b"
DEFAULT_MODEL_SMART = "openai/gpt-oss-120b"
DEFAULT_FALLBACK_MODELS = ("llama-3.3-70b-versatile", "llama-3.1-8b-instant")
DEFAULT_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _get(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = _get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from None
    if not lo <= value <= hi:
        raise RuntimeError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _float(name: str, default: float, *, lo: float, hi: float) -> float:
    raw = _get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from None
    if not lo <= value <= hi:
        raise RuntimeError(f"{name} must be between {lo} and {hi}, got {value}")
    return value


def _csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = _get(name)
    if raw is None:
        return default
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _id_set(name: str) -> frozenset[int]:
    raw = _get(name)
    if raw is None:
        return frozenset()
    ids: set[int] = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.add(int(part))
        except ValueError:
            raise RuntimeError(f"{name} must be a comma separated list of numeric Telegram ids") from None
    return frozenset(ids)


@dataclass(frozen=True, slots=True)
class Settings:
    telegram_token: str
    ai_api_key: str
    ai_base_url: str = "https://api.groq.com/openai/v1"
    model_fast: str = DEFAULT_MODEL_FAST
    model_smart: str = DEFAULT_MODEL_SMART
    model_fallbacks: tuple[str, ...] = DEFAULT_FALLBACK_MODELS
    vision_model: str = DEFAULT_VISION_MODEL
    whisper_model: str = "whisper-large-v3"
    ai_timeout: float = 30.0
    ai_max_attempts: int = 2
    supabase_url: str | None = None
    supabase_key: str | None = None
    weather_api_key: str | None = None
    admin_ids: frozenset[int] = frozenset()
    port: int = 10000
    history_messages: int = 16
    history_chars: int = 7000
    rate_capacity: int = 10
    rate_refill_seconds: float = 2.0
    max_input_chars: int = 12000
    log_level: str = "INFO"
    keepalive_url: str | None = None
    default_timezone: str = "UTC"
    group_requires_mention: bool = True
    concurrent_updates: int = 16

    @classmethod
    def from_env(cls) -> "Settings":
        token = _get("TELEGRAM_TOKEN")
        if not token:
            raise RuntimeError("Set the TELEGRAM_TOKEN environment variable.")
        ai_key = _get("AI_API_KEY")
        if not ai_key:
            raise RuntimeError("Set the AI_API_KEY environment variable.")

        fast = _get("AI_MODEL") or DEFAULT_MODEL_FAST
        smart = _get("AI_MODEL_SMART") or DEFAULT_MODEL_SMART
        keepalive = _get("KEEPALIVE_URL") or _get("RENDER_EXTERNAL_URL")
        if _get("KEEPALIVE") in {"0", "false", "no", "off"}:
            keepalive = None

        return cls(
            telegram_token=token,
            ai_api_key=ai_key,
            ai_base_url=_get("AI_BASE_URL") or "https://api.groq.com/openai/v1",
            model_fast=fast,
            model_smart=smart,
            model_fallbacks=_csv("AI_FALLBACK_MODELS", DEFAULT_FALLBACK_MODELS),
            vision_model=_get("AI_VISION_MODEL") or DEFAULT_VISION_MODEL,
            whisper_model=_get("WHISPER_MODEL") or "whisper-large-v3",
            ai_timeout=_float("AI_TIMEOUT_SECONDS", 30.0, lo=5.0, hi=120.0),
            ai_max_attempts=_int("AI_MAX_ATTEMPTS", 2, lo=1, hi=5),
            supabase_url=_get("SUPABASE_URL"),
            supabase_key=_get("SUPABASE_KEY"),
            weather_api_key=_get("WEATHER_API_KEY"),
            admin_ids=_id_set("ADMIN_IDS"),
            port=_int("PORT", 10000, lo=1, hi=65535),
            history_messages=_int("HISTORY_MESSAGES", 16, lo=0, hi=60),
            history_chars=_int("HISTORY_CHARS", 7000, lo=500, hi=60000),
            rate_capacity=_int("RATE_CAPACITY", 10, lo=1, hi=100),
            rate_refill_seconds=_float("RATE_REFILL_SECONDS", 2.0, lo=0.1, hi=60.0),
            max_input_chars=_int("MAX_INPUT_CHARS", 12000, lo=200, hi=100000),
            log_level=(_get("LOG_LEVEL") or "INFO").upper(),
            keepalive_url=keepalive,
            default_timezone=_get("DEFAULT_TIMEZONE") or "UTC",
            group_requires_mention=_get("GROUP_REQUIRES_MENTION") not in {"0", "false", "no", "off"},
            concurrent_updates=_int("CONCURRENT_UPDATES", 16, lo=1, hi=256),
        )

    @classmethod
    def for_testing(cls, **overrides) -> "Settings":
        base = dict(telegram_token="123456:TEST-TOKEN", ai_api_key="test-key")
        base.update(overrides)
        return cls(**base)  # type: ignore[arg-type]

    @property
    def supabase_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)
