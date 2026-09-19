"""deploy/audio_setup.py — speaker detection, unmute planning and .env wiring,
with `aplay`/`amixer` mocked (no audio hardware).

    python3 -m unittest tests.test_audio_setup -v
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
sys.path.insert(0, str(DEPLOY))  # audio_setup imports env_defaults from its own directory
_spec = importlib.util.spec_from_file_location("audio_setup", DEPLOY / "audio_setup.py")
audio_setup = importlib.util.module_from_spec(_spec)
sys.modules["audio_setup"] = audio_setup  # dataclasses needs the module registered
_spec.loader.exec_module(audio_setup)
import env_defaults  # noqa: E402

APLAY_L = """**** List of PLAYBACK Hardware Devices ****
card 0: vc4hdmi0 [vc4-hdmi-0], device 0: MAI PCM i2s-hifi-0 [MAI PCM i2s-hifi-0]
  Subdevices: 1/1
  Subdevice #0: subdevice #0
card 1: Headphones [bcm2835 Headphones], device 0: bcm2835 Headphones [bcm2835 Headphones]
  Subdevices: 8/8
card 2: Device [USB Audio Device], device 0: USB Audio [USB Audio]
  Subdevices: 1/1
"""

AMIXER = """Simple mixer control 'PCM',0
  Capabilities: pvolume pswitch pswitch-joined
  Playback channels: Mono
  Limits: Playback 0 - 255
  Mono: Playback 100 [39%] [off]
Simple mixer control 'Speaker',0
  Capabilities: pvolume
  Playback channels: Front Left - Front Right
  Front Left: Playback 20 [20%]
  Front Right: Playback 20 [20%]
Simple mixer control 'Master',0
  Capabilities: pvolume pswitch
  Front Left: Playback 200 [78%] [on]
Simple mixer control 'Mic',0
  Capabilities: cvolume cswitch
  Capture channels: Mono
  Mono: Capture 0 [0%] [off]
