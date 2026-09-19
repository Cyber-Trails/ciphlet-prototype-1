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

import re
import sys
import threading
from collections import deque
from math import gcd
from typing import Callable

from ciphlet.voice.base import AudioProcessor, STTProvider, TTSProvider, VoiceUnavailableError, WakeProvider

# Canonical rate of everything downstream of capture: webrtcvad (480-sample /
# 30 ms frames), openWakeWord (16 kHz, 1280-sample windows), and VOSK
# (KaldiRecognizer(model, 16000)). Capture hardware is NOT required to run at
# this rate — see _open_input_stream, which resamples to it when needed.
SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480 samples/frame — valid webrtcvad frame size
SILENCE_FRAMES_TO_STOP = 20  # ~600ms of silence ends an utterance
NO_SPEECH_TIMEOUT_FRAMES = 200  # ~6s: give up if nothing is said after the wake word
MAX_UTTERANCE_FRAMES = 500  # ~15s hard cap on one utterance
POST_SPEECH_HOLDOFF_FRAMES = 15  # ~450ms of mic ignored after TTS ends, so room echo can't re-trigger wake
WAKE_TAIL_SETTLE_FRAMES = 5  # ~150ms of silence = the wake phrase itself has ended
WAKE_TAIL_MAX_FRAMES = 40  # ~1.2s: if speech never pauses, the user is talking straight on into their request
ECHO_MIN_WORDS = 3  # a shorter transcript is never treated as Ciphlet hearing itself
ECHO_OVERLAP = 0.8  # fraction of transcript words found in Ciphlet's last reply => it heard itself

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

# Measured on the real Pi (speaker beside the mic): Ciphlet's own voice reaches
# the mic ~14x louder than room noise and the VAD flags it as continuous speech
# for seconds, so VAD-only barge-in cut every reply off after ~1.5 s. An
# interruption must therefore ALSO be clearly louder than the echo: frame rms >=
# BARGE_IN_GATE x the loudest echo seen so far in this reply. The first
# BARGE_IN_WARMUP_FRAMES (~1.5 s) of a reply only learn the echo level.
BARGE_IN_GATE = 2.5
BARGE_IN_WARMUP_FRAMES = 50


class BargeInDetector:
    """Decides, frame by frame while Ciphlet is speaking, whether the user is
    interrupting: VAD says speech AND the frame is markedly louder than the
    echo level learned so far, sustained for `frames` frames. `frames` <= 0
    disables barge-in; `gate` <= 0 falls back to VAD-only."""

    def __init__(self, frames: int = BARGE_IN_DEBOUNCE_FRAMES, gate: float = BARGE_IN_GATE, warmup: int = BARGE_IN_WARMUP_FRAMES) -> None:
        self._frames, self._gate, self._warmup = frames, gate, warmup
        self.reset()

    def reset(self) -> None:
        """Call when Ciphlet starts a new reply."""
        self._baseline = 0.0
        self._since_onset: int | None = None  # frames since the echo's first speech-like frame
        self._run = 0

    def update(self, speech: bool, rms: float) -> bool:
        if self._frames <= 0:
            return False
        if self._since_onset is None:
            # Piper's audio starts ~1 s AFTER the reply is issued (synthesis lag), so the
            # warm-up must start at the echo's onset — not at the start of the reply, or it
            # would learn only silence and the echo itself would look like an interruption.
            if not speech:
                self._baseline = max(self._baseline, rms)
                return False
            self._since_onset = 0
        self._since_onset += 1
        if self._since_onset <= self._warmup:  # learn the echo level; never interrupt this early
            self._baseline = max(self._baseline, rms)
            return False
        if speech and rms >= self._gate * self._baseline:
            self._run += 1
            return self._run >= self._frames
        self._run = 0
        self._baseline = max(self._baseline, rms)  # ratchet up only on frames that are not an interruption
        return False


def _get_sounddevice():
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise VoiceUnavailableError(
            "'sounddevice' is not installed. Install Ciphlet's voice extras on the Pi."
        ) from exc
    return sd


# Capture rates tried, in order, when opening the mic. 16 kHz first: if the
# device (or an ALSA plug/pulse route) already supports it, nothing extra is
# needed and behavior is exactly as before. USB mics often expose only 44.1/48
# kHz (e.g. `arecord --dump-hw-params` -> RATE: [44100 48000]); 48 kHz is a
# clean 3:1 to 16 kHz, so it is preferred over 44.1. The device's own default
# rate is tried last.
_CAPTURE_RATE_CANDIDATES = (SAMPLE_RATE, 48000, 44100)
_PA_INVALID_SAMPLE_RATE = -9997  # PortAudio paInvalidSampleRate

