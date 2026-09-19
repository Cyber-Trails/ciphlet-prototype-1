"""Ciphlet Orchestrator — the central coordination layer (§20, §21).

Both the text CLI and the voice pipeline call the same Orchestrator.handle_text,
so voice and typed interaction share one conversation context (§4.2).
"""

from __future__ import annotations

from typing import Callable

from ciphlet.brain.base import BrainMode, BrainProvider, BrainUnavailableError, Message
from ciphlet.embodiment.state import EmbodimentSink, EmbodimentState
from ciphlet.learning.engine import build_system_prompt
from ciphlet.memory.store import MemoryStore
from ciphlet.session import Session

HISTORY_LIMIT = 20

OFFLINE_MESSAGE = (
    "I can't reach any brain right now ({reason}), so I can't give you a "
    "real answer to that. I'm not going to fake it — check the connection, "
    "the configured API keys, or the local model path and try again."
)


class Orchestrator:
    def __init__(
        self,
        brain: BrainProvider,
        memory: MemoryStore,
        session: Session,
        embodiment: EmbodimentSink | None = None,
        local_brain: BrainProvider | None = None,
        system_note: str | None = None,
    ) -> None:
        self._brain = brain  # AUTO mode: free-provider chain (+Claude if --premium)
        self._local_brain = local_brain  # LOCAL_ONLY mode: Qwen directly, bypassing everything above
        self._memory = memory
        self._session = session
        self._embodiment = embodiment or EmbodimentSink()
        # Optional channel context appended to the system prompt (e.g. "you are speaking aloud on a
        # live voice box"). None for text chat, so text behaviour is exactly as before.
        self._system_note = system_note
        self._memory.start_session(session.id, no_memory=session.no_memory)
        # In-process only, for no-memory sessions (§5.3): keeps normal
        # in-session continuity without ever touching SQLite.
        self._transient_history: list[Message] = []
        # Runtime-truth identity of whichever provider/model actually served
        # the most recent turn (e.g. "groq (llama-3.3-70b-versatile)"), so
        # it's observable through normal output (main.py) without a
        # debugger. None until the first successful turn, and reset to None
        # on a failed turn (nothing actually served it).
        self.last_brain: str | None = None
        # How many messages (including the current turn) were actually sent
        # to the brain on the most recent successful call — diagnostic
        # ground truth alongside last_brain, so "the provider had N messages
        # of context" is directly observable per-turn, not just at resume.
        self.last_context_size: int = 0
        # Diagnostic timing summary from whichever provider served the most
        # recent turn (currently only OllamaBrainProvider reports one) —
        # e.g. "load 0.0s, prompt 2.1s (620 tok), first-token 2.2s, gen
        # 3.4s (180 tok), total 5.5s". None if the active provider doesn't
        # expose timing, or nothing has succeeded yet.
        self.last_timing: str | None = None

    @property
    def session(self) -> Session:
        return self._session

    def history_count(self) -> int:
        """How many messages actually exist for this session — diagnostic
        ground truth for CLI startup messaging, so "resuming" claims are
        never opaque (see MemoryStore.count_messages)."""
        if self._session.no_memory:
            return len(self._transient_history)
        return self._memory.count_messages(self._session.id)

    def _active_brain(self) -> BrainProvider:
        """Which BrainProvider answers this turn. LOCAL_ONLY never touches
        self._brain (the AUTO free-provider chain, or Claude under
        --premium) — it goes straight to the local provider, so no network
        AI call is attempted at all."""
        if self._session.brain_mode == BrainMode.LOCAL_ONLY:
            if self._local_brain is None:
                raise BrainUnavailableError(
                    "LOCAL_ONLY mode is active but no local brain is configured "
                    "(set CIPHLET_LOCAL_MODEL_PATH)."
                )
            return self._local_brain
        return self._brain

    @staticmethod
    def _describe_brain(brain: BrainProvider) -> str:
        """Runtime-truth identity of whichever provider actually served a
        call. BrainRouter tracks this per-call in `last_served` (most
        specific: the actual leaf provider after any fallback); a plain
        provider (Claude under --premium, or local under LOCAL_ONLY) is
        unambiguous, so its own name/model is used directly."""
        served = getattr(brain, "last_served", None)
        if served:
            return served
        model = getattr(brain, "model", None)
        return f"{brain.name} ({model})" if model else brain.name

    def handle_text(self, user_text: str, on_token: Callable[[str], None] | None = None) -> str:
        """Process one user turn (from text or transcribed voice) and return
        Ciphlet's reply. This is the single entry point both modalities use.

        `on_token`, if given, is forwarded to the active provider so the
        caller can display output as it's generated (currently only Ollama
        actually streams; other providers ignore it and this behaves
        exactly as before). The full text is always returned regardless,
        for SQLite persistence below."""
        user_message = Message(role="user", content=user_text)

        if not self._session.no_memory:
            self._memory.add_message(self._session.id, user_message)
            history = self._memory.recent_messages(self._session.id, HISTORY_LIMIT)
        else:
            self._transient_history.append(user_message)
            history = self._transient_history[-HISTORY_LIMIT:]

        self._embodiment.set_state(EmbodimentState.THINKING)
        try:
            active_brain = self._active_brain()
            # has_history reflects runtime truth (what was actually loaded
            # for this call), never assumed — an empty/fresh conversation
            # must not be told it has memory it doesn't (§ learning/engine.py).
            system = build_system_prompt(has_history=len(history) > 1)
            if self._system_note:
                system = system + "\n\n" + self._system_note
            reply_text = active_brain.generate(history, system=system, on_token=on_token)
        except BrainUnavailableError as exc:
            self._embodiment.set_state(EmbodimentState.WARNING)
            self.last_brain = None  # nothing actually served this turn
            self.last_timing = None
            return OFFLINE_MESSAGE.format(reason=str(exc))

        self.last_brain = self._describe_brain(active_brain)
        self.last_context_size = len(history)
        self.last_timing = getattr(active_brain, "last_timing", None)

        assistant_message = Message(role="assistant", content=reply_text)
        if not self._session.no_memory:
            self._memory.add_message(self._session.id, assistant_message)
        else:
            self._transient_history.append(assistant_message)

        self._embodiment.set_state(EmbodimentState.IDLE)
        return reply_text
