"""Local Intelligence brain provider (architecture §20A "Local intelligence").

Runtime: **Ollama**, run as a persistent background service that keeps the
model resident in memory across requests (`keep_alive=-1`).

=== Real Pi evidence on the /api/generate + context approach: it doesn't work here ===

The previous version of this file migrated from `/api/chat` to
`/api/generate` + the `context` token-array field, on the theory (from
ollama/ollama#14780) that CPU-backend `/api/chat` couldn't reuse its KV
cache but `/api/generate` + `context` could. **Real Pi measurements
disproved this for this installation**: two consecutive local turns in the
same process both showed full prompt evaluation (467 then 546 tokens) with
no `prompt_eval_cached_count` ever reported and no speedup — i.e. passing
`context` back was not actually resuming from a cached state here.

Investigating further (Ollama's own docs/issues, not assumed): the
`context` field for `/api/generate` is not just cosmetically "deprecated"
— Ollama's own maintainers describe it as **"longtime replaced by
functionality in the /api/chat endpoint"** (ollama/ollama#10576,
discussion on #8732). It is legacy, on the way out, and — per this
project's own real-hardware test — not delivering a working cache-skip on
this Pi/Ollama/model combination regardless of what older reports claimed
for other setups.

**Fix: dropped the `context` continuation mechanism entirely and reverted
to the simpler, current `/api/chat` endpoint.** This gives up nothing that
was actually working (the continuation path never produced a single cache
hit in real testing) while removing real complexity and a subtle
correctness risk it required (detecting a different provider having
answered a turn in between). If a future Ollama release fixes CPU-backend
`/api/chat` caching — which is the endpoint its own docs say is the
intended long-term path — this provider benefits automatically with no
further changes needed.

What *is* confirmed working from the real Pi data and kept as-is:
- `keep_alive=-1` — turn 2's `load_duration` was 0.0s, confirming the model
  stayed resident between calls.
- The tight history window (`_bound_history`, capped at
  CIPHLET_OLLAMA_HISTORY_MESSAGES messages, default 6) — prompt tokens
  stayed bounded (467, then 546) instead of the original unbounded
  ~1150-1200, even though every turn still does a full evaluation.
- Switching to gemma3:1b-it-q4_K_M — generation measured at ~11.9 tok/s
  (88 tok/7.4s, 166 tok/14.0s), a real ~2.5x improvement over the previous
  gemma2:2b/qwen2.5:3b measurements (~4.6-4.7 tok/s).
- Streaming, timing diagnostics (including `prompt_eval_cached_count`,
  kept in `_format_timing` in case a future Ollama version ever reports
  one through this endpoint — harmless to keep checking for).

=== Compact local response behavior ===

The remaining latency contributor visible in the same data is response
*length*: turn 2 generated 166 tokens (vs. 88 on turn 1) at the same
per-token speed, taking proportionally longer. The local system prompt's
old "teach rather than just answer: hint before you give the answer,
explain why" framing was encouraging padded, scaffolding-heavy answers
(hints, restatements, adaptation framing) by default, even for direct
technical questions. The prompt below flips that default: give a direct,
technically accurate answer at the user's evident level with no
unsolicited beginner analogies, "in technical terms" restatements,
emojis, or follow-up questions — only teach/expand/simplify when the user
actually asks for it. This is a behavioral fix (shorter answers by
default), not a hard truncation — `num_predict` remains a safety cap, not
the primary length control.

Model: **gemma3:1b-it-q4_K_M** (unchanged this round, per explicit
instruction to keep it). qwen2.5:3b and gemma2:2b remain pull-able/settable
via config with no code change, and neither is deleted automatically.

Host/model/timeout/context/output-length/history-window are all
configuration (CIPHLET_OLLAMA_HOST, CIPHLET_OLLAMA_MODEL,
CIPHLET_OLLAMA_TIMEOUT_S, CIPHLET_OLLAMA_NUM_CTX,
CIPHLET_OLLAMA_NUM_PREDICT, CIPHLET_OLLAMA_HISTORY_MESSAGES) — nothing
owner-specific is hard-coded.
"""

from __future__ import annotations

import math
import time
from typing import Callable

from ciphlet.brain.base import BrainProvider, BrainUnavailableError, Message

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "gemma3:1b-it-q4_K_M"
DEFAULT_TIMEOUT_S = 60
DEFAULT_NUM_CTX = 2048
DEFAULT_NUM_PREDICT = 256
# Tight local raw-history window — confirmed effective on real Pi data
# (kept prompt tokens bounded at 467/546 instead of growing unbounded).
# SQLite itself keeps everything; this only bounds what a local turn
# reconstructs from scratch, which on this endpoint is every turn.
DEFAULT_HISTORY_MESSAGES = 6

