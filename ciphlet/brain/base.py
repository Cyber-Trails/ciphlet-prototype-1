"""Provider-neutral brain boundary (architecture §20A).

Ciphlet's product behavior, memory policy, and orchestration must not bind
directly to any one model vendor. Every reasoning backend — cloud or local —
implements this same small interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


class BrainMode(Enum):
    """Session-level brain mode. Lives here (not a new state system) because
    it's part of the same brain vocabulary as BrainProvider/Message; Session
    (ciphlet/session.py) just carries it as a field, and Orchestrator reads
    it each turn to pick which BrainProvider to call.

    AUTO — the free-provider chain (Groq -> Gemini -> OpenRouter free ->
    local Qwen), see brain/router.py.
    LOCAL_ONLY — bypass every cloud provider unconditionally; local Qwen
    only, no network AI calls at all.
    """

    AUTO = "auto"
    LOCAL_ONLY = "local_only"


@dataclass(frozen=True)
class Message:
    """One turn in a conversation. Shared by memory, brain, and voice modules
    so text and voice modality use the exact same conversation structure."""

    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.created_at is None:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc))


class BrainUnavailableError(Exception):
    """Raised when the active brain provider cannot produce a response.

    The orchestrator must catch this and fail visibly/gracefully (§20A,
    "Offline behavior") rather than crash or silently pretend to answer.
    """


class BrainProvider(ABC):
    """A reasoning backend. Cloud or local; interchangeable behind this interface."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for logging/status, e.g. 'claude'."""

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        *,
        system: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Return a complete reply for the given conversation.

        Raises BrainUnavailableError if the provider cannot respond
        (missing credentials, network failure, API error).

        `on_token`, if given, is called with each incremental text chunk as
        it becomes available (streaming), so a caller can show output as
        it's generated instead of waiting for the full reply — the eventual
        seam for sentence-level streaming into TTS. The return value is
        always the complete accumulated text regardless (for memory
        persistence); a provider that doesn't support streaming simply
        never calls `on_token` and returns the full text once ready, which
        is exactly today's behavior — this parameter is additive, not a
        breaking change to any existing provider.
        """
