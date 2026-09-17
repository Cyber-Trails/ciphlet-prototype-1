"""OpenRouter — the **tertiary** free Cloud Intelligence leg in Ciphlet's
free-provider chain (§20A), tried after Groq and Gemini and before local
Qwen (see brain/router.py).

Verified against OpenRouter's official docs at implementation time
(openrouter.ai/docs/api_reference/limits) rather than assumed from prior
knowledge:

- Models whose ID ends in the literal suffix `:free` are priced at $0 per
  token and, per OpenRouter's own docs, "using :free models does not incur
  charges" — this is the one hard, documented zero-cost guarantee OpenRouter
  publishes.
- Free-model rate limit: 20 requests/minute regardless of account status;
  50 requests/day on a $0 balance, rising to 1,000/day only after a $10+
  lifetime credit purchase (credits are for headroom/limits, not spent by
  :free calls).
- A meta-router model ("openrouter/free") also exists that auto-selects
  among free models, but OpenRouter's own docs did not give this provider a
  clear, explicit zero-cost guarantee (its response includes a general
  "cost" field) — so it is deliberately NOT used here. Ciphlet only ever
  calls a model whose ID literally ends in ":free", and enforces that
  suffix in code below rather than trusting configuration alone.
- OpenRouter's free-model lineup rotates over time (their own docs note
  this), so no specific model is hardcoded as a shipped default — the owner
  must set CIPHLET_OPENROUTER_MODEL to a current ":free" model id from
  https://openrouter.ai/models?max_price=0.

No dedicated SDK dependency is added for this: OpenRouter's endpoint is a
plain OpenAI-compatible HTTPS POST, so this uses only the standard library
(urllib) to avoid pulling in an extra package for one provider.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

from ciphlet.brain.base import BrainProvider, BrainUnavailableError, Message

API_URL = "https://openrouter.ai/api/v1/chat/completions"

RUNTIME_IDENTITY_NOTE = (
    "\n\nRUNTIME FACT — this overrides anything you might otherwise assume "
    "about your own identity: you are currently answering as {identity}, "
    "running on OpenRouter's cloud servers (not on the Raspberry Pi itself — "
    "the Pi only runs Ciphlet's orchestrator, memory, and voice components). "
    "You are NOT GPT-4, NOT ChatGPT, and NOT made by OpenAI, regardless of "
    "which underlying open-weight model is actually serving this request. If "
    "asked what AI model, provider, or brain you're running on, answer only "
    "with the fact above — never guess, and never claim GPT-4, ChatGPT, "
    "OpenAI, or any other provider."
)


class OpenRouterBrainProvider(BrainProvider):
    def __init__(self, api_key: str | None, model: str | None) -> None:
        self._api_key = api_key
        self._model = model

    @property
    def name(self) -> str:
        return "openrouter"

    @property
    def model(self) -> str | None:
        return self._model

    def generate(self, messages: list[Message], *, system: str, on_token=None) -> str:
        # Streaming not implemented for this provider in this pass; the
        # parameter is accepted for interface consistency and ignored —
        # see BrainProvider.generate's docstring (base.py).
        if not self._api_key:
            raise BrainUnavailableError(
                "OPENROUTER_API_KEY is not set. Ciphlet's tertiary free cloud "
                "brain (OpenRouter) is offline; set the key in .env or the environment."
            )

        if not self._model:
            raise BrainUnavailableError(
                "CIPHLET_OPENROUTER_MODEL is not set. Pick a current ':free' model id "
                "from https://openrouter.ai/models?max_price=0 and set it explicitly."
            )

        # Hard safety gate: never call anything but a model whose id is
        # explicitly documented as $0 (see module docstring). This does not
        # trust configuration alone — it refuses to make the request at all
        # if the configured model isn't a literal ":free" model.
        if not self._model.endswith(":free"):
            raise BrainUnavailableError(
                f"Refusing to call OpenRouter model '{self._model}': it does not end in "
                "':free', so it is not guaranteed zero-cost. Set CIPHLET_OPENROUTER_MODEL "
                "to a model id ending in ':free'."
            )

        # Runtime-truth fix: ground identity dynamically from this actual
        # provider/model, per-call — never hardcoded into personality
        # (ciphlet/learning/engine.py) — so Ciphlet reports what it's really
        # running on instead of guessing (e.g. hallucinating "GPT-4").
        grounded_system = system + RUNTIME_IDENTITY_NOTE.format(identity=f"OpenRouter ({self._model})")

        payload = {
            "model": self._model,
            "messages": [{"role": "system", "content": grounded_system}]
            + [{"role": m.role, "content": m.content} for m in messages],
        }
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 429 = rate-limited, 402 = negative balance, etc. — all treated
            # the same way: fail visibly, let the router advance.
            raise BrainUnavailableError(f"OpenRouter brain request failed ({exc.code}): {exc.reason}") from exc
        except Exception as exc:
            raise BrainUnavailableError(f"OpenRouter brain request failed: {exc}") from exc

        try:
            return body["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, AttributeError) as exc:
            raise BrainUnavailableError(f"OpenRouter returned an unexpected response shape: {exc}") from exc
