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

    def test_barge_in_recommendation(self):
        self.assertEqual(selftest.recommend_barge_in(1, 3), 3)  # already clears the bleed
        self.assertEqual(selftest.recommend_barge_in(5, 3), 8)  # short bleed: add headroom
        self.assertEqual(selftest.recommend_barge_in(60, 3), 0)  # sustained bleed: disable


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
            wake_model_path=None, barge_in_frames=3,
        )

    def providers(self, mic_level=3000, heard="hello ciphlet", echo_is_speech=False, speak_error=None):
        state = {"echo": False}

        class TTS:
            def speak(_, text):
                if speak_error:
                    raise speak_error
                state["echo"] = text == selftest.ECHO_PHRASE
                import time
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
            def read(_, n): return np.full((n, 1), mic_level, dtype=np.int16), False
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

    def test_silent_mic_fails_with_gain_advice(self):
        code, out = self.run_it(mic_level=3)
        self.assertEqual(code, 1)
        self.assertIn("alsamixer", out)

    def test_no_transcript_is_a_warning_not_a_failure(self):
        code, out = self.run_it(heard="")
        self.assertEqual(code, 0)
        self.assertIn("[WARN] microphone", out)

    def test_speaker_bleed_into_mic_yields_a_barge_in_recommendation(self):
        code, out = self.run_it(echo_is_speech=True)
        self.assertEqual(code, 0)  # advice, not a failure
        self.assertIn("[WARN] barge-in", out)
        self.assertIn("CIPHLET_BARGE_IN_FRAMES=0", out)

    def test_missing_models_fail_fast_with_the_installer_hint(self):
        self.config.vosk_model_path = "/nope"
        code, out = self.run_it()
        self.assertEqual(code, 1)
        self.assertIn("deploy/install_voice.sh", out)


if __name__ == "__main__":
    unittest.main()
