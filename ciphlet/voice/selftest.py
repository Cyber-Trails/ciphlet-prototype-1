"""`ciphlet voice --selftest` — one integrated hardware check of the whole voice
stack (config -> speaker/Piper -> mic/resampling/VAD/VOSK -> wake model -> the
speaker-into-mic bleed that decides whether barge-in is safe).

It is meant to be run ON the Pi with the real mic and speaker. It needs no
brain/network. Every stage reports PASS / WARN / FAIL with an actionable
detail, and the exit code is non-zero only if a stage FAILs.
"""

from __future__ import annotations

import os
import sys
import threading

from ciphlet.voice import pipeline
from ciphlet.voice.base import VoiceUnavailableError

SPEAKER_PHRASE = "Ciphlet voice check. If you can hear this, my speaker is working."
ECHO_PHRASE = (
    "This is a longer sentence that plays through the speaker while the microphone listens, "
    "so I can measure how much of my own voice comes back in."
)
RECORD_SECONDS = 4
LOW_LEVEL_PEAK = 500  # int16 peak below this = mic is barely picking anything up
MAX_DEBOUNCE_WORTH_TRYING = 15  # ~450 ms; longer self-heard runs can't be debounced away


def longest_run(flags) -> int:
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def recommend_barge_in(longest_echo_run: int, current: int) -> int:
    """Barge-in frames that stop the speaker's own bleed triggering an
    interruption: keep `current` if it already clears the measured bleed, add a
    little headroom over a short bleed, and disable (0) if the bleed is
    sustained (no debounce can separate that from a real interruption)."""
    if longest_echo_run < current:
        return current
    if longest_echo_run <= MAX_DEBOUNCE_WORTH_TRYING:
        return longest_echo_run + 3
    return 0


def _levels(frames) -> tuple[int, float]:
    import numpy as np

    if not frames:
        return 0, 0.0
    audio = np.concatenate(frames, axis=0).astype(np.float64)
    return int(np.abs(audio).max()), float(np.sqrt((audio**2).mean()))


class _Report:
    def __init__(self) -> None:
        self.results: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str) -> None:
        self.results.append((status, name, detail))
        print(f"  [{status}] {name}: {detail}")

    @property
    def failed(self) -> bool:
        return any(status == "FAIL" for status, _, _ in self.results)


