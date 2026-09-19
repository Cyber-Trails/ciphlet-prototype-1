"""Speaker-output path: PiperTTS driving `piper` -> `aplay`, exercised end to end
with fake executables (no audio hardware, no piper install).

    python3 -m unittest tests.test_voice_output -v
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from ciphlet.voice import providers
from ciphlet.voice.base import VoiceUnavailableError
from ciphlet.voice.providers import PiperTTS, _playback_device, _voice_sample_rate


def _script(path: Path, body: str) -> str:
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class PlaybackDeviceTests(unittest.TestCase):
    def test_bare_hw_gets_plug_conversion_others_untouched(self):
        self.assertEqual(_playback_device("hw:2,0"), "plughw:2,0")
        for d in ("plughw:2,0", "default", "sysdefault:CARD=Device", None, ""):
            self.assertEqual(_playback_device(d), d)


class VoiceRateTests(unittest.TestCase):
    def test_rate_comes_from_the_voice_json_with_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            model = os.path.join(d, "v.onnx")
            self.assertEqual(_voice_sample_rate(model, 22050), 22050)  # no json
            Path(model + ".json").write_text(json.dumps({"audio": {"sample_rate": 16000}}))
            self.assertEqual(_voice_sample_rate(model, 22050), 16000)
            Path(model + ".json").write_text("{not json")
            self.assertEqual(_voice_sample_rate(model, 22050), 22050)


class SpeakTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.model = str(self.dir / "voice.onnx")
        Path(self.model + ".json").write_text(json.dumps({"audio": {"sample_rate": 16000}}))
        self.args_file, self.audio_file = self.dir / "aplay.args", self.dir / "aplay.stdin"
        # fake piper: swallow text on stdin, emit fixed "audio" on stdout
        self.piper = _script(self.dir / "piper", 'cat >/dev/null\nprintf "RAWPCM"\n')
        # fake aplay: record args and stdin
        self.aplay = _script(self.dir / "aplay", f'echo "$@" > {self.args_file}\ncat > {self.audio_file}\n')

    def tts(self, **kw):
        return PiperTTS(self.model, piper_bin=kw.pop("piper_bin", self.piper), player_bin=kw.pop("player_bin", self.aplay), **kw)

    def test_audio_reaches_aplay_at_the_voice_rate(self):
        self.tts().speak("hello")
        self.assertEqual(self.audio_file.read_text(), "RAWPCM")
        args = self.args_file.read_text().split()
        self.assertEqual(args[args.index("-r") + 1], "16000")  # from voice json, not a hard-coded 22050
        self.assertIn("S16_LE", args)
        self.assertNotIn("-D", args)  # no device configured -> ALSA default

    def test_volume_is_passed_to_piper_only_when_not_full_scale(self):
        argsfile = self.dir / "piper.args"
        piper = _script(self.dir / "piper2", f'echo "$@" > {argsfile}\ncat >/dev/null\nprintf "RAWPCM"\n')
        self.tts(piper_bin=piper, volume=0.5).speak("hi")
        self.assertIn("--volume 0.5", argsfile.read_text())
        self.tts(piper_bin=piper).speak("hi")  # default 1.0
        self.assertNotIn("--volume", argsfile.read_text())

    def test_configured_output_device_is_used_with_plug_conversion(self):
        self.tts(output_device="hw:2,0").speak("hello")
        args = self.args_file.read_text().split()
        self.assertEqual(args[args.index("-D") + 1], "plughw:2,0")
        pipe = self.tts(output_device="plughw:CARD=Device,DEV=0")
        pipe.speak("x")
        self.assertIn("plughw:CARD=Device,DEV=0", self.args_file.read_text())

    def test_piper_failure_reports_its_stderr(self):
        bad = _script(self.dir / "badpiper", 'cat >/dev/null\necho "model exploded" >&2\nexit 3\n')
        with self.assertRaises(VoiceUnavailableError) as cm:
            self.tts(piper_bin=bad).speak("hi")
        self.assertIn("exit 3", str(cm.exception))
        self.assertIn("model exploded", str(cm.exception))

    def test_playback_failure_reports_device_and_stderr_and_next_step(self):
        bad = _script(self.dir / "badaplay", 'cat >/dev/null\necho "Rate 16000Hz not available" >&2\nexit 1\n')
        with self.assertRaises(VoiceUnavailableError) as cm:
            self.tts(player_bin=bad, output_device="hw:9,0").speak("hi")
        msg = str(cm.exception)
        for part in ("plughw:9,0", "Rate 16000Hz not available", "CIPHLET_AUDIO_OUTPUT_DEVICE"):
            self.assertIn(part, msg)

    def test_unopenable_device_is_blamed_on_the_player_not_on_piper(self):
        # Real Pi finding: `aplay -D pipewire` failed to open, piper died of BrokenPipe,
        # and the error said "Piper synthesis failed ... BrokenPipeError".
        dead_aplay = _script(self.dir / "deadaplay", 'echo "aplay: audio open error: No such device" >&2\nexit 1\n')
        chatty_piper = _script(self.dir / "spiper", 'cat >/dev/null\nhead -c 200000 /dev/zero\necho "BrokenPipeError: [Errno 32]" >&2\nexit 1\n')
        with self.assertRaises(VoiceUnavailableError) as cm:
            self.tts(piper_bin=chatty_piper, player_bin=dead_aplay, output_device="pipewire").speak("hi")
        self.assertIn("Audio playback failed", str(cm.exception))
        self.assertIn("No such device", str(cm.exception))
        self.assertNotIn("Piper synthesis failed", str(cm.exception))

    def test_chatty_stderr_cannot_deadlock_synthesis(self):
        # >64 KB on stderr would fill an unread pipe and hang the old implementation.
        noisy = _script(self.dir / "noisy", 'cat >/dev/null\nhead -c 300000 /dev/zero | tr "\\0" "x" >&2\nprintf "RAWPCM"\n')
        done = threading.Event()
        threading.Thread(target=lambda: (self.tts(piper_bin=noisy).speak("hi"), done.set()), daemon=True).start()
        self.assertTrue(done.wait(10), "speak() hung on a chatty piper")

    def test_stop_interrupts_playback_without_raising(self):
        slow = _script(self.dir / "slow", "cat >/dev/null\nexec sleep 30\n")
        tts = self.tts(piper_bin=slow)
        errors, finished = [], threading.Event()

        def run():
            try:
                tts.speak("a long reply")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finished.set()

        threading.Thread(target=run, daemon=True).start()
        time.sleep(0.5)
        t0 = time.time()
        tts.stop()
        self.assertTrue(finished.wait(5), "stop() did not end speak()")
        self.assertLess(time.time() - t0, 3)
        self.assertEqual(errors, [])  # an intentional barge-in is not a failure

    def test_missing_player_gives_install_hint(self):
        with self.assertRaises(VoiceUnavailableError) as cm:
            self.tts(player_bin="definitely-not-a-real-aplay").speak("hi")
        self.assertIn("alsa-utils", str(cm.exception))


class PiperCommandTests(unittest.TestCase):
    def cmd(self, which, sibling_exists, spec):
        tts = PiperTTS("/m/v.onnx")
        with mock.patch.object(providers.shutil, "which", return_value=which), \
             mock.patch.object(providers.Path, "exists", return_value=sibling_exists), \
             mock.patch.object(providers.importlib.util, "find_spec", return_value=spec):
            return tts._piper_command()

    def test_prefers_path_then_venv_script_then_python_dash_m(self):
        self.assertEqual(self.cmd("/usr/bin/piper", True, object()), ["/usr/bin/piper"])
        self.assertEqual(len(self.cmd(None, True, object())), 1)  # venv sibling, no activation needed
        self.assertEqual(self.cmd(None, False, object())[1:], ["-m", "piper"])
        with self.assertRaises(VoiceUnavailableError):
            self.cmd(None, False, None)


if __name__ == "__main__":
    unittest.main()
