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
# Sentences the wake engine must stay quiet on. NOT the speaker-check line: it contains the name
# "Ciphlet", which (bare name accepted) is exactly what should wake it.
NEGATIVE_PHRASES = (
    ECHO_PHRASE,
    "The quick brown fox jumps over the lazy dog, then runs across the field and down to the river.",
)
RECORD_SECONDS = 4
LOW_LEVEL_PEAK = 500  # int16 peak below this = mic is barely picking anything up


def longest_run(flags) -> int:
    best = run = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def would_interrupt(pairs, frames: int, gate: float, low_level: float = 0.0) -> bool:
    """Would the real barge-in detector have fired on this recording of Ciphlet's
    own voice? `pairs` = [(vad_speech, frame_rms[, low_band_level]), ...]."""
    detector = pipeline.BargeInDetector(frames, gate, pipeline.BARGE_IN_WARMUP_FRAMES, low_level)
    for speech, rms, *rest in pairs:
        if detector.update(speech, rms, rest[0] if rest else None):
            return True
    return False


def recommend_gate(pairs, frames: int, gate: float) -> float | None:
    """Smallest loudness gate at or above `gate` that stops Ciphlet's own echo from
    interrupting it; None if even a very high gate doesn't."""
    for candidate in (gate, 3.5, 5.0, 8.0, 12.0):
        if candidate >= gate and not would_interrupt(pairs, frames, candidate, 0.0):
            return candidate
    return None


def recommend_low_level(pairs, frames: int, low_level: float) -> float | None:
    """Smallest low-band level at or above `low_level` that Ciphlet's own echo does not reach
    (a bassy speaker needs a higher one); None = the echo is as low-band-heavy as a person."""
    for candidate in (low_level, 200.0, 300.0, 500.0, 800.0, 1200.0):
        if candidate >= low_level and not would_interrupt(pairs, frames, 1e9, candidate):
            return candidate
    return None