"""


class ParseTests(unittest.TestCase):
    def test_parses_all_cards_with_stable_ids(self):
        cards = audio_setup.parse_aplay_l(APLAY_L)
        self.assertEqual([(c.index, c.id) for c in cards], [(0, "vc4hdmi0"), (1, "Headphones"), (2, "Device")])

    def test_usb_is_preferred_over_headphones_and_hdmi_is_last(self):
        cards = audio_setup.parse_aplay_l(APLAY_L)
        self.assertEqual(audio_setup.choose_card(cards).id, "Device")
        self.assertEqual(audio_setup.choose_card(cards[:2]).id, "Headphones")  # no USB: jack beats HDMI
        self.assertEqual(audio_setup.choose_card(cards[:1]).id, "vc4hdmi0")  # HDMI only: still usable
        self.assertIsNone(audio_setup.choose_card([]))

    def test_candidate_devices_use_the_card_id_not_its_number(self):
        card = audio_setup.choose_card(audio_setup.parse_aplay_l(APLAY_L))
        self.assertEqual(audio_setup.candidate_devices(card), ["plughw:CARD=Device,DEV=0", "sysdefault:CARD=Device"])

    def test_normalize_matches_piper_rule(self):
        self.assertEqual(audio_setup.normalize_device("hw:2,0"), "plughw:2,0")
        self.assertEqual(audio_setup.normalize_device("default"), "default")

    def test_mixer_fixes_only_muted_or_quiet_playback_controls(self):
        fixes = {f.name: f.args for f in audio_setup.parse_amixer(AMIXER)}
        self.assertEqual(fixes, {"PCM": ["80%", "unmute"], "Speaker": ["80%"]})  # Master is fine, Mic is capture-only

    def test_beep_is_a_valid_short_mono_wav(self):
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "b.wav")
            audio_setup.make_beep(path)
            with wave.open(path) as w:
                self.assertEqual((w.getnchannels(), w.getsampwidth()), (1, 2))
                self.assertAlmostEqual(w.getnframes() / w.getframerate(), 0.5, places=2)


class MainTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / ".env"
        self.calls: list[list[str]] = []

    def fake_run(self, plays_ok):
        def run(cmd, timeout=15.0):
            self.calls.append(cmd)
            if cmd[:2] == ["aplay", "-l"]:
                return True, APLAY_L
            if cmd[0] == "amixer" and "scontents" in cmd:
                return True, AMIXER
            if cmd[0] == "amixer":
                return True, ""
            if cmd[0] == "aplay":  # a beep
                return (cmd[cmd.index("-D") + 1] in plays_ok), "Unable to install hw params" if cmd[cmd.index("-D") + 1] not in plays_ok else ""
            return False, "?"

        return run

    def main(self, plays_ok):
        with mock.patch.object(audio_setup.shutil, "which", return_value="/usr/bin/aplay"), \
             mock.patch.object(audio_setup, "run", self.fake_run(plays_ok)), mock.patch("builtins.print"):
            return audio_setup.main(["--env", str(self.env)])

    def test_blank_key_is_filled_with_the_verified_device_after_unmuting(self):
        self.env.write_text("GROQ_API_KEY=secret\nCIPHLET_AUDIO_OUTPUT_DEVICE=\n")
        self.main({"plughw:CARD=Device,DEV=0"})
        self.assertEqual(self.env.read_text(), "GROQ_API_KEY=secret\nCIPHLET_AUDIO_OUTPUT_DEVICE=plughw:CARD=Device,DEV=0\n")
        ssets = [c for c in self.calls if c[0] == "amixer" and "sset" in c]
        self.assertIn(["amixer", "-c", "2", "-q", "sset", "PCM", "80%", "unmute"], ssets)
        first_beep = next(i for i, c in enumerate(self.calls) if c[0] == "aplay" and "-D" in c)
        self.assertLess(self.calls.index(ssets[0]), first_beep)  # unmute BEFORE the audible test

    def test_falls_back_to_the_next_candidate_if_the_first_fails(self):
        self.env.write_text("")
        self.main({"sysdefault:CARD=Device"})
        self.assertEqual(env_defaults.get_value(self.env.read_text(), "CIPHLET_AUDIO_OUTPUT_DEVICE"), "sysdefault:CARD=Device")

    def test_nothing_is_written_if_no_candidate_plays(self):
        self.env.write_text("A=1\n")
        self.main(set())
        self.assertEqual(self.env.read_text(), "A=1\n")

    def test_existing_value_is_never_overwritten_and_mixer_is_not_touched(self):
        self.env.write_text("CIPHLET_AUDIO_OUTPUT_DEVICE=hw:1,0\n")
        before = self.env.read_text()
        self.main({"plughw:CARD=Device,DEV=0"})
        self.assertEqual(self.env.read_text(), before)
        self.assertFalse([c for c in self.calls if c[0] == "amixer"])
        self.assertIn("plughw:1,0", [c[c.index("-D") + 1] for c in self.calls if c[0] == "aplay" and "-D" in c])  # tested with plug conversion

    def test_no_playback_devices_is_a_soft_skip(self):
        self.env.write_text("A=1\n")
        with mock.patch.object(audio_setup.shutil, "which", return_value="/usr/bin/aplay"), \
             mock.patch.object(audio_setup, "run", return_value=(True, "**** List of PLAYBACK Hardware Devices ****\n")), \
             mock.patch("builtins.print"):
            self.assertEqual(audio_setup.main(["--env", str(self.env)]), 0)
        self.assertEqual(self.env.read_text(), "A=1\n")


class GetValueTests(unittest.TestCase):
    def test_effective_value_last_wins_and_blank_forms(self):
        gv = env_defaults.get_value
        self.assertEqual(gv("K=a\nK=b\n", "K"), "b")
        self.assertEqual(gv('K="quoted val"\n', "K"), "quoted val")
        for blank in ("K=\n", "K=''\n", "K= # note\n", "# K=commented\n", "OTHER=1\n", ""):
            self.assertEqual(gv(blank, "K"), "", blank)


if __name__ == "__main__":
    unittest.main()
