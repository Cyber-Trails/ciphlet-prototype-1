"""`ciphlet voice --selftest` logic with fake providers/mic (no hardware).
Needs numpy (skipped without it):

    python3 -m unittest tests.test_selftest -v
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

try:
    import numpy as np
except ImportError:
    np = None

from ciphlet.voice import pipeline, selftest
from ciphlet.voice.base import VoiceUnavailableError


class HelperTests(unittest.TestCase):
    def test_longest_run(self):
        self.assertEqual(selftest.longest_run([0, 1, 1, 0, 1, 1, 1, 0]), 3)
        self.assertEqual(selftest.longest_run([]), 0)

    def test_would_interrupt_only_on_speech_much_louder_than_the_echo(self):
        warm = pipeline.BARGE_IN_WARMUP_FRAMES
        echo = [(True, 300.0)] * (warm + 100)  # VAD says "speech" throughout, but never louder than the echo
        self.assertFalse(selftest.would_interrupt(echo, 3, 2.5))
        surge = echo + [(True, 1200.0)] * 5  # 4x the echo
        self.assertTrue(selftest.would_interrupt(surge, 3, 2.5))
        self.assertFalse(selftest.would_interrupt(surge, 3, 5.0))

    def test_gate_recommendation(self):
        warm = pipeline.BARGE_IN_WARMUP_FRAMES
        surge_4x = [(True, 300.0)] * warm + [(True, 1200.0)] * 5
        self.assertEqual(selftest.recommend_gate(surge_4x, 3, 2.5), 5.0)  # smallest gate that clears it
        self.assertEqual(selftest.recommend_gate([(True, 300.0)] * (warm + 50), 3, 2.5), 2.5)  # already fine
        surge_20x = [(True, 300.0)] * warm + [(True, 6000.0)] * 5
        self.assertIsNone(selftest.recommend_gate(surge_20x, 3, 2.5))  # nothing helps: disable barge-in


@unittest.skipIf(np is None, "numpy not installed")
class RunSelftestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "v.onnx").write_text("x")
        (d / "v.onnx.json").write_text("{}")
        (d / "vosk").mkdir()
        self.config = SimpleNamespace(
            audio_input_device="hw:2,0", audio_output_device="plughw:CARD=Device,DEV=0",
            piper_model_path=str(d / "v.onnx"), vosk_model_path=str(d / "vosk"),
            wake_model_path=None, barge_in_frames=3, barge_in_gate=2.5, barge_in_low_level=130.0,
        )

    def providers(self, mic_level=3000, heard="hello ciphlet", echo_is_speech=False, speak_error=None, echo_amps=None, echo_hz=None):
        state = {"echo": False, "n": 0}

        class TTS:
            def speak(_, text):
                if speak_error:
                    raise speak_error
                import time
                state["echo"] = text == selftest.ECHO_PHRASE
                if state["echo"] and echo_amps is not None:
                    state["n"] = 0
                    deadline = time.time() + 5
                    while state["n"] < pipeline.BARGE_IN_WARMUP_FRAMES + 60 and time.time() < deadline:
                        time.sleep(0.001)  # keep "speaking" until the recorder has read enough frames
                else:
                    time.sleep(0.05)
                state["echo"] = False

            def stop(_): pass

        class Audio:
            def condition(_, b): return b
            def is_speech(_, b): return echo_is_speech if state["echo"] else True

        class STT:
            def transcribe(_, audio): return heard

        class Wake:
            windows = 0
            def detect(_, b): Wake.windows += 1; return False
            def reset(_): pass

        class Stream:
            def read(_, n):
                if state["echo"] and echo_amps is not None:  # loudness profile of Ciphlet's own voice at the mic
                    state["n"] += 1
                    amp = echo_amps(state["n"])
                    if echo_hz:  # tonal echo (e.g. a speaker with real bass at 150 Hz)
                        t = np.arange(n) / pipeline.SAMPLE_RATE
                        return (amp * np.sin(2 * np.pi * echo_hz * t)).astype(np.int16).reshape(-1, 1), False
                    return np.full((n, 1), amp, dtype=np.int16), False
                return np.full((n, 1), mic_level, dtype=np.int16), False
            def stop(_): pass
            def close(_): pass

        return dict(tts=TTS(), stt=STT(), audio=Audio(), wake=Wake(), open_stream=lambda dev: Stream(), interactive=False)

    def run_it(self, **kw):
        out = io.StringIO()
        with redirect_stdout(out):
            code = selftest.run_selftest(self.config, **self.providers(**kw))
        return code, out.getvalue()

    def test_all_stages_pass_on_a_healthy_setup(self):
        code, out = self.run_it()
        self.assertEqual(code, 0, out)
        for name in ("config", "speaker", "microphone+VAD+VOSK", "wake model", "barge-in"):
            self.assertIn(f"PASS  {name}", out)

    def test_speaker_failure_fails_the_run_with_the_real_error(self):
        code, out = self.run_it(speak_error=VoiceUnavailableError("Audio playback failed on 'plughw:2,0' (exit 1): busy"))
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] speaker", out)
        self.assertIn("busy", out)

    def test_silent_mic_fails_with_gain_advice_when_a_human_was_prompted(self):
        kw = self.providers(mic_level=3)
        kw["interactive"] = True
        out = io.StringIO()
        with redirect_stdout(out):
            code = selftest.run_selftest(self.config, ask=lambda prompt: "", **kw)
        self.assertEqual(code, 1)
        self.assertIn("alsamixer", out.getvalue())

    def test_silent_mic_is_only_a_warning_when_nobody_was_asked_to_speak(self):
        # Real Pi run over ssh with no human: a quiet room must not FAIL the run
        # or skip the speaker->mic bleed stage.
        code, out = self.run_it(mic_level=3)
        self.assertEqual(code, 0, out)
        self.assertIn("[WARN] microphone", out)
        self.assertIn("barge-in", out)
        self.assertNotIn("skipped", out)

    def test_unusable_vad_is_reported_as_a_failure_not_a_crash(self):
        # Real Pi failure: webrtcvad raised VoiceUnavailableError (pkg_resources missing)
        # and the self-test died with a traceback instead of reporting it.
        kw = self.providers()

        class BrokenAudio:
            def condition(_, b): return b
            def is_speech(_, b): raise VoiceUnavailableError("'webrtcvad' is not installed.")

        kw["audio"] = BrokenAudio()
        out = io.StringIO()
        with redirect_stdout(out):
            code = selftest.run_selftest(self.config, **kw)
        self.assertEqual(code, 1)
        self.assertIn("[FAIL] VAD/VOSK", out.getvalue())
        self.assertIn("webrtcvad", out.getvalue())

    def test_no_transcript_is_a_warning_not_a_failure(self):
        code, out = self.run_it(heard="")
        self.assertEqual(code, 0)
        self.assertIn("[WARN] microphone", out)

    def bleed(self, echo_amps, echo_hz=None):
        return self.run_it(echo_is_speech=True, echo_amps=echo_amps, echo_hz=echo_hz)

    def test_echo_that_never_exceeds_itself_does_not_interrupt_as_configured(self):
        # VAD flags Ciphlet's own voice as speech throughout (the real Pi case), but the
        # loudness gate means it can never interrupt itself.
        code, out = self.bleed(lambda i: 300)
        self.assertEqual(code, 0)
        self.assertIn("[PASS] barge-in", out)
        self.assertIn("does not interrupt it", out)

    def test_a_surging_echo_gets_a_gate_recommendation(self):
        warm = pipeline.BARGE_IN_WARMUP_FRAMES
        code, out = self.bleed(lambda i: 300 if i <= warm else 1200)  # 4x surge
        self.assertEqual(code, 0)  # advice, not a failure
        self.assertIn("[WARN] barge-in", out)
        self.assertIn("CIPHLET_BARGE_IN_GATE=5", out)

    def test_a_speaker_with_bass_is_reported_and_the_low_band_path_gets_a_recommendation(self):
        # Ciphlet's echo carrying real 150 Hz energy (level ~420) reads as a person to the low-band path.
        code, out = self.bleed(lambda i: 600, echo_hz=150)
        self.assertEqual(code, 0)
        self.assertIn("[WARN] barge-in", out)
        self.assertIn("CIPHLET_BARGE_IN_LOW_LEVEL=500", out)  # smallest candidate above the echo's own level
        self.assertIn("low-band", out)

    def test_a_very_bassy_echo_recommends_disabling_the_low_band_path(self):
        code, out = self.bleed(lambda i: 5000, echo_hz=150)
        self.assertIn("CIPHLET_BARGE_IN_LOW_LEVEL=0", out)

    def test_normal_echo_reports_its_low_band_level_and_passes(self):
        code, out = self.bleed(lambda i: 300)
        self.assertIn("[PASS] barge-in", out)
        self.assertIn("low-band (80-250 Hz) peak level", out)

    def test_an_echo_no_gate_can_separate_recommends_disabling_barge_in(self):
        warm = pipeline.BARGE_IN_WARMUP_FRAMES
        code, out = self.bleed(lambda i: 300 if i <= warm else 6000)  # 20x surge
        self.assertIn("[WARN] barge-in", out)
        self.assertIn("CIPHLET_BARGE_IN_FRAMES=0", out)

    def test_missing_models_fail_fast_with_the_installer_hint(self):
        self.config.vosk_model_path = "/nope"
        code, out = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("deploy/install_voice.sh", out)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(np is None, "numpy not installed")
class WakePhraseStageTests(unittest.TestCase):
    """Piper-synthesized wake phrase: fires on the phrase, quiet on other speech."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        (d / "v.onnx").write_text("x")
        (d / "v.onnx.json").write_text("{}")
        (d / "vosk").mkdir()
        self.config = SimpleNamespace(
            audio_input_device=None, audio_output_device=None, piper_model_path=str(d / "v.onnx"),
            vosk_model_path=str(d / "vosk"), wake_model_path=None, barge_in_frames=3, barge_in_gate=2.5, barge_in_low_level=130.0,
        )

    def run_it(self, wake_behaviour):
        class TTS:
            def speak(_, text): pass
            def stop(_): pass
            def synthesize(_, text):  # loud only for the wake phrase
                amp = 1000 if text == "hey sigh flit" else 0
                return np.full(22050, amp, dtype=np.int16).tobytes(), 22050

        class Audio:
            def condition(_, b): return b
            def is_speech(_, b): return False

        class STT:
            def transcribe(_, a): return "hello"

        class Wake:
            def reset(_): pass
            def detect(_, chunk):
                loud = bool(np.abs(np.frombuffer(chunk, dtype=np.int16)).max() > 200)
                return {"good": loud, "deaf": False, "trigger_happy": True}[wake_behaviour]

        class Stream:
            def read(_, n): return np.full((n, 1), 3000, dtype=np.int16), False
            def stop(_): pass
            def close(_): pass

        out = io.StringIO()
        with redirect_stdout(out):
            selftest.run_selftest(
                self.config, tts=TTS(), stt=STT(), audio=Audio(), wake=Wake(), wake_label='"Hey Ciphlet"',
                open_stream=lambda dev: Stream(), interactive=False,
            )
        return out.getvalue()

    def test_phrase_fires_and_other_speech_does_not(self):
        self.assertIn("[PASS] wake phrase", self.run_it("good"))

    def test_deaf_engine_gets_a_more_sensitive_hint(self):
        out = self.run_it("deaf")
        self.assertIn("[WARN] wake phrase", out)
        self.assertIn("smaller", out)

    def test_trigger_happy_engine_gets_a_stricter_hint(self):
        out = self.run_it("trigger_happy")
        self.assertIn("[WARN] wake phrase", out)
        self.assertIn("larger", out)
