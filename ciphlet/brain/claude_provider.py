"""Claude (Anthropic API) — Ciphlet's **optional premium** Cloud Intelligence
provider (§20A). This is NOT part of the default route: AUTO mode uses the
free-provider chain (Groq -> Gemini -> OpenRouter free -> local Qwen; see
ciphlet/brain/router.py). This class is only ever constructed and called
when the owner explicitly opts in (main.py's --premium flag) — never
automatically, so it never incurs charges without explicit selection, and it
is never part of the automatic fallback chain (it isn't in free_chain, and
--local-only bypasses it too — see orchestrator.py's _active_brain).

Kept available for when stronger reasoning/teaching quality than the free
chain is worth its metered cost — deep research, long-context lessons, or
anything the owner specifically wants Claude for. Like every provider, it is
a swappable intelligence backend, not Ciphlet's identity: personality lives
in the Orchestrator + Learning Engine system prompt
(ciphlet/learning/engine.py), handed to this provider identically to every
other one.

Sits fully behind BrainProvider; the Orchestrator only ever talks to
whichever provider main.py hands it (the free-chain BrainRouter, or this
class under --premium), so this can be replaced or dropped without touching
orchestration, memory, routing, or learning logic.
"""

from __future__ import annotations

from ciphlet.brain.base import BrainProvider, BrainUnavailableError, Message

RUNTIME_IDENTITY_NOTE = (
    "\n\nRUNTIME FACT — this overrides anything you might otherwise assume "
    "about your own identity: you are currently answering as {identity}, "
    "running on Anthropic's cloud servers (not on the Raspberry Pi itself — "
    "the Pi only runs Ciphlet's orchestrator, memory, and voice components). "
    "You are NOT GPT-4, NOT ChatGPT, and NOT made by OpenAI. If asked what AI "
    "model, provider, or brain you're running on, answer only with the fact "
    "above — never guess, and never claim GPT-4, ChatGPT, OpenAI, or any "
    "other provider."
)


class ClaudeBrainProvider(BrainProvider):
    def __init__(self, api_key: str | None, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy: only import/construct the SDK client on first use

    @property
    def name(self) -> str:
        return "claude"

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self):
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise BrainUnavailableError(
                "ANTHROPIC_API_KEY is not set. Ciphlet's premium cloud brain is "
                "offline; set the key in .env or the environment to use --premium."
            )

        try:
            import anthropic
        except ImportError as exc:
            raise BrainUnavailableError(
                "The 'anthropic' package is not installed. Install Ciphlet's "
                "premium extras to enable the --premium brain."
            ) from exc

        self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    def generate(self, messages: list[Message], *, system: str, on_token=None) -> str:
        # Streaming not implemented for this provider in this pass; the
        # parameter is accepted for interface consistency and ignored —
        # see BrainProvider.generate's docstring (base.py).
        client = self._get_client()

        # Runtime-truth fix: ground identity dynamically from this actual
        # provider/model, per-call — never hardcoded into personality
        # (ciphlet/learning/engine.py) — so Ciphlet reports what it's really
        # running on instead of guessing (e.g. hallucinating "GPT-4").
        grounded_system = system + RUNTIME_IDENTITY_NOTE.format(identity=f"Claude ({self._model})")

        try:
            response = client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=grounded_system,
                messages=[{"role": m.role, "content": m.content} for m in messages],
            )
        except Exception as exc:  # network/API errors — fail visibly, don't crash
            raise BrainUnavailableError(f"Claude brain request failed: {exc}") from exc

        text_parts = [block.text for block in response.content if block.type == "text"]
        return "".join(text_parts).strip()
