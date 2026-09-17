"""Brain Router — the routing half of Ciphlet's brain (architecture §20A
"Routing").

Ciphlet's identity/personality is not this file, and it is not any one
provider — it lives in the Orchestrator + Learning Engine system prompt
(ciphlet/learning/engine.py), which every provider below is handed
identically. This router only decides *which* free intelligence answers a
given AUTO-mode turn:

    Groq (free tier) -> Gemini (free tier) -> OpenRouter (:free models) -> local Qwen

Free-use-first, in that explicit order. On a rate-limit or any other
BrainUnavailableError from one provider, the router advances to the next
free provider — it never retries a provider indefinitely and never
substitutes a paid model. If every free cloud provider is unavailable, it
falls back to local Qwen and says so; it does not invent a paid path.

Anthropic Claude is never part of this chain. It is constructed and called
only via the separate owner-authorized --premium path in main.py, which
bypasses this router entirely (see main.py's _build_orchestrator) — that is
what keeps Claude "completely outside the automatic fallback chain."

LOCAL_ONLY mode (§ session-level brain mode, ciphlet/brain/base.py
BrainMode) does not go through this router at all: Orchestrator calls the
local provider directly in that mode, so no network AI call — not even an
attempt — can happen. See ciphlet/orchestrator.py.
"""

from __future__ import annotations

from ciphlet.brain.base import BrainProvider, BrainUnavailableError, Message

DEGRADED_NOTICE = (
    "[Every free cloud brain is unreachable right now, so this is a degraded "
    "local answer — reconnect for full teaching/research capability]\n"
)


class BrainRouter(BrainProvider):
    """Composite BrainProvider that walks an ordered chain of free cloud
    providers, then falls back to local. Used by the Orchestrator exactly
    like any single provider — routing is invisible above this layer.

    `last_served` records which concrete provider/model actually answered
    the most recent generate() call (e.g. "groq (llama-3.3-70b-versatile)").
    Each provider already grounds its own identity into the prompt it sees
    (see each provider's RUNTIME_IDENTITY_NOTE / LOCAL_SYSTEM_SUFFIX) — this
    attribute is the router-level runtime-truth record of the same fact, for
    external reporting/diagnostics (logs, future health checks, §19C)
    without having to trust the LLM's own account of itself.
    """

    def __init__(self, free_chain: list[BrainProvider], local: BrainProvider | None) -> None:
        self._free_chain = free_chain
        self._local = local
        self.last_served: str | None = None
        # Mirrors last_served: whichever leg actually answered's own
        # last_timing, if it exposes one (currently only OllamaBrainProvider
        # does). None for providers that don't report timing.
        self.last_timing: str | None = None

    @property
    def name(self) -> str:
        chain_names = " -> ".join(p.name for p in self._free_chain) or "none"
        local_name = self._local.name if self._local else "none"
        return f"router(free_chain=[{chain_names}], local={local_name})"

    @staticmethod
    def _identity(provider: BrainProvider) -> str:
        model = getattr(provider, "model", None)
        return f"{provider.name} ({model})" if model else provider.name

    def generate(self, messages: list[Message], *, system: str, on_token=None) -> str:
        errors: list[str] = []

        for provider in self._free_chain:
            try:
                reply = provider.generate(messages, system=system, on_token=on_token)
            except BrainUnavailableError as exc:
                errors.append(f"{provider.name}: {exc}")
                continue  # rate-limited/unavailable — advance to next free provider
            self.last_served = self._identity(provider)
            self.last_timing = getattr(provider, "last_timing", None)
            return reply

        if self._local is None:
            raise BrainUnavailableError(
                "All free cloud providers are unavailable and no local brain is "
                "configured: " + "; ".join(errors)
            )

        try:
            reply = self._local.generate(messages, system=system, on_token=on_token)
        except BrainUnavailableError as local_exc:
            errors.append(f"{self._local.name}: {local_exc}")
            raise BrainUnavailableError("; ".join(errors)) from None

        self.last_served = self._identity(self._local)
        self.last_timing = getattr(self._local, "last_timing", None)
        return DEGRADED_NOTICE + reply