def _phrase_pcm_16k(tts, text: str) -> bytes:
    """Piper-synthesize `text`, resample to 16 kHz mono int16, with a little
    lead/trail silence — audio a wake engine can be fed directly."""
    import numpy as np

    pcm, rate = tts.synthesize(text)
    samples = np.frombuffer(pcm, dtype=np.int16)
    if rate != pipeline.SAMPLE_RATE:
        samples = pipeline._StreamResampler(rate, pipeline.SAMPLE_RATE).process(samples)
    pad = np.zeros(pipeline.SAMPLE_RATE // 2, dtype=np.int16)
    return np.concatenate((pad, samples, pad)).tobytes()


def wake_fires(wake, pcm: bytes) -> bool:
    """Feed 80 ms windows of `pcm` to the wake engine; did it ever fire?"""
    step = pipeline.WAKE_CHUNK_SAMPLES * 2
    wake = wake.fresh() if hasattr(wake, "fresh") else wake
    wake.reset()
    hit = False
    for i in range(0, len(pcm) - step + 1, step):
        if wake.detect(pcm[i : i + step]):
            hit = True
    wake.reset()
    return hit


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
    wake_label: str | None = None,
    open_stream=None,
    ask=input,
    interactive: bool | None = None,
) -> int:
    from ciphlet.voice.providers import PiperTTS, VoskSTT, WebRTCVadAudioProcessor, build_wake_provider

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

    tts = tts or PiperTTS(model_path=piper_path, output_device=config.audio_output_device, volume=getattr(config, "tts_volume", 1.0))
    stt = stt or VoskSTT(model_path=vosk_path)
    audio = audio or WebRTCVadAudioProcessor()
    if wake is None:
        try:
            wake, wake_label = build_wake_provider(config)
        except VoiceUnavailableError as exc:
            report.add("FAIL", "wake model", str(exc))
            wake = None
    wake_label = wake_label or "the wake phrase"

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
        try:
            speech_frames = sum(audio.is_speech(audio.condition(f.tobytes())) for f in frames_16k)
            text = stt.transcribe(b"".join(f.tobytes() for f in frames_16k))
        except VoiceUnavailableError as exc:  # VAD or VOSK not usable: report, don't crash
            mic_ok = False
            report.add("FAIL", "VAD/VOSK", f"captured audio (peak {peak}, rms {rms:.0f}) but processing failed: {exc}")
            speech_frames, text = None, None
        detail = f"peak {peak}, rms {rms:.0f}, speech in {speech_frames}/{len(frames_16k)} frames; VOSK heard: {text!r}"
        if text is None:
            pass
        elif peak < LOW_LEVEL_PEAK and not interactive:
            report.add("WARN", "microphone", detail + " — nothing loud enough was heard (non-interactive run: nobody was prompted to speak)")
        elif peak < LOW_LEVEL_PEAK:
            mic_ok = False
            report.add("FAIL", "microphone", detail + " — signal is almost silent: raise capture gain (alsamixer -c <card>, F4) or check the mic")
        elif not text:
            report.add("WARN", "microphone", detail + " — captured audio but VOSK heard no words (speak louder/closer, or nothing was said)")
        else:
            report.add("PASS", "microphone+VAD+VOSK", detail)

    # 4. Wake engine ---------------------------------------------------------
    print("\n-- Wake word --")
    if wake is not None:
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
            report.add("PASS", "wake model", f"loaded and ran on {windows} windows; say {wake_label} to wake it")
            # Does the engine actually fire on the phrase (and stay quiet on
            # other speech)? Uses Piper-synthesized speech, so it needs no human
            # and is repeatable; real voices still vary — see the hands-free test.
            if hasattr(tts, "synthesize") and speaker_ok:
                # Spelled as the SPEC pronounces it (SIGH-flit): Piper reads "ciphlet" as
                # "SIF-let", which is not how the owner says it.
                positive = "hey jarvis" if "jarvis" in wake_label else "hey sigh flit"
                try:
                    hit = wake_fires(wake, _phrase_pcm_16k(tts, positive))
                    false_hits = [t for t in NEGATIVE_PHRASES if wake_fires(wake, _phrase_pcm_16k(tts, t))]
                except VoiceUnavailableError as exc:
                    report.add("WARN", "wake phrase", f"could not synthesize test audio: {exc}")
                else:
                    if hit and not false_hits:
                        report.add("PASS", "wake phrase", f"fires on synthesized '{positive}', stays quiet on other sentences")
                    elif not hit:
                        report.add("WARN", "wake phrase", f"did NOT fire on synthesized '{positive}' — make it more sensitive (CIPHLET_WAKE_KWS_THRESHOLD smaller, e.g. 1e-30) or check pronunciation")
                    else:
                        report.add("WARN", "wake phrase", f"fired on ordinary sentences ({len(false_hits)} of {len(NEGATIVE_PHRASES)}) — make it stricter (CIPHLET_WAKE_KWS_THRESHOLD larger, e.g. 1e-10)")

    # 5. Speaker-into-mic bleed (decides whether barge-in is safe) -----------
    print("\n-- Speaker->mic bleed: stay QUIET while I speak (measures barge-in safety) --")
    if not (mic_ok and speaker_ok):
        report.add("WARN", "barge-in", "skipped (needs a working mic and speaker)")
    else:
        try:
            stream = open_stream(config.audio_input_device)
            speaker = threading.Thread(target=lambda: _safe_speak(tts, ECHO_PHRASE), daemon=True)
            speaker.start()
            pairs = []
            try:
                import numpy as np

                while speaker.is_alive():
                    chunk, _ = stream.read(pipeline.FRAME_SAMPLES)
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float64) ** 2)))
                    pairs.append((
                        bool(audio.is_speech(audio.condition(chunk.tobytes()))),
                        rms,
                        pipeline.low_band_level(chunk),
                    ))
            finally:
                stream.stop()
                stream.close()
            run = longest_run([speech for speech, *_ in pairs])
            echo_rms = max((p[1] for p in pairs), default=0.0)
            echo_low = max((p[2] for p in pairs), default=0.0)
            frames, gate, low_level = config.barge_in_frames, config.barge_in_gate, getattr(config, "barge_in_low_level", 0.0)
            detail = (
                f"own voice reached the mic as speech for up to {run} consecutive frames ({run * pipeline.FRAME_MS} ms), "
                f"echo peak rms {echo_rms:.0f}, echo low-band (80-250 Hz) peak level {echo_low:.0f} "
                f"(a person talking over it must reach {low_level:.0f}; a person near the mic is typically several hundred)"
            )
            if frames <= 0:
                report.add("PASS", "barge-in", detail + " — barge-in is disabled (CIPHLET_BARGE_IN_FRAMES=0)")
            elif not would_interrupt(pairs, frames, gate, low_level):
                report.add("PASS", "barge-in", detail + " — Ciphlet's own voice does not interrupt it as configured")
            else:
                advice = []
                if low_level > 0 and would_interrupt(pairs, frames, 1e9, low_level):
                    rec = recommend_low_level(pairs, frames, low_level)
                    advice.append(
                        f"set CIPHLET_BARGE_IN_LOW_LEVEL={rec:g}" if rec is not None
                        else "set CIPHLET_BARGE_IN_LOW_LEVEL=0 (this speaker's echo has as much low-band energy as a person)"
                    )
                if would_interrupt(pairs, frames, gate, 0.0):
                    rec = recommend_gate(pairs, frames, gate)
                    advice.append(
                        f"set CIPHLET_BARGE_IN_GATE={rec:g}" if rec is not None
                        else "set CIPHLET_BARGE_IN_FRAMES=0 (the echo is too loud to tell from a person), or use headphones / a speakerphone with echo cancellation"
                    )
                report.add("WARN", "barge-in", detail + " — Ciphlet would interrupt itself: " + "; ".join(advice) + " in .env")
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
