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
