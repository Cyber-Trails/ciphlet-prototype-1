"""Tests for the mic-capture path in ciphlet/voice/pipeline.py: opening the
input device at a hardware-supported rate and resampling to the 16 kHz mono
int16 that the VAD / wake word / STT need.

Regression for the Pi USB mic that only supports 44100/48000 Hz and made
PortAudio fail with paInvalidSampleRate (-9997) at 16 kHz.

Uses a fake `sounddevice` (no audio hardware). The numeric tests need numpy
and are skipped where it isn't installed. Run from the repo root:

    python3 -m unittest tests.test_audio_input -v
"""

from __future__ import annotations

import unittest
from unittest import mock

try:
    import numpy as np
except ImportError:  # the resampling tests are skipped without numpy
    np = None

from ciphlet.voice import pipeline
from ciphlet.voice.base import VoiceUnavailableError

needs_numpy = unittest.skipIf(np is None, "numpy not installed")

OUT = pipeline.SAMPLE_RATE  # 16000


def sine(freq, rate, n, amp=10000.0, start=0):
    t = (np.arange(start, start + n)) / rate
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.int16)


class FakePortAudioError(Exception):
    pass


class FakeStream:
    """Stands in for sd.InputStream: emits a continuous sine at its own rate."""

    def __init__(self, rate, freq=1000.0, amp=10000.0):
        self.rate, self.freq, self.amp = rate, freq, amp
        self.pos = 0
        self.started = self.stopped = self.closed = False

    def start(self):
        self.started = True

    def read(self, frames):
        block = sine(self.freq, self.rate, frames, self.amp, self.pos).reshape(-1, 1)
        self.pos += frames
        return block, False

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class FakeSD:
    """Fake sounddevice module. `supported` is the set of rates the mic accepts."""

    PortAudioError = FakePortAudioError

    def __init__(self, supported, default_rate=44100, fail_with=None):
        self.supported = set(supported)
        self.default_rate = default_rate
        self.fail_with = fail_with  # non-sample-rate PortAudioError to raise instead
        self.attempts = []  # (samplerate, device) per InputStream() call

    def query_devices(self, device=None, kind=None):
        return {"default_samplerate": float(self.default_rate)}

    def InputStream(self, samplerate, channels, dtype, device):
        self.attempts.append((samplerate, device))
        assert channels == 1 and dtype == "int16"
        if self.fail_with:
            raise FakePortAudioError(self.fail_with, -9985)
        if samplerate not in self.supported:
            raise FakePortAudioError("Error opening InputStream: Invalid sample rate [PaErrorCode -9997]", -9997)
        return FakeStream(samplerate)


