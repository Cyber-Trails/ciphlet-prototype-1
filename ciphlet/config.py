"""Ciphlet runtime configuration.

Reads settings from the environment (and a local .env file, if present).
Keeps configuration separate from product/orchestration logic per the
architecture's "reuse first" / provider-neutrality principles.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "ciphlet.db"


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(PROJECT_ROOT / ".env")


_load_dotenv()


@dataclass(frozen=True)
class Config:
    # Free-provider chain (§20A), tried in this order automatically in AUTO
    # mode: Groq -> Gemini -> OpenRouter free -> local (Ollama).
    groq_api_key: str | None
    groq_model: str
    gemini_api_key: str | None
    gemini_model: str
    openrouter_api_key: str | None
    openrouter_model: str | None

    # Optional premium Cloud Intelligence (§20A) — Anthropic Claude. Only
    # constructed/called when the user explicitly passes --premium; never
    # part of the free chain, so it never incurs cost automatically.
    anthropic_api_key: str | None
    premium_brain_model: str

    # Local Intelligence (§20A) — a persistent Ollama server (see
    # brain/ollama_provider.py), not a per-request subprocess. Requires
    # `ollama serve` running and the model pulled on the Pi; if unreachable,
    # the router runs cloud-only (no offline/degraded fallback), and
    # LOCAL_ONLY mode fails visibly instead of silently using the cloud.
    ollama_host: str
    ollama_model: str
    ollama_timeout_s: int
    # Explicit context/output bounds (previously unset, causing unbounded
    # prompt growth + Ollama's own per-model defaults to govern latency —
    # see brain/ollama_provider.py). num_predict caps a single reply's
    # length; num_ctx bounds total prompt+reply tokens.
    ollama_num_ctx: int
    ollama_num_predict: int
    # Tight local raw-history window (message count, applied before the
    # token budget above) — SQLite keeps everything; this only bounds what
    # a session's *first* local turn reconstructs from scratch before
    # cheaper same-process KV-cache continuation takes over.
    ollama_history_messages: int

    # Memory
    db_path: Path

    # Voice (§20B)
    wake_model_path: str | None
    piper_model_path: str | None
    vosk_model_path: str | None
    # Mic (PortAudio, via sounddevice) and speaker (ALSA, via `aplay`) device
    # selection — the Pi's default audio device is not always the intended
    # mic/speaker (e.g. a USB mic or HAT). Either an index or a name
    # (sub)string; list real devices with `python3 -m sounddevice` (mic) or
    # `aplay -L` (speaker). Unset uses each subsystem's own default.
    audio_input_device: str | int | None
    audio_output_device: str | None
    # Consecutive 30ms speech frames needed to interrupt Ciphlet mid-reply
    # (barge-in, §4.6). 0 disables barge-in — use if the speaker is audible
    # in the mic and keeps cutting replies off (`ciphlet voice --selftest`
    # measures this and recommends a value).
    barge_in_frames: int
    # Loudness gate for barge-in: an interruption must also be this many times
    # louder than the echo of Ciphlet's own voice at the mic (`ciphlet voice
    # --selftest` measures the echo and recommends a value). 0 = VAD only.
    barge_in_gate: float
    # Longest reply (characters) that is spoken aloud; longer replies are spoken
    # in part ("The rest is on screen") and printed in full. 0 = no cap.
    spoken_max_chars: int
    # Wake engine: "auto" (default) = trained custom model if CIPHLET_WAKE_MODEL
    # is set, else the PocketSphinx "Hey Ciphlet" phrase; "pocketsphinx" or
    # "openwakeword" force one (openwakeword = generic "hey jarvis"/"alexa"
    # bring-up phrases). The PocketSphinx threshold: smaller = more sensitive.
    wake_engine: str
    wake_kws_threshold: float

    @classmethod
    def load(cls) -> "Config":
        return cls(
            groq_api_key=os.environ.get("GROQ_API_KEY"),
            groq_model=os.environ.get("CIPHLET_GROQ_MODEL", "llama-3.3-70b-versatile"),
            gemini_api_key=os.environ.get("GEMINI_API_KEY"),
            gemini_model=os.environ.get("CIPHLET_GEMINI_MODEL", "gemini-2.5-flash"),
            openrouter_api_key=os.environ.get("OPENROUTER_API_KEY"),
            # No default: must be an explicit ':free' model id (see
            # brain/openrouter_provider.py) — never guessed/hardcoded.
            openrouter_model=os.environ.get("CIPHLET_OPENROUTER_MODEL"),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY"),
            premium_brain_model=os.environ.get("CIPHLET_PREMIUM_BRAIN_MODEL", "claude-sonnet-4-5"),
            ollama_host=os.environ.get("CIPHLET_OLLAMA_HOST", "http://localhost:11434"),
            ollama_model=os.environ.get("CIPHLET_OLLAMA_MODEL", "gemma3:1b-it-q4_K_M"),
            ollama_timeout_s=int(os.environ.get("CIPHLET_OLLAMA_TIMEOUT_S", "60")),
            ollama_num_ctx=int(os.environ.get("CIPHLET_OLLAMA_NUM_CTX", "2048")),
            ollama_num_predict=int(os.environ.get("CIPHLET_OLLAMA_NUM_PREDICT", "256")),
            ollama_history_messages=int(os.environ.get("CIPHLET_OLLAMA_HISTORY_MESSAGES", "6")),
            db_path=Path(os.environ.get("CIPHLET_DB_PATH", str(DEFAULT_DB_PATH))),
            wake_model_path=os.environ.get("CIPHLET_WAKE_MODEL"),
            piper_model_path=os.environ.get("CIPHLET_PIPER_MODEL"),
            vosk_model_path=os.environ.get("CIPHLET_VOSK_MODEL_PATH"),
            audio_input_device=_parse_audio_device(os.environ.get("CIPHLET_AUDIO_INPUT_DEVICE")),
            audio_output_device=os.environ.get("CIPHLET_AUDIO_OUTPUT_DEVICE") or None,
            barge_in_frames=int(os.environ.get("CIPHLET_BARGE_IN_FRAMES") or "3"),
            barge_in_gate=float(os.environ.get("CIPHLET_BARGE_IN_GATE") or "2.5"),
            spoken_max_chars=int(os.environ.get("CIPHLET_SPOKEN_MAX_CHARS") or "600"),
            wake_engine=(os.environ.get("CIPHLET_WAKE_ENGINE") or "auto").strip().lower(),
            wake_kws_threshold=float(os.environ.get("CIPHLET_WAKE_KWS_THRESHOLD") or "1e-20"),
        )


def _parse_audio_device(raw: str | None) -> str | int | None:
    if not raw:
        return None
    raw = raw.strip()
    return int(raw) if raw.lstrip("-").isdigit() else raw
