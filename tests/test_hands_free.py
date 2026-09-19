"""Hands-free loop integration: wake -> listen -> STT -> brain -> speak, plus
barge-in, self-echo rejection, wake reset and post-speech holdoff — driven
through the real HandsFreeVoiceSession with a scripted microphone (no hardware).

Frames are encoded by their first sample: 0 = silence, 1 = speech, 7 = the wake
phrase. Needs numpy (skipped without it):

    python3 -m unittest tests.test_hands_free -v
"""

from __future__ import annotations

import io
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

try:
    import numpy as np
except ImportError:
    np = None

from ciphlet.voice import pipeline
from ciphlet.voice.base import AudioProcessor, STTProvider, TTSProvider, VoiceUnavailableError, WakeProvider

SIL, SPK, WAKE = 0, 1, 7
ECHO, LOUD = 300, 1500  # Ciphlet's own voice at the mic vs. a user clearly louder than it


def frame(kind: int):
    return np.full((pipeline.FRAME_SAMPLES, 1), kind, dtype=np.int16)


class ScriptedStream:
    """Plays a script of frame kinds, then raises KeyboardInterrupt (ends run_forever)."""

    def __init__(self, script, on_read=None):
        self.script, self.i, self.on_read = list(script), 0, on_read
        self.stopped = self.closed = False

    def read(self, frames):
        if self.on_read:
            self.on_read(self.i)
        if self.i >= len(self.script):
            raise KeyboardInterrupt
        kind = self.script[self.i]
        self.i += 1
        return frame(kind), False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeAudio(AudioProcessor):
    def condition(self, audio):
        return audio

    def is_speech(self, chunk):
        return int(np.frombuffer(chunk, dtype=np.int16)[0]) in (SPK, ECHO, LOUD)


class FakeWake(WakeProvider):
    def __init__(self):
        self.windows = 0
        self.resets = 0

    def detect(self, chunk):
        self.windows += 1
        return bool(np.frombuffer(chunk, dtype=np.int16)[0] == WAKE)

    def reset(self):
        self.resets += 1


class FakeSTT(STTProvider):
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

    def transcribe(self, audio):
        self.calls += 1
        return self.texts.pop(0) if self.texts else ""


class FakeTTS(TTSProvider):
    """speak() blocks until stop() (a long reply), or returns at once."""

    def __init__(self, block=True):
        self.block, self.spoken, self.stops = block, [], 0
        self._stop = threading.Event()
        self.started = threading.Event()

    def speak(self, text):
        self.spoken.append(text)
        self.started.set()
        if self.block:
            self._stop.wait(5)

    def stop(self):
        self.stops += 1
        self._stop.set()


def make_session(stt, tts, wake=None, replies=None, **kw):
    kw.setdefault("barge_in_warmup_frames", 0)  # the gate is exercised by its own tests below
    replies = replies if replies is not None else []
    brain_inputs = []

    def brain(text):
        brain_inputs.append(text)
        return replies.pop(0) if replies else "ok"

    session = pipeline.HandsFreeVoiceSession(FakeAudio(), wake or FakeWake(), stt, tts, brain, **kw)
    return session, brain_inputs


def run(session, script, on_read=None):
    stream = ScriptedStream(script, on_read)
    out, err = io.StringIO(), io.StringIO()
    with mock.patch.object(pipeline, "_open_input_stream", return_value=stream), redirect_stdout(out), redirect_stderr(err):
        try:
            session.run_forever()
        except KeyboardInterrupt:
            pass
    return stream, out.getvalue(), err.getvalue()


