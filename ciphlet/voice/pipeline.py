"""Voice pipeline (§20B): wires WakeProvider/AudioProcessor/STTProvider/
TTSProvider around the Orchestrator, in the two supported shapes:

- PTTVoiceSession: push-to-talk. The required fallback/recovery mechanism
  (§4.1) and the simplest path to bring up on real hardware first
  (§24 Stage 1-2 engineering bring-up).
- HandsFreeVoiceSession: wake-word + VAD always-listening loop with true
  barge-in. This is the primary interaction model (§4.1) Ciphlet is built
  toward; PTT is not a substitute for it (§25).

Both are optional at runtime: if sounddevice/numpy or a provider's ML
dependency isn't installed, VoiceUnavailableError propagates up with a clear
message and the caller (main.py) falls back to text mode rather than crashing.
"""

from __future__ import annotations

import threading
from typing import Callable

from ciphlet.voice.base import AudioProcessor, STTProvider, TTSProvider, VoiceUnavailableError, WakeProvider

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples/frame — valid webrtcvad frame size
SILENCE_FRAMES_TO_STOP = 20  # ~600ms of silence ends an utterance

# openWakeWord expects ~80ms (1280-sample @16kHz) windows, not the 480-sample
# VAD frame size above — feeding it undersized frames (an earlier known gap
# in this file) works mechanically but hurts real accuracy. Pattern (a small
# accumulator buffer feeding correctly-sized windows to the wake model,
# decoupled from the VAD frame size) informed by Ambidiosidad/jarvis's
# extensions/voice/wake_word.py (Apache-2.0) — see docs/THIRD_PARTY_NOTICES.md.
WAKE_CHUNK_SAMPLES = 1280

# Self-hearing / false-reactivation mitigation (§4.6, §20B): there is no
# hardware acoustic-echo cancellation here (AudioProcessor.condition() is a
# pass-through placeholder — see voice/providers.py), so Ciphlet's own voice
# coming back in through the mic while it talks would otherwise look
# identical to a real interruption. Requiring several consecutive speech
# frames (not just one) before treating it as a real barge-in is a cheap,
# honest heuristic — not true AEC — that filters out short echo/bleed
# blips while still allowing a genuine, sustained interruption through.
BARGE_IN_DEBOUNCE_FRAMES = 3  # ~90ms of sustained speech at FRAME_MS=30


def _get_sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise VoiceUnavailableError(
            "'sounddevice' is not installed. Install Ciphlet's voice extras on the Pi."
        ) from exc
    return sd


def _open_input_stream(device: str | int | None):
    """Open+start a mono 16-bit input stream, converting a PortAudio-level
    failure (no mic, wrong device, device busy) into a clear, actionable
    VoiceUnavailableError instead of a raw driver traceback."""
    sd = _get_sounddevice()
    try:
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", device=device)
        stream.start()
    except sd.PortAudioError as exc:
        raise VoiceUnavailableError(
            f"Could not open audio input device ({exc}). Check the microphone is connected, or set "
            "CIPHLET_AUDIO_INPUT_DEVICE — list devices with 'python3 -m sounddevice'."
        ) from exc
    return stream


class PTTVoiceSession:
    """Push-to-talk: press Enter, speak, press Enter again to send."""

    def __init__(
        self,
        stt: STTProvider,
        tts: TTSProvider,
        on_utterance: Callable[[str], str],
        input_device: str | int | None = None,
    ) -> None:
        self._stt = stt
        self._tts = tts
        self._on_utterance = on_utterance
        self._input_device = input_device

    def run_turn(self) -> None:
        import numpy as np

        input("Press Enter, then speak. Press Enter again to stop recording...")
        frames: list[np.ndarray] = []
        stop_event = threading.Event()

        def _wait_for_enter() -> None:
            input()
            stop_event.set()

        threading.Thread(target=_wait_for_enter, daemon=True).start()

        print("Listening... press Enter to stop.")
        stream = _open_input_stream(self._input_device)
        try:
            while not stop_event.is_set():
                chunk, _ = stream.read(FRAME_SAMPLES)
                frames.append(chunk.copy())
        finally:
            stream.stop()
            stream.close()

        audio = np.concatenate(frames, axis=0).tobytes() if frames else b""
        text = self._stt.transcribe(audio)
        if not text:
            print("(heard nothing)")
            return

        print(f"You: {text}")
        reply = self._on_utterance(text)
        print(f"Ciphlet: {reply}")
        self._tts.speak(reply)


