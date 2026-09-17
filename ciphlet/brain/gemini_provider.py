"""Google Gemini API — the **secondary** free Cloud Intelligence leg in
Ciphlet's free-provider chain (§20A), tried after Groq and before OpenRouter
free models (see brain/router.py).

Verified against official Google documentation at implementation time
(ai.google.dev/gemini-api/docs/rate-limits, .../pricing, .../billing;
googleapis/python-genai on GitHub) rather than assumed from prior knowledge:

- Google publishes a genuine free tier (no cost) gated by RPM/TPM/RPD that
  varies by model and account "usage tier" — Google's own docs point to the
  live per-account numbers in AI Studio rather than publishing one fixed
  table, so this provider does not hardcode a quota; it just reacts to
  whatever the API returns (a 429 surfaces as errors.APIError and is treated
  like any other failure — the router advances to the next provider).
- Free tier does not require a linked billing account; Google states a
  billing account must be explicitly linked to move beyond the free tier,
  so an account with no billing account attached cannot be charged via this
  path.
- Free tier prompts/responses may be used by Google to improve their
  products (per the official pricing page) — unlike the paid tier. Route
  privacy-sensitive material accordingly (§20A "Data sensitivity routing").

Uses the official `google-genai` SDK (`from google import genai`), reading
GEMINI_API_KEY. Default model is gemini-2.5-flash, a free-tier-eligible
model per Google's current docs — a candidate default, not frozen; swap via
CIPHLET_GEMINI_MODEL if Google's free-tier model lineup changes.

Like every other backend, this is a swappable intelligence leg behind
BrainProvider, not Ciphlet's identity.
"""

from __future__ import annotations

from ciphlet.brain.base import BrainProvider, BrainUnavailableError, Message

RUNTIME_IDENTITY_NOTE = (
    "\n\nRUNTIME FACT — this overrides anything you might otherwise assume "
    "about your own identity: you are currently answering as {identity}, "
    "running on Google's cloud servers (not on the Raspberry Pi itself — the "
    "Pi only runs Ciphlet's orchestrator, memory, and voice components). "
    "You are NOT GPT-4, NOT ChatGPT, and NOT made by OpenAI. If asked what AI "
    "model, provider, or brain you're running on, answer only with the fact "
    "above — never guess, and never claim GPT-4, ChatGPT, OpenAI, or any "
    "other provider."
)


class GeminiBrainProvider(BrainProvider):
    def __init__(self, api_key: str | None, model: str) -> None:
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy: only import/construct the SDK client on first use

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self):
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise BrainUnavailableError(
                "GEMINI_API_KEY is not set. Ciphlet's secondary free cloud brain "
                "(Gemini) is offline; set the key in .env or the environment."
            )

        try:
            from google import genai
        except ImportError as exc:
            raise BrainUnavailableError(
                "The 'google-genai' package is not installed. Install Ciphlet's "
                "core dependencies to enable the Gemini free-tier brain."
            ) from exc

        self._client = genai.Client(api_key=self._api_key)
        return self._client

    def generate(self, messages: list[Message], *, system: str, on_token=None) -> str:
        # Streaming not implemented for this provider in this pass; the
        # parameter is accepted for interface consistency and ignored —
        # see BrainProvider.generate's docstring (base.py).
        client = self._get_client()

        try:
            from google.genai import errors, types
        except ImportError as exc:
            raise BrainUnavailableError(
                "The 'google-genai' package is not installed. Install Ciphlet's "
                "core dependencies to enable the Gemini free-tier brain."
            ) from exc

        # Gemini's roles are "user" and "model" (not "assistant").
        contents = [
            types.Content(role="model" if m.role == "assistant" else "user", parts=[types.Part.from_text(text=m.content)])
            for m in messages
        ]

        # Runtime-truth fix: ground identity dynamically from this actual
        # provider/model, per-call — never hardcoded into personality
        # (ciphlet/learning/engine.py) — so Ciphlet reports what it's really
        # running on instead of guessing (e.g. hallucinating "GPT-4").
        grounded_system = system + RUNTIME_IDENTITY_NOTE.format(identity=f"Gemini ({self._model})")

        try:
            response = client.models.generate_content(
                model=self._model,
                contents=contents,
                config=types.GenerateContentConfig(system_instruction=grounded_system, max_output_tokens=1024),
            )
        except errors.APIError as exc:  # includes 429 rate-limit — fail visibly, don't crash
            raise BrainUnavailableError(f"Gemini brain request failed: {exc}") from exc
        except Exception as exc:  # network/other errors
            raise BrainUnavailableError(f"Gemini brain request failed: {exc}") from exc

        return (response.text or "").strip()
