"""What Ciphlet says aloud vs. what it prints. Fixture: the real reply the brain
gave on the Pi to "what is your name and what can you help me with" — a ~350-word
markdown table + bold + emoji answer that would otherwise be read out verbatim.

    python3 -m unittest tests.test_speakable -v
"""

from __future__ import annotations

import unicodedata
import unittest

from ciphlet.voice.pipeline import SPOKEN_MAX_CHARS, speakable

REAL_REPLY = """Hey there! I’m **Ciphlet** — your cyber‑savvy learning buddy. I’m built to help you **learn, practice, and master** all things cybersecurity, from the basics of networking and Linux to the nitty‑gritty of SOC work, threat hunting, incident response, red‑team tactics, and everything in between.

Here’s a quick taste of what we can explore together:

| Area | What we can do |
|------|----------------|
| **SOC & Monitoring** | Walk through SIEM concepts, build detection rules, and simulate alert triage. |
| **Blue / Red / Purple Team** | Design defensive controls, try out ethical‑hacking techniques, and see how the two sides mesh. |

**How we’ll learn together**

1. **Ask & Explore** – I’ll prompt you with questions to spark your thinking before dropping the full answer.  
2. **Hint‑First Approach** – When you’re stuck, I’ll give a nudge or a hint, then we can dive deeper together.

- I don’t have the ability to run tools, view your screen, or control your computer.

So, what cybersecurity adventure are you curious about today? 🎯🛡️
"""


class SpeakableTests(unittest.TestCase):
    def test_the_real_pi_reply_becomes_clean_capped_speech(self):
        out = speakable(REAL_REPLY)
        for junk in ("|", "**", "#", "🎯", "🛡", "---", "\n"):
            self.assertNotIn(junk, out)
        self.assertTrue(out.startswith("Hey there! I’m Ciphlet"))
        self.assertNotIn("Blue / Red / Purple Team", out)  # table rows are dropped, not read out as pipes
        self.assertLessEqual(len(out), SPOKEN_MAX_CHARS + len(" The rest is on screen."))
        self.assertTrue(out.endswith("The rest is on screen."))
        self.assertFalse(any(unicodedata.category(c) in ("So", "Cs") for c in out))

    def test_short_plain_replies_are_untouched(self):
        for text in ("Paris is the capital of France.", "It is 12:30.", "Sure, I can help with that!"):
            self.assertEqual(speakable(text), text)

    def test_cut_falls_on_a_sentence_boundary(self):
        text = " ".join(f"This is sentence number {i}." for i in range(60))
        out = speakable(text, 200)
        body = out[: -len(" The rest is on screen.")]
        self.assertTrue(body.endswith("."))
        self.assertTrue(body.rstrip(".").split()[-1].isdigit())  # a whole sentence, never cut mid-number

    def test_no_cap_when_zero(self):
        self.assertGreater(len(speakable(REAL_REPLY, 0)), SPOKEN_MAX_CHARS)
        self.assertNotIn("|", speakable(REAL_REPLY, 0))  # still cleaned

    def test_code_links_and_urls(self):
        out = speakable("Run this:\n```bash\nnmap -sV 10.0.0.1\n```\nThen read [the guide](https://example.com/x) or see https://example.org/y now.")
        self.assertIn("code omitted", out)
        self.assertNotIn("nmap", out)  # command text is not read out
        self.assertIn("the guide", out)
        self.assertNotIn("http", out)

    def test_lists_and_headings(self):
        out = speakable("# Steps\n- first thing\n- second thing\n1. numbered")
        self.assertNotIn("#", out)
        self.assertNotIn("- ", out)
        self.assertIn("first thing", out)
        self.assertIn("second thing", out)

    def test_empty_and_symbol_only_text_do_not_crash(self):
        self.assertEqual(speakable(""), "")
        self.assertEqual(speakable("🎯🛡️"), "")


if __name__ == "__main__":
    unittest.main()