@unittest.skipIf(np is None, "numpy not installed")
class CaptureTests(unittest.TestCase):
    def capture(self, script, prefix=None):
        session, _ = make_session(FakeSTT(), FakeTTS())
        stream = ScriptedStream(script)
        audio = session._capture_utterance(stream, prefix)
        return len(audio) // 2 // pipeline.FRAME_SAMPLES, stream.i  # frames returned, frames consumed

    def test_a_pause_after_the_wake_word_does_not_lose_the_turn(self):
        # ~1.5 s of silence BEFORE the user starts talking (old code quit after 600 ms)
        frames, consumed = self.capture([SIL] * 50 + [SPK] * 10 + [SIL] * 30)
        self.assertEqual(consumed, 50 + 10 + pipeline.SILENCE_FRAMES_TO_STOP)
        self.assertGreater(frames, 60)

    def test_never_speaking_times_out_with_no_audio(self):
        frames, consumed = self.capture([SIL] * 400)
        self.assertEqual((frames, consumed), (0, pipeline.NO_SPEECH_TIMEOUT_FRAMES))

    def test_endless_speech_is_capped(self):
        frames, _ = self.capture([SPK] * 900)
        self.assertEqual(frames, pipeline.MAX_UTTERANCE_FRAMES)

    def test_barge_in_prefix_counts_as_speech_already_started_and_is_kept(self):
        prefix = [frame(SPK) for _ in range(3)]
        frames, consumed = self.capture([SIL] * 40, prefix)
        self.assertEqual(consumed, pipeline.SILENCE_FRAMES_TO_STOP)
        self.assertEqual(frames, 3 + pipeline.SILENCE_FRAMES_TO_STOP)


@unittest.skipIf(np is None, "numpy not installed")
class AfterWakeCaptureTests(unittest.TestCase):
    """Real Pi finding: the wake word's own trailing audio counted as 'speech
    started', so a natural pause before the request ended the capture with
    only the wake word's tail in it (VOSK heard nothing, the turn was lost)."""

    def capture(self, script):
        """-> (speech frames in the captured audio, total frames, stream)"""
        session, _ = make_session(FakeSTT(), FakeTTS())
        stream = ScriptedStream(script)
        audio = session._capture_utterance(stream, after_wake=True)
        samples = np.frombuffer(audio, dtype=np.int16).reshape(-1, pipeline.FRAME_SAMPLES)
        return int((samples[:, 0] == SPK).sum()) if len(samples) else 0, len(samples), stream

    def test_wake_tail_is_dropped_and_the_request_after_a_pause_is_captured(self):
        # wake phrase tail (10 speech), ~1.2 s natural pause, then the request, then silence
        speech, _, _ = self.capture([SPK] * 10 + [SIL] * 40 + [SPK] * 12 + [SIL] * 30)
        self.assertEqual(speech, 12)  # the request only — none of the wake tail

    def test_the_old_behaviour_would_have_ended_on_the_tail(self):
        # the exact Pi trace: ~0.3-0.7 s of wake tail, then silence; the request comes later
        speech, _, stream = self.capture([SPK] * 10 + [SIL] * 60 + [SPK] * 12 + [SIL] * 30)
        self.assertGreater(stream.i, 10 + pipeline.SILENCE_FRAMES_TO_STOP)  # did not stop after the tail
        self.assertEqual(speech, 12)

    def test_speaking_straight_on_without_a_pause_keeps_everything(self):
        speech, total, _ = self.capture([SPK] * 80 + [SIL] * 30)
        self.assertEqual(speech, 80)  # nothing of the request is thrown away
        self.assertEqual(total, 80 + pipeline.SILENCE_FRAMES_TO_STOP)

    def test_nothing_said_after_the_wake_word_times_out_with_no_audio(self):
        speech, total, _ = self.capture([SPK] * 6 + [SIL] * 400)
        self.assertEqual((speech, total), (0, 0))


