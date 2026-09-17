"""Groq (Groq Cloud API) — the **first, primary** leg of Ciphlet's free
cloud chain (§20A): Groq -> Gemini -> OpenRouter free -> local Qwen (see
ciphlet/brain/router.py).

Chosen as the first-tried automatic cloud route for normal conversation,
cybersecurity tutoring, study, and reasoning because, of the free-tier
options verified against Groq's official docs (console.groq.com/docs/rate-
limits) at implementation time:

- Groq's free tier is a genuine no-cost, no-credit-card developer tier —
  rate-limit gated only, with no credits system and no per-token charge
  (exact RPM/TPM/RPD figures are account/model-specific and shown live at
  console.groq.com/settings/limits rather than published as one fixed
  table, so this provider reacts to whatever the API returns rather than
  hardcoding a quota)
- serves strong open-weight reasoning models (default here: Llama 3.3 70B)
  that are well above what an 8GB Pi 5 can run locally, at very low latency
  (LPU inference), which matters for a voice-first companion
- OpenAI-compatible chat API — simple, mature client SDK

Anthropic Claude (ciphlet/brain/claude_provider.py) remains available as an
opt-in premium provider for when the owner explicitly wants its extra
reasoning quality and accepts its cost — it is never part of this free chain
and never constructed or called automatically. See main.py's --premium flag.

Like every other backend, this class is a swappable intelligence leg, not
Ciphlet's identity: identity/personality lives in the Orchestrator + Learning
Engine system prompt (ciphlet/learning/engine.py), handed to this provider
identically to every other one.
"""

from __future__ import annotations

from ciphlet.brain.base import BrainProvider, BrainUnavailableError, Message

RUNTIME_IDENTITY_NOTE = (
    "\n\nRUNTIME FACT — this overrides anything you might otherwise assume "
    "about your own identity: you are currently answering as {identity}, "
    "running on Groq's cloud servers (not on the Raspberry Pi itself — the "
    "Pi only runs Ciphlet's orchestrator, memory, and voice components). "
    "You are NOT GPT-4, NOT ChatGPT, and NOT made by OpenAI. If asked what AI "
    "model, provider, or brain you're running on, answer only with the fact "
    "above — never guess, and never claim GPT-4, ChatGPT, OpenAI, or any "
    "other provider."
)


class GroqBrainProvider(BrainProvider):
    def __init__(self, api_key: str | None, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy: only import/construct the SDK client on first use

    @property
    def name(self) -> str:
        return "groq"

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self):
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise BrainUnavailableError(
                "GROQ_API_KEY is not set. Ciphlet's default cloud brain is offline; "
                "set the key in .env or the environment to enable conversation."
            )

        try:
            from groq import Groq
        except ImportError as exc:
            raise BrainUnavailableError(
                "The 'groq' package is not installed. Install Ciphlet's core "
                "dependencies to enable the cloud brain."
            ) from exc

        self._client = Groq(api_key=self._api_key)
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
        grounded_system = system + RUNTIME_IDENTITY_NOTE.format(identity=f"Groq ({self._model})")

        chat_messages = [{"role": "system", "content": grounded_system}]
        chat_messages += [{"role": m.role, "content": m.content} for m in messages]

        try:
            response = client.chat.completions.create(
                model=self._model,
                max_tokens=1024,
                messages=chat_messages,
            )
        except Exception as exc:  # network/API errors — fail visibly, don't crash
            raise BrainUnavailableError(f"Groq brain request failed: {exc}") from exc

        return (response.choices[0].message.content or "").strip()