# No Python-side tokenizer is available here — a deliberately conservative
# (low) characters-per-token estimate, so history is trimmed to a safe
# margin rather than risk underestimating real token count.
_CHARS_PER_TOKEN_ESTIMATE = 3.2
_CONTEXT_SAFETY_MARGIN_TOKENS = 32

# Compact, purpose-built system prompt for the local leg only. Preserves
# identity, cybersecurity-mentor role, personality, safety, and
# memory-continuity from the full shared prompt (ciphlet/learning/engine.py)
# at roughly a third of its estimated token length. Defaults to direct,
# technically-accurate answers — no unsolicited analogies, restatements,
# emojis, or follow-up questions — teaching/expansion only on request.
_LOCAL_SYSTEM_PROMPT = (
    "You are Ciphlet (SIGH-flit), a cybersecurity mentor and learning "
    "companion on a Raspberry Pi 5 — a teacher first, not a generic "
    "assistant. Default to a direct, technically accurate answer at the "
    "user's evident level. Do not automatically add beginner analogies, "
    "'in technical terms' restatements, emojis, or follow-up questions — "
    "only teach, hint, explain further, or simplify when the user actually "
    "asks for it. "
    "Personality: warm, curious, clever, a little playful; calm and "
    "focused for serious or safety-relevant topics. "
    "Cybersecurity scope: SOC, red/blue/purple team, OSINT, DFIR, "
    "networking, Linux, detection engineering, ethical hacking, scripting "
    "— authorized/legal use only, always. "
    "You have no shell, tool, or screen access here — say so rather than "
    "pretend to use one. "
    "RUNTIME FACT (overrides any other assumption): you are Ciphlet's "
    "local brain{model_suffix}, running on this Pi itself, not the cloud, "
    "and not GPT-4/ChatGPT/OpenAI. If asked your model or provider, state "
    "this plainly.{memory_note}"
)

_MEMORY_NOTE = (
    " The conversation history above, including from before a restart, is "
    "real — use it; never claim you have no memory when prior turns are "
    "shown."
)


def _build_local_system_prompt(model: str, has_history: bool) -> str:
    return _LOCAL_SYSTEM_PROMPT.format(
        model_suffix=f" ({model})",
        memory_note=_MEMORY_NOTE if has_history else "",
    )


def _estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / _CHARS_PER_TOKEN_ESTIMATE)


def _bound_history(
    system: str, messages: list[Message], num_ctx: int, num_predict: int, max_messages: int
) -> list[Message]:
    """Bound conversation history sent to the local model: a tight
    message-count cap first (confirmed effective on real Pi data), then
    the existing token-budget trim as a defensive fallback. Never touches
    SQLite/long-term memory — purely a per-call window. System prompt is
    never trimmed; most recent messages kept, oldest dropped first; at
    least the current turn is always kept."""
    if not messages:
        return []

    messages = messages[-max_messages:]

    budget = num_ctx - _estimate_tokens(system) - num_predict - _CONTEXT_SAFETY_MARGIN_TOKENS
    if budget <= 0:
        return messages[-1:]

    kept: list[Message] = []
    used = 0
    for message in reversed(messages):
        cost = _estimate_tokens(message.content) + 4  # + role/framing overhead
        if kept and used + cost > budget:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    return kept


def _get_field(obj, key: str):
    """Ollama client responses are attribute-style objects in current
    versions, dicts in some older ones — handle both without guessing
    which is installed."""
    value = getattr(obj, key, None)
    if value is None and isinstance(obj, dict):
        value = obj.get(key)
    return value


def _extract_chat_content(chunk) -> str:
    """/api/chat's streamed text delta is under 'message.content'."""
    message = _get_field(chunk, "message")
    if message is None:
        return ""
    return _get_field(message, "content") or ""