class BargeInDetectorTests(unittest.TestCase):
    """Real Pi finding: Ciphlet's own voice reaches the mic ~14x louder than room
    noise and VAD flags it as speech for seconds — VAD-only barge-in cut every
    reply off after ~1.5 s. An interruption must also be louder than the echo."""

    def det(self, **kw):
        return pipeline.BargeInDetector(**{"frames": 3, "gate": 2.5, "warmup": 10, **kw})

    def feed(self, det, seq):
        return [det.update(speech, rms) for speech, rms in seq]

    def test_echo_flagged_as_speech_never_interrupts(self):
        det = self.det()
        self.assertFalse(any(self.feed(det, [(True, 300.0)] * 400)))  # VAD-only would have fired at frame 1

    def test_a_clearly_louder_sustained_voice_interrupts_on_the_debounce_frame(self):
        det = self.det()
        self.feed(det, [(True, 300.0)] * 60)
        self.assertEqual(self.feed(det, [(True, 1500.0)] * 4), [False, False, True, True])

    def test_a_short_loud_blip_is_not_an_interruption(self):
        det = self.det()
        self.feed(det, [(True, 300.0)] * 60)
        self.assertFalse(any(self.feed(det, [(True, 1500.0)] * 2 + [(True, 300.0)] + [(True, 1500.0)] * 2)))

    def test_loud_non_speech_does_not_interrupt(self):
        det = self.det()
        self.feed(det, [(True, 300.0)] * 60)
        self.assertFalse(any(self.feed(det, [(False, 5000.0)] * 10)))  # a door slam is not a voice

    def test_a_quiet_interruption_below_the_gate_is_missed(self):
        # Documented limitation: talking over Ciphlet only works if clearly louder than its echo.
        det = self.det()
        self.feed(det, [(True, 300.0)] * 60)
        self.assertFalse(any(self.feed(det, [(True, 600.0)] * 20)))  # 2x < 2.5x

    def test_the_first_frames_only_learn_the_echo_level(self):
        det = self.det(warmup=10)
        self.assertFalse(any(self.feed(det, [(True, 5000.0)] * 10)))  # even loud speech can't interrupt during warm-up
        self.assertFalse(any(self.feed(det, [(True, 6000.0)] * 10)))  # ...and it raised the baseline (6000 < 2.5 x 5000)

    def test_warmup_starts_at_the_echo_onset_not_at_the_start_of_the_reply(self):
        # Real Pi failure: ~1 s of synthesis lag before any audio; the warm-up window was
        # spent on silence, so the echo's onset (300 vs ~30) looked like an interruption
        # and the reply was cut off by its own voice 3.8 s in.
        det = self.det(warmup=10)
        lag = [(False, 30.0)] * 40  # reply issued, nothing audible yet
        echo = [(True, 300.0)] * 200
        self.assertFalse(any(self.feed(det, lag + echo)))

    def test_reset_relearns_the_echo_for_the_next_reply(self):
        det = self.det()
        self.feed(det, [(True, 3000.0)] * 60)  # a loud reply
        det.reset()
        self.feed(det, [(True, 300.0)] * 60)  # a quieter one: 1500 is now an interruption again
        self.assertTrue(any(self.feed(det, [(True, 1500.0)] * 4)))

    def test_disabled_and_vad_only_modes(self):
        self.assertFalse(any(self.feed(self.det(frames=0), [(True, 9999.0)] * 50)))
        vad_only = self.det(gate=0, warmup=0)
        self.assertTrue(any(self.feed(vad_only, [(True, 300.0)] * 5)))  # the old behaviour


class EchoGuardTests(unittest.TestCase):
    def test_own_voice_is_recognised_but_real_speech_and_short_replies_are_not(self):
        reply = "The time is twelve thirty in the afternoon"
        self.assertTrue(pipeline._is_self_echo("the time is twelve thirty", reply))
        self.assertTrue(pipeline._is_self_echo("time is twelve thirty in the afternoon", reply))
        self.assertFalse(pipeline._is_self_echo("stop talking and tell me a joke", reply))
        self.assertFalse(pipeline._is_self_echo("the time", reply))  # under ECHO_MIN_WORDS
        self.assertFalse(pipeline._is_self_echo("anything at all here", ""))


