"""Tests for deploy/env_defaults.py — the idempotent .env updater used by
deploy/install_voice.sh. Stdlib only; run from the repo root:

    python3 -m unittest tests.test_env_defaults -v
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent / "deploy" / "env_defaults.py"
_spec = importlib.util.spec_from_file_location("env_defaults", HELPER)
env_defaults = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(env_defaults)

PIPER = "/home/pi/CIPHLET/models/piper/en_US-amy-medium.onnx"
VOSK = "/home/pi/CIPHLET/models/vosk/vosk-model-small-en-us-0.15"

# Realistic file: secrets, comments (incl. a commented-out managed key), odd
# spacing, blank lines — everything here must survive byte-for-byte.
UNRELATED = (
    "# Ciphlet config — hand edited\n"
    "GROQ_API_KEY=gsk_secret_value_123\n"
    "\n"
    "GEMINI_API_KEY = \"has spaces # and hash\"\n"
    "CIPHLET_OLLAMA_MODEL=qwen3:4b-instruct-q4_K_M\n"
    "# CIPHLET_PIPER_MODEL=/commented/out/not/a/key.onnx\n"
    "  INDENTED_KEY=keep-me\n"
    "CIPHLET_AUDIO_INPUT_DEVICE=\n"  # blank, but NOT managed -> must stay blank
)


def run(text: str, managed: dict[str, str]):
    return env_defaults.apply_defaults(text, managed)


class ApplyDefaultsTests(unittest.TestCase):
    def test_missing_key_is_appended(self):
        out, st = run(UNRELATED, {"CIPHLET_PIPER_MODEL": PIPER})
        self.assertEqual(st, {"CIPHLET_PIPER_MODEL": "added"})
        self.assertEqual(out, UNRELATED + f"CIPHLET_PIPER_MODEL={PIPER}\n")  # commented-out line was ignored

    def test_missing_key_in_empty_file(self):
        out, st = run("", {"CIPHLET_VOSK_MODEL_PATH": VOSK})
        self.assertEqual(out, f"CIPHLET_VOSK_MODEL_PATH={VOSK}\n")

    def test_append_terminates_unterminated_last_line(self):
        out, _ = run("A=1", {"K": "v"})
        self.assertEqual(out, "A=1\nK=v\n")

    def test_blank_key_is_filled_in_place(self):
        for blank in ("CIPHLET_PIPER_MODEL=", "CIPHLET_PIPER_MODEL=   ", 'CIPHLET_PIPER_MODEL=""', "CIPHLET_PIPER_MODEL=''"):
            with self.subTest(blank=blank):
                text = f"A=1\n{blank}\nB=2\n"
                out, st = run(text, {"CIPHLET_PIPER_MODEL": PIPER})
                self.assertEqual(st, {"CIPHLET_PIPER_MODEL": "filled"})
                self.assertEqual(out, f"A=1\nCIPHLET_PIPER_MODEL={PIPER}\nB=2\n")

    def test_blank_key_keeps_export_indent_and_trailing_comment(self):
        out, _ = run("  export K=  # set by hand later\nZ=1\n", {"K": "v"})
        self.assertEqual(out, "  export K=v # set by hand later\nZ=1\n")

    def test_non_empty_existing_value_is_preserved_exactly(self):
        for existing in (
            "/my/own/piper.onnx",
            "models/piper/en_US-amy-medium.onnx",  # .env.example's relative default
            '"/quoted path/with space.onnx"',
            "0",  # falsy-looking but non-empty
            "  spaced-value  # trailing comment",
        ):
            with self.subTest(existing=existing):
                text = f"A=1\nCIPHLET_PIPER_MODEL={existing}\nB=2\n"
                out, st = run(text, {"CIPHLET_PIPER_MODEL": PIPER})
                self.assertEqual(st, {"CIPHLET_PIPER_MODEL": "kept"})
                self.assertEqual(out, text)

    def test_unrelated_configuration_is_preserved_byte_for_byte(self):
        managed = {"CIPHLET_PIPER_MODEL": PIPER, "CIPHLET_VOSK_MODEL_PATH": VOSK}
        # 1) both missing -> only two appended lines differ
        out, _ = run(UNRELATED, managed)
        self.assertTrue(out.startswith(UNRELATED))
        self.assertEqual(out[len(UNRELATED):], f"CIPHLET_PIPER_MODEL={PIPER}\nCIPHLET_VOSK_MODEL_PATH={VOSK}\n")
        # 2) both blank in the middle -> only those two lines change
        text = UNRELATED.replace("GROQ_API_KEY", "CIPHLET_PIPER_MODEL=\nCIPHLET_VOSK_MODEL_PATH=\nGROQ_API_KEY", 1)
        out, _ = run(text, managed)
        expected = UNRELATED.replace(
            "GROQ_API_KEY",
            f"CIPHLET_PIPER_MODEL={PIPER}\nCIPHLET_VOSK_MODEL_PATH={VOSK}\nGROQ_API_KEY",
            1,
        )
        self.assertEqual(out, expected)
        self.assertIn("GROQ_API_KEY=gsk_secret_value_123\n", out)
        self.assertIn("CIPHLET_AUDIO_INPUT_DEVICE=\n", out)  # unmanaged blank stays blank

    def test_prefix_keys_are_not_confused(self):
        text = "CIPHLET_PIPER_MODEL_EXTRA=x\nXCIPHLET_PIPER_MODEL=y\n"
        out, st = run(text, {"CIPHLET_PIPER_MODEL": PIPER})
        self.assertEqual(st["CIPHLET_PIPER_MODEL"], "added")
        self.assertTrue(out.startswith(text))

    def test_duplicate_key_last_occurrence_is_effective(self):
        # last blank -> it is the one filled (dotenv: last wins)
        out, _ = run("K=first\nK=\n", {"K": "v"})
        self.assertEqual(out, "K=first\nK=v\n")
        # last non-empty -> kept, even if an earlier one is blank
        text = "K=\nK=mine\n"
        out, st = run(text, {"K": "v"})
        self.assertEqual((out, st), (text, {"K": "kept"}))

    def test_crlf_line_endings_preserved(self):
        out, _ = run("A=1\r\nK=\r\nB=2\r\n", {"K": "v", "N": "n"})
        self.assertEqual(out, "A=1\r\nK=v\r\nB=2\r\nN=n\r\n")

    def test_values_needing_quotes_round_trip(self):
        out, _ = run("", {"K": "/path with space/model.onnx"})
        self.assertEqual(out, "K='/path with space/model.onnx'\n")

    def test_idempotent(self):
        managed = {"CIPHLET_PIPER_MODEL": PIPER, "CIPHLET_VOSK_MODEL_PATH": VOSK}
        once, _ = run(UNRELATED, managed)
        twice, st = run(once, managed)
        self.assertEqual(once, twice)
        self.assertEqual(set(st.values()), {"kept"})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = Path(self.tmp.name) / ".env"
        self.wake = Path(self.tmp.name) / "hey_ciphlet.onnx"

    def cli(self, *extra):
        return subprocess.run(
            [sys.executable, str(HELPER), "--env", str(self.env), *extra],
            capture_output=True, text=True, check=True,
        ).stdout

    def test_wake_model_skipped_when_file_absent_and_existing_value_preserved(self):
        self.env.write_text("CIPHLET_WAKE_MODEL=/my/manual/wake.onnx\nX=1\n")
        before = self.env.read_bytes()
        out = self.cli("--set-if-file", f"CIPHLET_WAKE_MODEL={self.wake}")
        self.assertIn("skipped", out)
        self.assertEqual(self.env.read_bytes(), before)

    def test_wake_model_not_invented_when_key_missing_and_file_absent(self):
        self.env.write_text("X=1\n")
        self.cli("--set-if-file", f"CIPHLET_WAKE_MODEL={self.wake}")
        self.assertEqual(self.env.read_text(), "X=1\n")

    def test_wake_model_set_only_when_file_exists_and_blank(self):
        self.wake.write_bytes(b"onnx")
        self.env.write_text("CIPHLET_WAKE_MODEL=\nX=1\n")
        self.cli("--set-if-file", f"CIPHLET_WAKE_MODEL={self.wake}")
        self.assertEqual(self.env.read_text(), f"CIPHLET_WAKE_MODEL={self.wake}\nX=1\n")

    def test_wake_model_existing_value_kept_even_when_trained_file_exists(self):
        self.wake.write_bytes(b"onnx")
        self.env.write_text("CIPHLET_WAKE_MODEL=/my/manual/wake.onnx\n")
        self.cli("--set-if-file", f"CIPHLET_WAKE_MODEL={self.wake}")
        self.assertEqual(self.env.read_text(), "CIPHLET_WAKE_MODEL=/my/manual/wake.onnx\n")

    def test_no_write_when_nothing_changes_and_mode_preserved(self):
        self.env.write_text(f"CIPHLET_PIPER_MODEL={PIPER}\n")
        os.chmod(self.env, 0o600)
        os.utime(self.env, (1_000_000_000, 1_000_000_000))
        self.cli("--set", f"CIPHLET_PIPER_MODEL={PIPER}")
        st = self.env.stat()
        self.assertEqual(int(st.st_mtime), 1_000_000_000)  # file untouched
        self.assertEqual(stat.S_IMODE(st.st_mode), 0o600)

    def test_mode_preserved_when_file_is_rewritten(self):
        self.env.write_text("CIPHLET_PIPER_MODEL=\n")
        os.chmod(self.env, 0o600)
        self.cli("--set", f"CIPHLET_PIPER_MODEL={PIPER}")
        self.assertEqual(stat.S_IMODE(self.env.stat().st_mode), 0o600)
        self.assertEqual(self.env.read_text(), f"CIPHLET_PIPER_MODEL={PIPER}\n")
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir() if p.name.endswith(".tmp")], [])

    def test_rerun_is_a_noop(self):
        self.env.write_text(UNRELATED)
        args = ("--set", f"CIPHLET_PIPER_MODEL={PIPER}", "--set", f"CIPHLET_VOSK_MODEL_PATH={VOSK}")
        self.cli(*args)
        first = self.env.read_bytes()
        out = self.cli(*args)
        self.assertEqual(self.env.read_bytes(), first)
        self.assertEqual(out.count("kept existing"), 2)

    def test_output_never_echoes_unrelated_secrets(self):
        self.env.write_text(UNRELATED)
        out = self.cli("--set", f"CIPHLET_PIPER_MODEL={PIPER}")
        self.assertNotIn("gsk_secret_value_123", out)


if __name__ == "__main__":
    unittest.main()
