# Third-Party Notices — Donor Sources (Clean Rebuild / Adopt-Adapt)

This records the upstream projects used as implementation donors for
Ciphlet's local-intelligence and voice pipeline, per the clean-rebuild
instruction to preserve required license/attribution notices. Donor repos
were cloned into a temporary workspace for inspection only and removed
afterward — none are vendored into this tree.

## Donor sources and licenses (checked directly against each repo)

| Repo | License | Used for |
|---|---|---|
| [duckida/RPi-local-voice-assistant](https://github.com/duckida/RPi-local-voice-assistant) | **None declared** (GitHub reports no license; no LICENSE file in the repo) | Evidence only — see below |
| [eric-rolph/pi5-local-voice-assistant](https://github.com/eric-rolph/pi5-local-voice-assistant) | **MIT** (`Copyright (c) 2025 GLADOS Voice Assistant Contributors`) | Evidence + pattern reference |
| [Ambidiosidad/jarvis](https://github.com/Ambidiosidad/jarvis) | **Apache License 2.0** | One adapted technical pattern (see below) |

## What was adopted from each

### duckida/RPi-local-voice-assistant — evidence only, no code copied
No license is declared on this repository, so no source code or text from
it is reproduced or adapted here. It was used strictly as **evidence** that
a specific combination of proven, free, local components works on
Raspberry Pi hardware: Ollama as a persistent local LLM server (with
`keep_alive=-1` to keep the model resident, avoiding a reload per turn),
VOSK for offline STT, and a press-button push-to-talk interaction model.
Ciphlet's own `ciphlet/brain/ollama_provider.py` and
`ciphlet/voice/providers.py` (`VoskSTT`) are independently written against
the public Ollama and VOSK APIs, informed by (not copied from) this
project's tool choices.

### eric-rolph/pi5-local-voice-assistant — MIT, evidence + pattern reference
Used as evidence that **`gemma2:2b-instruct-q4_0` via Ollama** is a
practical, donor-recommended model for a Raspberry Pi 5 ("optimized for
Pi 5" per its README) — this replaced Ciphlet's earlier forced Qwen2.5-3B
configuration as the new default `CIPHLET_OLLAMA_MODEL`. Also confirmed
that shelling out to the `piper` CLI (installed via the `piper-tts` pip
package) for TTS synthesis is the proven approach — Ciphlet's existing
`PiperTTS` provider already used this exact pattern and needed no change.
No source code from this repository is reproduced verbatim; per MIT terms,
this copyright notice is preserved here as the attribution record for the
design decisions it informed.

### Ambidiosidad/jarvis — Apache-2.0, one adapted technical pattern
`extensions/voice/wake_word.py` demonstrates the correct audio-chunking
requirement for openWakeWord: the model expects ~80ms (1280-sample @16kHz)
windows, fed from a buffer sized specifically for that, decoupled from
whatever frame size the rest of the pipeline's VAD uses. Ciphlet's own
wake-word integration had a known, previously-documented gap here (VAD-sized
480-sample frames were being fed directly to `predict()`, which "works
mechanically but hurts real accuracy"). This specific technical
pattern — accumulate into a correctly-sized window before calling the wake
model, independent of the VAD frame size — was adapted (not copied
verbatim; Ciphlet's implementation is a single-stream buffer/accumulator in
`ciphlet/voice/pipeline.py`'s `HandsFreeVoiceSession._check_wake`, not
jarvis's separate-PyAudio-stream architecture) into
`ciphlet/voice/pipeline.py` (`WAKE_CHUNK_SAMPLES`, `_check_wake`), with an
inline comment crediting the source. Per Apache-2.0 §4, this NOTICE file
serves as the required attribution for that adapted pattern; the original
project's Apache-2.0 license text governs the donor repository itself,
unmodified and not redistributed here.

## What was NOT adopted

`Ambidiosidad/jarvis`'s broader architecture (Docker/Nomad-orchestrated
microservices, an AdonisJS/Node.js admin panel, motors/vision extensions)
was inspected but not used — it is a much larger, differently-scoped
platform than a single-process Pi 5 voice assistant, and adopting it would
have meant "rebuilding equivalent infrastructure" rather than reusing a
proven, appropriately-sized implementation. Only the one wake-word chunking
pattern above was taken from it.

## Workspace cleanup

All three donor repositories were cloned into a temporary directory
(`/tmp/ciphlet_donors`) for inspection and removed after the above was
extracted — no donor clone, `.git` history, or build artifact from them is
part of this repository.