def _format_timing(final_chunk, request_started: float, first_token_at: float | None) -> str | None:
    """Built entirely from Ollama's own response metadata (total_duration,
    load_duration, prompt_eval_count/duration, eval_count/duration — real
    fields Ollama returns, in nanoseconds except the counts) plus one
    legitimately client-measured wall-clock value (time to first streamed
    token) — never invented numbers. `prompt_eval_cached_count` is
    included defensively in case a future Ollama version reports a genuine
    cache hit through this endpoint; real Pi testing has not observed one."""
    if final_chunk is None:
        return None

    def ns_to_s(value) -> float | None:
        return value / 1e9 if isinstance(value, (int, float)) else None

    load_s = ns_to_s(_get_field(final_chunk, "load_duration"))
    prompt_s = ns_to_s(_get_field(final_chunk, "prompt_eval_duration"))
    prompt_n = _get_field(final_chunk, "prompt_eval_count")
    cached_n = _get_field(final_chunk, "prompt_eval_cached_count")
    eval_s = ns_to_s(_get_field(final_chunk, "eval_duration"))
    eval_n = _get_field(final_chunk, "eval_count")
    total_s = ns_to_s(_get_field(final_chunk, "total_duration"))
    first_token_s = (first_token_at - request_started) if first_token_at else None

    parts = []
    if load_s is not None:
        parts.append(f"load {load_s:.1f}s")
    if prompt_s is not None:
        detail = f"{prompt_n} tok" if prompt_n else ""
        if cached_n:
            detail += f", {cached_n} cached"
        parts.append(f"prompt {prompt_s:.1f}s" + (f" ({detail})" if detail else ""))
    if first_token_s is not None:
        parts.append(f"first-token {first_token_s:.1f}s")
    if eval_s is not None:
        parts.append(f"gen {eval_s:.1f}s" + (f" ({eval_n} tok)" if eval_n else ""))
    if total_s is not None:
        parts.append(f"total {total_s:.1f}s")
    return ", ".join(parts) if parts else None


class OllamaBrainProvider(BrainProvider):
    def __init__(
        self,
        host: str | None = None,
        model: str | None = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        num_ctx: int = DEFAULT_NUM_CTX,
        num_predict: int = DEFAULT_NUM_PREDICT,
        history_messages: int = DEFAULT_HISTORY_MESSAGES,
    ) -> None:
        self._host = host or DEFAULT_HOST
        self._model = model or DEFAULT_MODEL
        self._timeout_s = timeout_s
        self._num_ctx = num_ctx
        self._num_predict = num_predict
        self._history_messages = history_messages
        self._client = None  # lazy: only import/construct the SDK client on first use
        # Diagnostic ground truth for the most recent successful call.
        self.last_timing: str | None = None

    @property
    def name(self) -> str:
        return "local"

    @property
    def model(self) -> str:
        return self._model

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            import ollama
        except ImportError as exc:
            raise BrainUnavailableError(
                "The 'ollama' package is not installed. Install Ciphlet's core "
                "dependencies to enable the local brain."
            ) from exc

        self._client = ollama.Client(host=self._host, timeout=self._timeout_s)
        return self._client

    def generate(
        self,
        messages: list[Message],
        *,
        system: str,  # noqa: ARG002 — intentionally not used; see module docstring
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        client = self._get_client()

        grounded_system = _build_local_system_prompt(self._model, has_history=len(messages) > 1)
        bounded_messages = _bound_history(
            grounded_system, messages, self._num_ctx, self._num_predict, self._history_messages
        )
        chat_messages = [{"role": "system", "content": grounded_system}]
        chat_messages += [{"role": m.role, "content": m.content} for m in bounded_messages]

        options = {"num_ctx": self._num_ctx, "num_predict": self._num_predict}
        request_started = time.monotonic()

        try:
            if on_token is not None:
                reply, final_chunk, first_token_at = self._stream(client, chat_messages, options, on_token)
            else:
                response = client.chat(
                    model=self._model,
                    messages=chat_messages,
                    keep_alive=-1,  # keep the model resident; never reload per turn
                    options=options,
                )
                reply = _extract_chat_content(response)
                final_chunk, first_token_at = response, None
        except Exception as exc:  # connection refused, model not pulled, timeout, etc.
            raise BrainUnavailableError(
                f"Ollama request failed ({self._host}, model '{self._model}'): {exc}. "
                "Is 'ollama serve' running and has the model been pulled "
                f"('ollama pull {self._model}')?"
            ) from exc

        self.last_timing = _format_timing(final_chunk, request_started, first_token_at)

        reply = reply.strip() if reply else ""
        if not reply:
            raise BrainUnavailableError("Ollama returned an empty or unexpected response.")
        return reply

    def _stream(self, client, chat_messages, options, on_token: Callable[[str], None]):
        stream = client.chat(
            model=self._model,
            messages=chat_messages,
            keep_alive=-1,  # keep the model resident; never reload per turn
            options=options,
            stream=True,
        )

        pieces: list[str] = []
        first_token_at: float | None = None
        final_chunk = None
        for chunk in stream:
            piece = _extract_chat_content(chunk)
            if piece:
                if first_token_at is None:
                    first_token_at = time.monotonic()
                pieces.append(piece)
                on_token(piece)
            final_chunk = chunk  # the last chunk (done=True) carries the timing metadata

        return "".join(pieces), final_chunk, first_token_at