def run_selftest(
    config,
    *,
    tts=None,
    stt=None,
    audio=None,
    wake=None,
    open_stream=None,
    ask=input,
    interactive: bool | None = None,
) -> int:
    from ciphlet.voice.providers import OpenWakeWordProvider, PiperTTS, VoskSTT, WebRTCVadAudioProcessor

    interactive = sys.stdin.isatty() if interactive is None else interactive
    open_stream = open_stream or pipeline._open_input_stream
    report = _Report()

    print("== Ciphlet voice self-test ==")
    print(f"  mic device:     {config.audio_input_device if config.audio_input_device is not None else '(default)'}")
    print(f"  speaker device: {config.audio_output_device or '(default)'}")

    # 1. Config / model files ------------------------------------------------
    piper_path, vosk_path = config.piper_model_path, config.vosk_model_path
    missing = []
    if not piper_path or not os.path.isfile(piper_path):
        missing.append(f"Piper voice model ({piper_path or 'CIPHLET_PIPER_MODEL unset'})")
    elif not os.path.isfile(piper_path + ".json"):
        missing.append(f"Piper voice config ({piper_path}.json)")
    if not vosk_path or not os.path.isdir(vosk_path):
        missing.append(f"VOSK model dir ({vosk_path or 'CIPHLET_VOSK_MODEL_PATH unset'})")
    if config.wake_model_path and not os.path.isfile(config.wake_model_path):
        missing.append(f"wake model ({config.wake_model_path})")
    if missing:
        report.add("FAIL", "config", "missing: " + "; ".join(missing) + " — run deploy/install_voice.sh")
        return _finish(report)
    report.add("PASS", "config", "Piper voice, VOSK model and wake setting found")

    tts = tts or PiperTTS(model_path=piper_path, output_device=config.audio_output_device)
    stt = stt or VoskSTT(model_path=vosk_path)
    audio = audio or WebRTCVadAudioProcessor()
    wake = wake or OpenWakeWordProvider(model_path=config.wake_model_path)

    # 2. Speaker -------------------------------------------------------------
    print("\n-- Speaker: you should hear a spoken sentence now --")
    speaker_ok = True
    try:
        tts.speak(SPEAKER_PHRASE)
    except VoiceUnavailableError as exc:
        report.add("FAIL", "speaker", str(exc))
        speaker_ok = False
    else:
        heard = True
        if interactive:
            heard = ask("  Did you hear it clearly? [Y/n] ").strip().lower() not in ("n", "no")
        speaker_ok = heard
        if heard:
            report.add("PASS", "speaker", "Piper synthesized and played" + (" (heard)" if interactive else " (no error; not confirmed by ear)"))
        else:
            report.add(
                "FAIL",
                "speaker",
                "played without error but you heard nothing — wrong output device or muted. Check 'aplay -l', "
                "'alsamixer -c <card>' (unmute/raise volume), and set CIPHLET_AUDIO_OUTPUT_DEVICE "
                "(re-run deploy/install_voice.sh to auto-detect).",
            )

    # 3. Microphone -> resampling -> VAD -> VOSK -----------------------------
    frames_16k: list = []
    print(f"\n-- Microphone: speak a sentence for the next {RECORD_SECONDS} seconds --")
    if interactive:
        ask("  Press Enter, then say e.g. 'hello ciphlet what time is it'... ")
    mic_ok = False
    try:
        stream = open_stream(config.audio_input_device)
    except VoiceUnavailableError as exc:
        report.add("FAIL", "microphone", str(exc))
        stream = None
    if stream is not None:
        mic_ok = True
        try:
            n_frames = RECORD_SECONDS * 1000 // pipeline.FRAME_MS
            print("  Listening...")
            for _ in range(n_frames):
                chunk, _ = stream.read(pipeline.FRAME_SAMPLES)
                frames_16k.append(chunk.copy())
        finally:
            stream.stop()
            stream.close()
        peak, rms = _levels(frames_16k)
        speech_frames = sum(audio.is_speech(audio.condition(f.tobytes())) for f in frames_16k)
        text = stt.transcribe(b"".join(f.tobytes() for f in frames_16k))
        detail = f"peak {peak}, rms {rms:.0f}, speech in {speech_frames}/{len(frames_16k)} frames; VOSK heard: {text!r}"
        if peak < LOW_LEVEL_PEAK:
            mic_ok = False
            report.add("FAIL", "microphone", detail + " — signal is almost silent: raise capture gain (alsamixer -c <card>, F4) or check the mic")
        elif not text:
            report.add("WARN", "microphone", detail + " — captured audio but VOSK heard no words (speak louder/closer, or nothing was said)")
        else:
            report.add("PASS", "microphone+VAD+VOSK", detail)

    # 4. Wake model ----------------------------------------------------------
    print("\n-- Wake word model --")
    try:
        windows = 0
        wake.reset()
        flat = b"".join(f.tobytes() for f in frames_16k) or bytes(pipeline.WAKE_CHUNK_SAMPLES * 2 * 5)
        step = pipeline.WAKE_CHUNK_SAMPLES * 2
        for i in range(0, len(flat) - step + 1, step):
            wake.detect(flat[i : i + step])
            windows += 1
        wake.reset()
    except VoiceUnavailableError as exc:
        report.add("FAIL", "wake model", str(exc))
    else:
        phrases = "your trained model" if config.wake_model_path else '"hey jarvis", "alexa", "hey mycroft" or "hey rhasspy"'
        report.add("PASS", "wake model", f"loaded and ran on {windows} windows; say {phrases} to wake it")

    # 5. Speaker-into-mic bleed (decides whether barge-in is safe) -----------
    print("\n-- Speaker->mic bleed: stay QUIET while I speak (measures barge-in safety) --")
    if not (mic_ok and speaker_ok):
        report.add("WARN", "barge-in", "skipped (needs a working mic and speaker)")
    else:
        try:
            stream = open_stream(config.audio_input_device)
            speaker = threading.Thread(target=lambda: _safe_speak(tts, ECHO_PHRASE), daemon=True)
            speaker.start()
            flags = []
            try:
                while speaker.is_alive():
                    chunk, _ = stream.read(pipeline.FRAME_SAMPLES)
                    flags.append(bool(audio.is_speech(audio.condition(chunk.tobytes()))))
            finally:
                stream.stop()
                stream.close()
            run = longest_run(flags)
            current = config.barge_in_frames
            rec = recommend_barge_in(run, current)
            detail = f"own voice reached the mic as speech for up to {run} consecutive frames ({run * pipeline.FRAME_MS} ms); barge-in threshold is {current}"
            if run < current:
                report.add("PASS", "barge-in", detail + " — safe as configured")
            elif rec == 0:
                report.add("WARN", "barge-in", detail + " — sustained: set CIPHLET_BARGE_IN_FRAMES=0 in .env (or use headphones / move the speaker away from the mic)")
            else:
                report.add("WARN", "barge-in", detail + f" — set CIPHLET_BARGE_IN_FRAMES={rec} in .env")
        except VoiceUnavailableError as exc:
            report.add("WARN", "barge-in", f"could not measure: {exc}")

    return _finish(report)


def _safe_speak(tts, text: str) -> None:
    try:
        tts.speak(text)
    except VoiceUnavailableError:
        pass  # surfaced by the speaker stage; here we only need the playback window


def _finish(report: _Report) -> int:
    print("\n== Result ==")
    for status, name, _ in report.results:
        print(f"  {status:<5} {name}")
    if report.failed:
        print("\nFix the FAIL items above, then re-run: ciphlet voice --selftest")
        return 1
    print("\nNext: ciphlet voice --hands-free   (say the wake phrase, ask something, and interrupt a long reply)")
    return 0