_input_rate_cache: dict = {}  # device -> rate that last opened successfully
_announced_rates: set = set()


class _StreamResampler:
    """Stateful mono int16 sample-rate converter (streaming, numpy only).

    Band-limited (Kaiser-windowed sinc) interpolation with the filter state
    carried across calls, so feeding audio in arbitrary block sizes yields the
    same output as one big call — no per-chunk edge glitches, which would
    otherwise recur every 30 ms and hurt VAD/wake/STT. The cutoff sits just
    under the output Nyquist so content above it is filtered out rather than
    aliased down into the speech band. Cost is a few tens of thousands of
    multiply-adds per 30 ms frame — negligible next to the models.
    """

    _ZERO_CROSSINGS = 8
    _KAISER_BETA = 8.0
    _CUTOFF = 0.91  # fraction of the output Nyquist

    def __init__(self, in_rate: int, out_rate: int) -> None:
        import numpy as np

        g = gcd(in_rate, out_rate)
        self._up = out_rate // g
        self._down = in_rate // g
        fc = 0.5 * min(1.0, out_rate / in_rate) * self._CUTOFF  # cycles per input sample
        half = int(np.ceil(self._ZERO_CROSSINGS / (2 * fc)))  # filter half-width, in input samples
        self._half = half
        self._taps = np.arange(-half + 1, half + 1)
        # One weight row per fractional phase (out sample n sits at input time
        # n*down/up; the fractional part repeats every `up` outputs).
        tau = (np.arange(self._up)[:, None] / self._up) - self._taps[None, :]
        window = np.i0(self._KAISER_BETA * np.sqrt(np.clip(1.0 - (tau / half) ** 2, 0.0, None))) / np.i0(self._KAISER_BETA)
        weights = 2 * fc * np.sinc(2 * fc * tau) * window
        weights /= weights.sum(axis=1, keepdims=True)  # exact unity DC gain per phase
        self._weights = weights.astype(np.float32)
        self._buf = np.zeros(half, dtype=np.float32)  # history; index 0 is input time _buf_start
        self._buf_start = -half
        self._next = 0  # index of the next output sample to produce

    def process(self, samples):
        """Feed a 1-D int16 block; return the newly available 1-D int16 output."""
        import numpy as np

        half, up, down = self._half, self._up, self._down
        self._buf = np.concatenate((self._buf, samples.astype(np.float32)))
        total = self._buf_start + len(self._buf)
        # Emit only outputs whose full filter support (up to `half` samples
        # ahead) has arrived — a fixed, sub-millisecond latency.
        last = ((total - half) * up - 1) // down
        if last < self._next:
            return np.zeros(0, dtype=np.int16)
        n = np.arange(self._next, last + 1, dtype=np.int64)
        pos = n * down
        base, phase = pos // up, pos % up
        gathered = self._buf[(base - self._buf_start)[:, None] + self._taps[None, :]]
        out = (gathered * self._weights[phase]).sum(axis=1)
        self._next = last + 1
        drop = (self._next * down) // up - half + 1 - self._buf_start
        if drop > 0:
            self._buf = self._buf[drop:]
            self._buf_start += drop
        return np.clip(np.rint(out), -32768, 32767).astype(np.int16)


