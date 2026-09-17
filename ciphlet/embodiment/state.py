"""Embodiment state channel (architecture §13, §14).

Status: IMPLEMENTED / VERIFIED for the state enum + sink interface below.
The actual sprite/display rendering described in §13 is
APPROVED / DESIGNED — NOT IMPLEMENTED; there is no display driver yet.

Only meaningful user-facing states should reach this channel (§14) — the
orchestrator sets these at conversation turn boundaries, not on every
internal/backend event.
"""

from __future__ import annotations

from enum import Enum


class EmbodimentState(Enum):
    IDLE = "idle"
    LISTENING = "attentive/listening"
    THINKING = "thinking"
    SPEAKING = "speaking"
    TEACHING = "teaching"
    INVESTIGATING = "investigating"
    WORKING = "working"
    SUCCESS = "success"
    WARNING = "warning"
    SLEEP = "sleep"


class EmbodimentSink:
    """Receives embodiment state changes.

    This default implementation just logs the state — a stand-in until a real
    display/sprite driver (§13) exists. It is the seam future embodiment
    rendering plugs into without changing orchestration code.
    """

    def set_state(self, state: EmbodimentState) -> None:
        print(f"[embodiment] {state.value}")