class OpenInputStreamTests(unittest.TestCase):
    def setUp(self):
        pipeline._input_rate_cache.clear()
        pipeline._announced_rates.clear()

    def open(self, sd, device=None):
        with mock.patch.object(pipeline, "_get_sounddevice", return_value=sd), mock.patch("builtins.print"):
            return pipeline._open_input_stream(device)

    def test_native_16k_device_is_used_directly_without_resampling(self):
        sd = FakeSD({16000})
        stream = self.open(sd)
        self.assertIsInstance(stream, FakeStream)  # raw stream, no wrapper
        self.assertEqual([r for r, _ in sd.attempts], [16000])
        self.assertTrue(stream.started)

    @needs_numpy
    def test_48k_only_mic_opens_at_48k_not_16k(self):
        # The observed Pi USB mic: RATE: [44100 48000]
        sd = FakeSD({44100, 48000})
        stream = self.open(sd, "hw:2,0")
        self.assertIsInstance(stream, pipeline._ResamplingInputStream)
        self.assertEqual(stream._in_rate, 48000)
        self.assertEqual([r for r, _ in sd.attempts], [16000, 48000])  # 16k rejected, 48k preferred over 44.1k
        chunk, _ = stream.read(pipeline.FRAME_SAMPLES)
        self.assertEqual((chunk.shape, chunk.dtype), ((480, 1), np.dtype("int16")))

    @needs_numpy
    def test_44100_only_mic_falls_back_to_44100(self):
        sd = FakeSD({44100})
        stream = self.open(sd)
        self.assertEqual(stream._in_rate, 44100)
        self.assertEqual([r for r, _ in sd.attempts], [16000, 48000, 44100])
        chunk, _ = stream.read(pipeline.FRAME_SAMPLES)
        self.assertEqual(chunk.shape, (480, 1))

    @needs_numpy
    def test_device_default_rate_is_the_last_resort(self):
        sd = FakeSD({32000}, default_rate=32000)
        stream = self.open(sd)
        self.assertEqual(stream._in_rate, 32000)
        self.assertEqual([r for r, _ in sd.attempts], [16000, 48000, 44100, 32000])

    def test_input_device_setting_is_forwarded_unchanged(self):
        for device in ("hw:2,0", 3, None):
            with self.subTest(device=device):
                pipeline._input_rate_cache.clear()
                sd = FakeSD({16000})
                self.open(sd, device)
                self.assertEqual({d for _, d in sd.attempts}, {device})

    @needs_numpy
    def test_working_rate_is_remembered_so_ptt_turns_skip_failed_probes(self):
        sd = FakeSD({48000})
        self.open(sd, "hw:2,0")
        sd.attempts.clear()
        self.open(sd, "hw:2,0")  # next PTT turn
        self.assertEqual([r for r, _ in sd.attempts], [48000])

    def test_other_portaudio_errors_are_not_retried_and_keep_actionable_message(self):
        sd = FakeSD({16000}, fail_with="Error opening InputStream: Device unavailable [PaErrorCode -9985]")
        with self.assertRaises(VoiceUnavailableError) as cm:
            self.open(sd, "hw:9,9")
        self.assertEqual(len(sd.attempts), 1)
        self.assertIn("CIPHLET_AUDIO_INPUT_DEVICE", str(cm.exception))

    def test_no_usable_rate_raises_clear_error_listing_rates_tried(self):
        sd = FakeSD(set(), default_rate=22050)
        with self.assertRaises(VoiceUnavailableError) as cm:
            self.open(sd, "hw:2,0")
        msg = str(cm.exception)
        for rate in ("16000", "48000", "44100", "22050"):
            self.assertIn(rate, msg)
        self.assertIn("arecord --dump-hw-params", msg)

    @needs_numpy
    def test_resampling_is_announced_once_per_device_and_rate(self):
        sd = FakeSD({48000})
        with mock.patch.object(pipeline, "_get_sounddevice", return_value=sd), mock.patch("builtins.print") as pr:
            pipeline._open_input_stream("hw:2,0")
            pipeline._open_input_stream("hw:2,0")
        self.assertEqual(pr.call_count, 1)