@unittest.skipIf(np is None, "numpy not installed")
class HandsFreeLoopTests(unittest.TestCase):
    def test_full_turn_wake_listen_respond_speak(self):
        tts, stt = FakeTTS(block=False), FakeSTT("what time is it")
        session, brain = make_session(stt, tts, replies=["It is noon."])
        stream, out, _ = run(session, [SIL] * 5 + [WAKE] * 3 + [SIL] * 5 + [SPK] * 10 + [SIL] * 25 + [SIL] * 5)
        self.assertIn("(wake word detected)", out)
        self.assertEqual(brain, ["what time is it"])
        self.assertTrue(tts.started.wait(2))
        self.assertEqual(tts.spoken, ["It is noon."])
        self.assertTrue(stream.stopped and stream.closed)  # stream released on exit

    def test_models_are_loaded_before_the_mic_opens(self):
        # Real Pi finding: openWakeWord loaded lazily on the first window, after the mic
        # was open, so the first seconds of audio (the wake word) were lost.
        order = []

        class W(FakeWake):
            def load(self): order.append("wake.load")

        class S(FakeSTT):
            def load(self): order.append("stt.load")

        session, _ = make_session(S(), FakeTTS(), wake=W())
        stream = ScriptedStream([SIL] * 3)
        with mock.patch.object(pipeline, "_open_input_stream", side_effect=lambda dev: (order.append("mic.open"), stream)[1]), \
             redirect_stdout(io.StringIO()):
            try:
                session.run_forever()
            except KeyboardInterrupt:
                pass
        self.assertEqual(order[:3], ["wake.load", "stt.load", "mic.open"])

    def test_an_empty_turn_says_so_instead_of_vanishing(self):
        session, _ = make_session(FakeSTT(""), FakeTTS(block=False))
        _, out, _ = run(session, [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 3)
        self.assertIn("heard nothing", out)

    def test_markdown_reply_is_printed_in_full_but_spoken_clean_and_capped(self):
        tts = FakeTTS(block=False)
        reply = "**Hi!** Here is a table:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n" + "Firewalls filter traffic. " * 60 + "🎯"
        session, _ = make_session(FakeSTT("what is a firewall"), tts, replies=[reply])
        _, out, _ = run(session, [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 3)
        self.assertTrue(tts.started.wait(2))
        spoken = tts.spoken[0]
        self.assertIn("| a | b |", out)  # the screen gets the full, original text
        for junk in ("|", "**", "🎯", "---"):
            self.assertNotIn(junk, spoken)  # the speaker does not
        self.assertLessEqual(len(spoken), pipeline.SPOKEN_MAX_CHARS + len(" The rest is on screen."))
        self.assertEqual(session._last_reply, spoken)  # echo guard compares against what was actually said

    def test_wake_model_is_reset_after_each_turn(self):
        wake = FakeWake()
        session, _ = make_session(FakeSTT("hello there"), FakeTTS(block=False), wake=wake)
        run(session, [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 3)
        self.assertGreaterEqual(wake.resets, 1)

    def test_barge_in_interrupts_speech_and_keeps_the_interrupting_words(self):
        tts = FakeTTS(block=True)  # keeps "talking" until stop()
        stt = FakeSTT("what time is it", "stop and tell me a joke instead")
        session, brain = make_session(stt, tts, replies=["First a very long reply", "Why did the chicken"])
        # turn 1, then the user talks over the reply (sustained speech), then silence
        script = [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 2
        stream = ScriptedStream(script + [SPK] * 8 + [SIL] * 30)
        out = io.StringIO()
        # let the speaking thread start before the interrupting frames are read
        stream.on_read = lambda i: tts.started.wait(2) if i == len(script) else None
        with mock.patch.object(pipeline, "_open_input_stream", return_value=stream), redirect_stdout(out):
            try:
                session.run_forever()
            except KeyboardInterrupt:
                pass
        self.assertEqual(tts.stops, 1)
        self.assertEqual(brain, ["what time is it", "stop and tell me a joke instead"])
        self.assertEqual(stt.calls, 2)

    def test_own_echo_does_not_cut_off_the_reply_but_a_louder_voice_does(self):
        """The exact Pi failure: VAD flags the echo as speech, and the reply was
        stopped ~1.5 s in by its own voice. Now only a much louder voice stops it."""
        tts = FakeTTS(block=True)
        stt = FakeSTT("what is the capital of france", "wait I have a different question")
        session, brain = make_session(stt, tts, replies=["Paris is the capital of France and so on."], barge_in_warmup_frames=10)
        script = [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 2
        stream = ScriptedStream(script + [ECHO] * 200 + [LOUD] * 8 + [SIL] * 30)
        stream.on_read = lambda i: tts.started.wait(2) if i == len(script) else None
        with mock.patch.object(pipeline, "_open_input_stream", return_value=stream), redirect_stdout(io.StringIO()):
            try:
                session.run_forever()
            except KeyboardInterrupt:
                pass
        self.assertEqual(tts.stops, 1)  # exactly one stop: the loud voice, not the 200 frames of echo
        self.assertEqual(brain, ["what is the capital of france", "wait I have a different question"])

    def test_echo_alone_lets_the_whole_reply_play(self):
        tts = FakeTTS(block=True)
        session, brain = make_session(FakeSTT("what is the capital of france"), tts, replies=["Paris."], barge_in_warmup_frames=10)
        script = [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 2
        stream = ScriptedStream(script + [ECHO] * 300)
        stream.on_read = lambda i: tts.started.wait(2) if i == len(script) else None
        with mock.patch.object(pipeline, "_open_input_stream", return_value=stream), redirect_stdout(io.StringIO()):
            try:
                session.run_forever()
            except KeyboardInterrupt:
                pass
        self.assertEqual(tts.stops, 0)  # 300 frames (9 s) of echo flagged as speech: never interrupted
        tts.stop()  # release the blocked speech thread

    def test_barge_in_can_be_disabled(self):
        tts = FakeTTS(block=True)
        session, brain = make_session(FakeSTT("first question here", "should never be asked"), tts, barge_in_frames=0)
        script = [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 2
        stream = ScriptedStream(script + [SPK] * 20 + [SIL] * 5)
        stream.on_read = lambda i: tts.started.wait(2) if i == len(script) else None
        with mock.patch.object(pipeline, "_open_input_stream", return_value=stream), redirect_stdout(io.StringIO()):
            try:
                session.run_forever()
            except KeyboardInterrupt:
                pass
        self.assertEqual(tts.stops, 0)
        self.assertEqual(brain, ["first question here"])
        tts.stop()  # release the blocked speech thread

    def test_own_voice_transcribed_after_barge_in_is_ignored_not_answered(self):
        tts = FakeTTS(block=True)
        reply = "The weather today is sunny and warm"
        stt = FakeSTT("what is the weather", "the weather today is sunny and warm")  # 2nd = self-echo
        session, brain = make_session(stt, tts, replies=[reply])
        script = [WAKE] * 3 + [SIL] * 6 + [SPK] * 5 + [SIL] * 25 + [SIL] * 2
        stream = ScriptedStream(script + [SPK] * 8 + [SIL] * 30)
        stream.on_read = lambda i: tts.started.wait(2) if i == len(script) else None
        out = io.StringIO()
        with mock.patch.object(pipeline, "_open_input_stream", return_value=stream), redirect_stdout(out):
            try:
                session.run_forever()
            except KeyboardInterrupt:
                pass
        self.assertEqual(brain, ["what is the weather"])  # never replied to itself
        self.assertIn("ignored", out.getvalue())

    def test_mic_is_ignored_briefly_after_speech_ends_then_wake_works_again(self):
        wake = FakeWake()
        session, _ = make_session(FakeSTT(), FakeTTS(block=False), wake=wake)
        session._speaking.set()  # Ciphlet is mid-reply...
        finish_at = 5  # ...and playback ends on its own before frame 5

        def on_read(i):
            if i == finish_at:
                session._speaking.clear()

        # After playback: a wake marker inside the holdoff must be ignored...
        script = [SIL] * finish_at + [WAKE] * 4 + [SIL] * (pipeline.POST_SPEECH_HOLDOFF_FRAMES + 12)
        stream, out, _ = run(session, script, on_read)
        self.assertNotIn("(wake word detected)", out)  # early WAKE frames fell inside the holdoff
        self.assertGreaterEqual(wake.resets, 1)  # and the wake model was reset on the transition

    def test_speech_failure_is_reported_not_swallowed_and_state_recovers(self):
        session, _ = make_session(FakeSTT(), FakeTTS())

        class Boom(FakeTTS):
            def speak(self, text):
                raise VoiceUnavailableError("Audio playback failed on 'plughw:2,0' (exit 1): no such device")

        session._tts = Boom()
        session._speaking.set()
        err = io.StringIO()
        with redirect_stderr(err):
            session._speak_then_clear("hello")
        self.assertIn("speech output failed", err.getvalue())
        self.assertIn("plughw:2,0", err.getvalue())
        self.assertFalse(session._speaking.is_set())


if __name__ == "__main__":
    unittest.main()