class _ResamplingInputStream:
    """Wraps a sounddevice InputStream that captures at `in_rate` and exposes
    the same read/stop/close surface at SAMPLE_RATE, so the pipeline's readers
    (which ask for FRAME_SAMPLES 16 kHz frames) don't change."""

    def __init__(self, stream, in_rate: int, out_rate: int = SAMPLE_RATE) -> None:
        import numpy as np

        self._stream = stream
        self._in_rate = in_rate
        self._out_rate = out_rate
        self._resampler = _StreamResampler(in_rate, out_rate)
        self._pending = np.zeros(0, dtype=np.int16)  # resampled, not yet returned

    def read(self, frames: int):
        import numpy as np

        native = -(-frames * self._in_rate // self._out_rate)  # ceil
        overflowed = False
        while len(self._pending) < frames:
            data, over = self._stream.read(native)
            overflowed = overflowed or bool(over)
            self._pending = np.concatenate((self._pending, self._resampler.process(data.reshape(-1))))
        out = self._pending[:frames].reshape(-1, 1).copy()
        self._pending = self._pending[frames:]
        return out, overflowed

    def stop(self) -> None:
        self._stream.stop()

    def close(self) -> None:
        self._stream.close()


def _is_invalid_sample_rate(exc: Exception) -> bool:
    return _PA_INVALID_SAMPLE_RATE in exc.args[1:2] or "Invalid sample rate" in str(exc)


def _capture_rate_candidates(sd, device) -> list[int]:
    rates: list[int] = []
    if device in _input_rate_cache:
        rates.append(_input_rate_cache[device])
    rates.extend(_CAPTURE_RATE_CANDIDATES)
    try:
        rates.append(int(sd.query_devices(device, "input")["default_samplerate"]))
    except Exception:
        pass  # no/invalid device: opening below reports it properly
    return list(dict.fromkeys(rates))


def _open_input_stream(device: str | int | None):
    """Open+start a mono 16-bit input stream that delivers SAMPLE_RATE audio.

    The microphone is opened at a rate it actually supports (see
    _CAPTURE_RATE_CANDIDATES) and, if that isn't 16 kHz, resampled to 16 kHz —
    the format the VAD, wake-word model and STT require. A PortAudio-level
    failure (no mic, wrong device, device busy) becomes a clear, actionable
    VoiceUnavailableError instead of a raw driver traceback."""
    sd = _get_sounddevice()
    tried: list[int] = []
    for rate in _capture_rate_candidates(sd, device):
        stream = None
        try:
            stream = sd.InputStream(samplerate=rate, channels=1, dtype="int16", device=device)
            stream.start()
        except sd.PortAudioError as exc:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if _is_invalid_sample_rate(exc):
                tried.append(rate)  # this rate isn't supported by the device; try the next
                continue
            raise VoiceUnavailableError(
                f"Could not open audio input device ({exc}). Check the microphone is connected, or set "
                "CIPHLET_AUDIO_INPUT_DEVICE — list devices with 'python3 -m sounddevice'."
            ) from exc
        _input_rate_cache[device] = rate
        if rate == SAMPLE_RATE:
            return stream
        if (device, rate) not in _announced_rates:
            _announced_rates.add((device, rate))
            print(f"(audio input opened at {rate} Hz — the device doesn't support {SAMPLE_RATE} Hz; resampling)")
        return _ResamplingInputStream(stream, rate)
    where = f"'{device}'" if device is not None else "the default input device"
    raise VoiceUnavailableError(
        f"Audio input device {where} rejected every sample rate Ciphlet tried ({', '.join(map(str, tried))} Hz). "
        "Check what it supports (e.g. 'arecord --dump-hw-params -D hw:2,0 /dev/null') and select the right "
        "microphone with CIPHLET_AUDIO_INPUT_DEVICE — list devices with 'python3 -m sounddevice'."
    )


def _is_self_echo(heard: str, last_reply: str) -> bool:
    """True if `heard` is (nearly) just Ciphlet's own last reply coming back in
    through the mic — with no hardware echo cancellation, barge-in can trigger
    on its own TTS and would otherwise transcribe and answer itself."""
    words = re.findall(r"[a-z0-9']+", heard.lower())
    if len(words) < ECHO_MIN_WORDS or not last_reply:
        return False
    reply_words = set(re.findall(r"[a-z0-9']+", last_reply.lower()))
    return sum(w in reply_words for w in words) / len(words) >= ECHO_OVERLAP


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
        barge_in_frames: int = BARGE_IN_DEBOUNCE_FRAMES,
        wake_label: str = '"Hey Ciphlet"',
        barge_in_gate: float = BARGE_IN_GATE,
        barge_in_warmup_frames: int = BARGE_IN_WARMUP_FRAMES,
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
        # Consecutive speech frames needed to interrupt TTS; 0 disables
        # barge-in (use if the speaker bleeds into the mic — see --selftest).
        self._barge_in_frames = barge_in_frames
        self._barge = BargeInDetector(barge_in_frames, barge_in_gate, barge_in_warmup_frames)
        self._last_reply = ""
        self._wake_label = wake_label

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

    def _reset_wake(self) -> None:
        self._wake_buffer.clear()
        self._wake.reset()

    def run_forever(self) -> None:
        import numpy as np

        # Load models BEFORE the mic opens: a lazily-loaded wake model stalls the
        # loop for seconds on its first window, and audio in that gap is lost.
        self._wake.load()
        self._stt.load()
        print(f"Ciphlet is listening for {self._wake_label}... (Ctrl+C to stop)")
        stream = _open_input_stream(self._input_device)
        recent: deque = deque(maxlen=max(self._barge_in_frames, 1))  # those frames, kept so the interruption isn't clipped
        was_speaking = False
        holdoff = 0
        try:
            while True:
                chunk, _ = stream.read(FRAME_SAMPLES)
                conditioned = self._audio.condition(chunk.tobytes())

                if self._speaking.is_set():
                    if not was_speaking:
                        self._barge.reset()  # a new reply just started: relearn the echo level
                    was_speaking = True
                    # Interruption path (§4.6): listen while Ciphlet talks and
                    # barge in on sustained speech that is clearly louder than
                    # the echo of Ciphlet's own voice (see BargeInDetector; no
                    # hardware AEC here).
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                    recent.append(chunk.copy())  # latest frames, so the interruption's first words aren't clipped
                    if self._barge.update(bool(self._audio.is_speech(conditioned)), rms):
                        self._tts.stop()
                        self._speaking.clear()
                        self._respond(self._capture_utterance(stream, list(recent)), echo_guard=True)
                        recent.clear()
                        was_speaking = False
                        self._reset_wake()
                    continue

                if was_speaking:  # playback just finished on its own
                    was_speaking = False
                    holdoff = POST_SPEECH_HOLDOFF_FRAMES
                    self._reset_wake()
                if holdoff > 0:
                    holdoff -= 1
                    continue

                if self._check_wake(conditioned):
                    print("(wake word detected)")
                    self._respond(self._capture_utterance(stream, after_wake=True))
                    self._reset_wake()
        finally:
            stream.stop()
            stream.close()

    def _capture_utterance(self, stream, prefix: list | None = None, after_wake: bool = False) -> bytes:
        """Record until ~600ms of silence *after speech has started*. Waits up to
        NO_SPEECH_TIMEOUT_FRAMES for the user to begin (so a pause after the
        wake word doesn't lose the turn), and caps total length.

        after_wake: the wake phrase's own trailing audio would otherwise count as
        "speech started" and a natural pause before the request would then end
        the capture with nothing in it. So first let the wake phrase finish (a
        short silence) and drop it; if the user never pauses, keep it all — they
        are talking straight on into the request."""
        import numpy as np

        frames = list(prefix or [])
        started = bool(frames)  # barge-in: the interrupting speech is already in `prefix`
        if after_wake:
            tail: list = []
            quiet = 0
            paused = False
            while len(tail) < WAKE_TAIL_MAX_FRAMES:
                chunk, _ = stream.read(FRAME_SAMPLES)
                tail.append(chunk.copy())
                quiet = 0 if self._audio.is_speech(self._audio.condition(chunk.tobytes())) else quiet + 1
                if quiet >= WAKE_TAIL_SETTLE_FRAMES:
                    paused = True
                    break
            if not paused:
                frames, started = tail, True  # continuous speech: keep the wake phrase + request together
        waited = 0
        silence_run = 0
        while len(frames) < MAX_UTTERANCE_FRAMES:
            chunk, _ = stream.read(FRAME_SAMPLES)
            conditioned = self._audio.condition(chunk.tobytes())
            frames.append(chunk.copy())
            if self._audio.is_speech(conditioned):
                started = True
                silence_run = 0
            elif started:
                silence_run += 1
                if silence_run >= SILENCE_FRAMES_TO_STOP:
                    break
            else:
                waited += 1
                if waited >= NO_SPEECH_TIMEOUT_FRAMES:
                    return b""  # never started talking
        return np.concatenate(frames, axis=0).tobytes() if frames else b""

    def _respond(self, audio: bytes, echo_guard: bool = False) -> None:
        if not audio:
            print("(heard nothing — no speech after the wake word)")
            return
        text = self._stt.transcribe(audio)
        if not text:
            print("(heard nothing I could make out)")
            return
        if echo_guard and _is_self_echo(text, self._last_reply):
            print("(ignored — that was my own voice coming back in through the mic)")
            return

        print(f"You: {text}")
        reply = self._on_utterance(text)
        self._last_reply = reply
        print(f"Ciphlet: {reply}")
        if self._on_reply:
            self._on_reply(reply)

        self._speaking.set()
        threading.Thread(target=self._speak_then_clear, args=(reply,), daemon=True).start()

    def _speak_then_clear(self, reply: str) -> None:
        try:
            self._tts.speak(reply)
        except Exception as exc:  # runs in a thread: surface it instead of dying silently
            print(f"(speech output failed: {exc})", file=sys.stderr)
        finally:
            self._speaking.clear()