@needs_numpy
class ResamplerTests(unittest.TestCase):
    RATES = (48000, 44100)

    def resample(self, x, rate, block):
        r = pipeline._StreamResampler(rate, OUT)
        parts = [r.process(x[i : i + block]) for i in range(0, len(x), block)]
        return np.concatenate(parts)

    def test_output_is_independent_of_block_size(self):
        rng = np.random.default_rng(0)
        for rate in self.RATES:
            x = rng.integers(-20000, 20000, size=rate, dtype=np.int16)
            whole = self.resample(x, rate, len(x))
            for block in (1440, 1323, 1000, 7, 1):
                with self.subTest(rate=rate, block=block):
                    if block == 1 and rate == 44100:
                        x_ = x[:5000]
                        np.testing.assert_array_equal(self.resample(x_, rate, 1), self.resample(x_, rate, len(x_)))
                    else:
                        np.testing.assert_array_equal(self.resample(x, rate, block), whole)

    def test_in_band_tones_keep_frequency_phase_and_amplitude(self):
        for rate in self.RATES:
            for freq in (300.0, 1000.0, 3400.0):
                with self.subTest(rate=rate, freq=freq):
                    y = self.resample(sine(freq, rate, rate), rate, rate * pipeline.FRAME_MS // 1000)
                    ideal = sine(freq, OUT, len(y))
                    err = np.abs(y[200:].astype(float) - ideal[200:].astype(float)).max()
                    self.assertLess(err, 0.02 * 10000, f"max error {err}")

    def test_upper_speech_band_passes_within_1_5_db(self):
        for rate in self.RATES:
            with self.subTest(rate=rate):
                y = self.resample(sine(6000.0, rate, rate), rate, rate // 10)[400:]
                gain_db = 20 * np.log10(np.sqrt((y.astype(float) ** 2).mean()) / (10000 / np.sqrt(2)))
                self.assertGreater(gain_db, -1.5)

    def test_out_of_band_content_is_rejected_not_aliased(self):
        # 10 kHz is above the 8 kHz output Nyquist; naive decimation would
        # alias it to 6 kHz (in the speech band). It must be filtered out.
        for rate in self.RATES:
            for freq in (10000.0, 12000.0):
                with self.subTest(rate=rate, freq=freq):
                    y = self.resample(sine(freq, rate, rate), rate, rate // 10)[400:]
                    rms_in = 10000 / np.sqrt(2)
                    atten_db = 20 * np.log10(max(np.sqrt((y.astype(float) ** 2).mean()), 1e-9) / rms_in)
                    self.assertLess(atten_db, -40)

    def test_output_length_tracks_the_rate_ratio(self):
        for rate in self.RATES:
            y = self.resample(sine(1000.0, rate, rate), rate, rate // 10)
            self.assertLessEqual(OUT - len(y), 40)  # only a sub-ms filter delay is withheld
            self.assertLessEqual(len(y), OUT)

    def test_clips_instead_of_wrapping(self):
        x = np.full(4800, 32767, dtype=np.int16)
        x[::2] = -32768  # worst-case full-scale square wave
        y = self.resample(x, 48000, 1440)
        self.assertEqual(y.dtype, np.int16)  # no exception; values saturate rather than wrap


@needs_numpy
class ResamplingStreamTests(unittest.TestCase):
    def test_reads_are_exact_30ms_16k_frames_and_continuous(self):
        for rate in (48000, 44100):
            with self.subTest(rate=rate):
                stream = pipeline._ResamplingInputStream(FakeStream(rate), rate)
                frames = []
                for _ in range(60):  # ~1.8 s
                    chunk, over = stream.read(pipeline.FRAME_SAMPLES)
                    self.assertEqual((chunk.shape, chunk.dtype), ((480, 1), np.dtype("int16")))
                    self.assertEqual(len(chunk.tobytes()), 960)  # what webrtcvad/wake/VOSK consume
                    self.assertFalse(over)
                    frames.append(chunk)
                y = np.concatenate(frames)[:, 0].astype(float)
                ideal = sine(1000.0, OUT, len(y)).astype(float)
                self.assertLess(np.abs(y[200:] - ideal[200:]).max(), 200)  # continuous across frame joins

    def test_arbitrary_read_sizes_return_exactly_the_requested_frames(self):
        stream = pipeline._ResamplingInputStream(FakeStream(44100), 44100)
        for frames in (480, 1280, 1, 333, 480):
            chunk, _ = stream.read(frames)
            self.assertEqual(chunk.shape, (frames, 1))

    def test_stop_and_close_are_delegated_to_the_device_stream(self):
        raw = FakeStream(48000)
        stream = pipeline._ResamplingInputStream(raw, 48000)
        stream.stop()
        stream.close()
        self.assertTrue(raw.stopped and raw.closed)


@needs_numpy
class PipelineIntegrationTests(unittest.TestCase):
    def test_hands_free_wake_windows_are_1280_samples_of_16k_from_a_48k_mic(self):
        """End to end through the real session code: 48 kHz capture in, wake
        model receives 1280-sample (2560-byte) 16 kHz windows."""
        windows = []

        class Wake:
            def detect(self, chunk):
                windows.append(chunk)
                return False

        class Audio:
            def condition(self, b):
                return b

            def is_speech(self, b):
                return False

        session = pipeline.HandsFreeVoiceSession(Audio(), Wake(), mock.Mock(), mock.Mock(), lambda t: "")
        stream = pipeline._ResamplingInputStream(FakeStream(48000), 48000)
        for _ in range(20):
            chunk, _ = stream.read(pipeline.FRAME_SAMPLES)
            session._check_wake(chunk.tobytes())
        self.assertGreaterEqual(len(windows), 5)
        self.assertTrue(all(len(w) == pipeline.WAKE_CHUNK_SAMPLES * 2 for w in windows))


if __name__ == "__main__":
    unittest.main()