class HandsFreeVoiceSession:
    """Wake-word + VAD always-listening loop with true barge-in (§4.1, §4.6,
    §20B). Requires every voice provider (wake, VAD, STT, TTS) to actually be
    installed and working on real hardware."""

    def __init__(
        self,
        audio: AudioProcessor,
        wake: WakeProvider,
        stt: STTProvider,
        tts: TTSProvider,
        on_utterance: Callable[[str], str],
        input_device: str | int | None = None,
        on_reply: Callable[[str], None] | None = None,
    ) -> None:
        self._audio = audio
        self._wake = wake
        self._stt = stt
        self._tts = tts
        self._on_utterance = on_utterance
        self._input_device = input_device
        # Optional hook fired with each reply, right before it's spoken —
        # lets the caller (main.py) print [brain]/timing info the same way
        # text mode and PTT already do, without this module importing
        # Orchestrator itself (§20B: providers/pipeline stay decoupled).
        self._on_reply = on_reply
        self._speaking = threading.Event()
        self._wake_buffer = bytearray()

    def _check_wake(self, conditioned: bytes) -> bool:
        """Accumulate VAD-sized frames into openWakeWord-sized windows
        before calling detect() — see WAKE_CHUNK_SAMPLES above."""
        self._wake_buffer.extend(conditioned)
        chunk_bytes = WAKE_CHUNK_SAMPLES * 2  # int16 = 2 bytes/sample
        detected = False
        while len(self._wake_buffer) >= chunk_bytes:
            window = bytes(self._wake_buffer[:chunk_bytes])
            del self._wake_buffer[:chunk_bytes]
            if self._wake.detect(window):
                detected = True
        return detected

    def run_forever(self) -> None:
        print('Ciphlet is listening for "Hey Ciphlet"... (Ctrl+C to stop)')
        stream = _open_input_stream(self._input_device)
        speech_run = 0  # consecutive speech frames seen while Ciphlet is talking — see BARGE_IN_DEBOUNCE_FRAMES
        try:
            while True:
                chunk, _ = stream.read(FRAME_SAMPLES)
                conditioned = self._audio.condition(chunk.tobytes())

                if self._speaking.is_set():
                    # Interruption path (§4.6): listen while Ciphlet talks,
                    # barge in once real speech is sustained (debounced
                    # against self-heard TTS bleed-through — see
                    # BARGE_IN_DEBOUNCE_FRAMES above; no hardware AEC here).
                    if self._audio.is_speech(conditioned):
                        speech_run += 1
                        if speech_run >= BARGE_IN_DEBOUNCE_FRAMES:
                            self._tts.stop()
                            self._speaking.clear()
                            speech_run = 0
                            self._respond(self._capture_utterance(stream))
                    else:
                        speech_run = 0
                    continue

                speech_run = 0
                if self._check_wake(conditioned):
                    print("(wake word detected)")
                    self._respond(self._capture_utterance(stream))
        finally:
            stream.stop()
            stream.close()

    def _capture_utterance(self, stream) -> bytes:
        import numpy as np

        frames = []
        silence_run = 0
        while silence_run < SILENCE_FRAMES_TO_STOP:
            chunk, _ = stream.read(FRAME_SAMPLES)
            conditioned = self._audio.condition(chunk.tobytes())
            frames.append(chunk.copy())
            silence_run = 0 if self._audio.is_speech(conditioned) else silence_run + 1
        return np.concatenate(frames, axis=0).tobytes() if frames else b""

    def _respond(self, audio: bytes) -> None:
        text = self._stt.transcribe(audio)
        if not text:
            return

        print(f"You: {text}")
        reply = self._on_utterance(text)
        print(f"Ciphlet: {reply}")
        if self._on_reply:
            self._on_reply(reply)

        self._speaking.set()
        threading.Thread(target=self._speak_then_clear, args=(reply,), daemon=True).start()

    def _speak_then_clear(self, reply: str) -> None:
        try:
            self._tts.speak(reply)
        finally:
            self._speaking.clear()
