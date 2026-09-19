"""The brain must know when it is speaking aloud on a live voice box (owner: "it thinks we are still on
a text based conversation"). The note is added for voice sessions only; text chat is unchanged."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ciphlet.brain.base import BrainProvider
from ciphlet.memory.store import MemoryStore
from ciphlet.orchestrator import Orchestrator
from ciphlet.session import Session
from ciphlet.voice.context import VOICE_SYSTEM_NOTE


class RecordingBrain(BrainProvider):
    name = "recording"

    def __init__(self):
        self.systems = []

    def generate(self, messages, *, system, on_token=None):
        self.systems.append(system)
        return "ok"


class VoiceContextTests(unittest.TestCase):
    def orchestrator(self, tmp, note):
        brain = RecordingBrain()
        orch = Orchestrator(brain=brain, memory=MemoryStore(Path(tmp) / "t.db"), session=Session(no_memory=True), system_note=note)
        return orch, brain

    def test_voice_sessions_tell_the_brain_it_is_live_and_spoken(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch, brain = self.orchestrator(tmp, VOICE_SYSTEM_NOTE)
            orch.handle_text("hello")
        self.assertTrue(brain.systems[0].endswith(VOICE_SYSTEM_NOTE))
        for phrase in ("LIVE VOICE", "not text", "Raspberry Pi", "read aloud", "no markdown", "BRIEF", "forty words"):
            self.assertIn(phrase.lower(), VOICE_SYSTEM_NOTE.lower())

    def test_text_chat_is_unchanged_without_a_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch, brain = self.orchestrator(tmp, None)
            orch.handle_text("hello")
        self.assertNotIn("LIVE VOICE", brain.systems[0])

    def test_the_note_reaches_every_turn_not_just_the_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            orch, brain = self.orchestrator(tmp, VOICE_SYSTEM_NOTE)
            orch.handle_text("one")
            orch.handle_text("two")
        self.assertTrue(all(VOICE_SYSTEM_NOTE in sy for sy in brain.systems))


if __name__ == "__main__":
    unittest.main()
