"""OpenWakeWordProvider configuration, against a stubbed `openwakeword` (the
real package/models are only on the Pi). Needs numpy for detect() (skipped
without it):

    python3 -m unittest tests.test_wake_provider -v
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest import mock

try:
    import numpy as np
except ImportError:
    np = None

from ciphlet.voice.base import VoiceUnavailableError
from ciphlet.voice.providers import GENERIC_WAKE_PHRASES, OpenWakeWordProvider


class FakeModel:
    instances: list = []

    def __init__(self, **kw):
        self.kw, self.resets = kw, 0
        FakeModel.instances.append(self)

    def predict(self, samples):
        return {"hey_jarvis": 0.9}

    def reset(self):
        self.resets += 1


def stub_openwakeword(model_cls=FakeModel):
    pkg, mod = types.ModuleType("openwakeword"), types.ModuleType("openwakeword.model")
    mod.Model = model_cls
    pkg.model = mod
    return mock.patch.dict(sys.modules, {"openwakeword": pkg, "openwakeword.model": mod})


@unittest.skipIf(np is None, "numpy not installed")
class WakeProviderTests(unittest.TestCase):
    def setUp(self):
        FakeModel.instances.clear()

    def test_default_loads_only_real_wake_phrases_on_onnx_not_timer_or_weather(self):
        with stub_openwakeword():
            self.assertTrue(OpenWakeWordProvider().detect(bytes(2560)))
        kw = FakeModel.instances[0].kw
        self.assertEqual(kw, {"inference_framework": "onnx", "wakeword_models": list(GENERIC_WAKE_PHRASES)})
        self.assertNotIn("timer", GENERIC_WAKE_PHRASES)
        self.assertNotIn("weather", GENERIC_WAKE_PHRASES)

    def test_custom_model_path_is_used_alone(self):
        with stub_openwakeword():
            OpenWakeWordProvider(model_path="models/wake/hey_ciphlet.onnx").detect(bytes(2560))
        self.assertEqual(FakeModel.instances[0].kw["wakeword_models"], ["models/wake/hey_ciphlet.onnx"])

    def test_reset_clears_the_model_and_is_safe_before_it_loads(self):
        with stub_openwakeword():
            p = OpenWakeWordProvider()
            p.reset()  # nothing loaded yet: must not raise or load the model
            self.assertEqual(FakeModel.instances, [])
            p.detect(bytes(2560))
            p.reset()
        self.assertEqual(FakeModel.instances[0].resets, 1)

    def test_load_failure_is_a_clear_error(self):
        class Broken(FakeModel):
            def __init__(self, **kw):
                raise ValueError("Could not find pretrained model for model name 'alexa'")

        with stub_openwakeword(Broken), self.assertRaises(VoiceUnavailableError) as cm:
            OpenWakeWordProvider().detect(bytes(2560))
        self.assertIn("download_models", str(cm.exception))


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# PocketSphinx "Hey Ciphlet" provider + engine selection (fake pocketsphinx)
# ---------------------------------------------------------------------------
import os  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from ciphlet.voice import providers  # noqa: E402
from ciphlet.voice.providers import PocketSphinxWakeProvider, build_wake_provider  # noqa: E402


class FakeDecoder:
    instances: list = []

    def __init__(self, **kw):
        self.kw, self.words, self.kws_text, self.kws_path = kw, {"hey": "HH EY"}, None, None
        self.active, self.starts, self.ends, self.fed, self.fire = None, 0, 0, [], False
        FakeDecoder.instances.append(self)

    def lookup_word(self, w):
        return self.words.get(w)

    def add_word(self, w, phones, update=True):
        self.words[w] = phones

    def add_kws(self, name, path):
        self.kws_path = path
        with open(path) as fh:
            self.kws_text = fh.read()

    def activate_search(self, name):
        self.active = name

    def start_utt(self):
        self.starts += 1

    def end_utt(self):
        self.ends += 1

    def process_raw(self, data, no_search=False, full_utt=False):
        self.fed.append(data)

    def hyp(self):
        return object() if self.fire else None


def stub_pocketsphinx():
    mod = types.ModuleType("pocketsphinx")
    mod.Decoder = FakeDecoder
    return mock.patch.dict(sys.modules, {"pocketsphinx": mod})


def cfg(**kw):
    base = dict(wake_model_path=None, wake_engine="auto", wake_kws_threshold=1e-20)
    return SimpleNamespace(**{**base, **kw})


class PocketSphinxProviderTests(unittest.TestCase):
    def setUp(self):
        FakeDecoder.instances.clear()

    def test_decoder_is_configured_with_the_spec_pronunciation_and_keyphrases(self):
        with stub_pocketsphinx():
            p = PocketSphinxWakeProvider(threshold=1e-25)
            p.load()
        d = FakeDecoder.instances[0]
        self.assertEqual((d.kw["lm"], d.kw["samprate"], d.kw["kws_threshold"]), (None, 16000, 1e-25))
        self.assertEqual(d.words["ciphlet"], "S AY F L IH T")  # "SIGH-flit" (spec)
        self.assertIn("ciphletb", d.words)
        self.assertEqual(d.kws_text.splitlines(), ["hey ciphlet /1e-25/", "hey ciphletb /1e-25/"])
        self.assertEqual((d.active, d.starts), ("ciphlet-wake", 1))
        self.assertFalse(os.path.exists(d.kws_path), "temporary keyword file must be removed")

    def test_detect_reports_a_hit_and_restarts_the_utterance(self):
        with stub_pocketsphinx():
            p = PocketSphinxWakeProvider()
            self.assertFalse(p.detect(b"\x00" * 2560))
            d = FakeDecoder.instances[0]
            self.assertEqual(d.fed, [b"\x00" * 2560])
            d.fire = True
            self.assertTrue(p.detect(b"\x00" * 2560))
            self.assertEqual((d.ends, d.starts), (1, 2))  # end + start: ready for the next phrase

    def test_utterance_state_is_bounded_on_long_silence(self):
        with stub_pocketsphinx():
            p = PocketSphinxWakeProvider()
            for _ in range(PocketSphinxWakeProvider.RESTART_AFTER_WINDOWS):
                p.detect(b"\x00" * 2560)
        self.assertEqual(FakeDecoder.instances[0].ends, 1)

    def test_reset_restarts_and_is_safe_before_load(self):
        with stub_pocketsphinx():
            p = PocketSphinxWakeProvider()
            p.reset()
            self.assertEqual(FakeDecoder.instances, [])
            p.load()
            p.reset()
        self.assertEqual(FakeDecoder.instances[0].ends, 1)

    def test_missing_package_gives_installer_hint(self):
        with mock.patch.dict(sys.modules, {"pocketsphinx": None}), self.assertRaises(VoiceUnavailableError) as cm:
            PocketSphinxWakeProvider().load()
        self.assertIn("install_voice.sh", str(cm.exception))


class BuildWakeProviderTests(unittest.TestCase):
    def test_custom_model_wins(self):
        p, label = build_wake_provider(cfg(wake_model_path="/m/hey_ciphlet.onnx"))
        self.assertIsInstance(p, OpenWakeWordProvider)
        self.assertIn("custom", label)

    def test_auto_uses_hey_ciphlet_via_pocketsphinx(self):
        with stub_pocketsphinx():
            p, label = build_wake_provider(cfg(wake_kws_threshold=1e-15))
        self.assertIsInstance(p, PocketSphinxWakeProvider)
        self.assertEqual(label, '"Hey Ciphlet"')
        self.assertEqual(p._threshold, 1e-15)

    def test_openwakeword_engine_is_the_generic_bringup_only(self):
        p, label = build_wake_provider(cfg(wake_engine="openwakeword"))
        self.assertIsInstance(p, OpenWakeWordProvider)
        self.assertIn("temporary", label)

    def test_auto_falls_back_loudly_never_silently(self):
        import contextlib
        import io

        err = io.StringIO()
        with mock.patch.dict(sys.modules, {"pocketsphinx": None}), contextlib.redirect_stderr(err):
            p, label = build_wake_provider(cfg())
        self.assertIsInstance(p, OpenWakeWordProvider)
        self.assertIn("WARNING", err.getvalue())
        self.assertIn("generic", err.getvalue())

    def test_forced_pocketsphinx_does_not_fall_back(self):
        with mock.patch.dict(sys.modules, {"pocketsphinx": None}), self.assertRaises(VoiceUnavailableError):
            build_wake_provider(cfg(wake_engine="pocketsphinx"))

    def test_invalid_engine_is_rejected(self):
        with self.assertRaises(VoiceUnavailableError):
            build_wake_provider(cfg(wake_engine="porcupine"))


class SynthesizeTests(unittest.TestCase):
    def test_synthesize_returns_raw_pcm_and_the_voice_rate(self):
        import stat
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            piper = Path(d) / "piper"
            piper.write_text('#!/bin/sh\ncat >/dev/null\nprintf "PCMDATA"\n')
            piper.chmod(piper.stat().st_mode | stat.S_IEXEC)
            (Path(d) / "v.onnx.json").write_text('{"audio": {"sample_rate": 16000}}')
            pcm, rate = providers.PiperTTS(str(Path(d) / "v.onnx"), piper_bin=str(piper)).synthesize("hello")
        self.assertEqual((pcm, rate), (b"PCMDATA", 16000))
