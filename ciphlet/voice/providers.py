"""Concrete Pi-targeted voice providers (architecture §20B candidates).

Every class here does a lazy import of its ML/audio dependency and raises
VoiceUnavailableError if it's missing, so importing this module — or running
Ciphlet in text mode — never requires any of these packages to be installed.

These are the leading candidates named in §20B, not a frozen final stack:

- WebRTCVadAudioProcessor — WebRTC-class VAD. `condition()` is currently a
  pass-through placeholder; RNNoise-class denoising and real acoustic-echo
  mitigation are future work, not implemented here.
- OpenWakeWordProvider — openWakeWord. Ships with generic pretrained models
  only; a custom "Hey Ciphlet" model must be trained before wake detection
  matches the intended phrase (§4.1). Point CIPHLET_WAKE_MODEL at a trained
  model file once one exists.
- VoskSTT — VOSK, offline batch-decode STT (donor-proven, §20B).
- PiperTTS — Piper via its CLI binary + `aplay` for playback, so stop()
  can kill the playback subprocess for true barge-in (§4.6). Piper is a
  candidate, not Ciphlet's permanently frozen final voice (§20B).
"""

from __future__ import annotations

import shutil
import subprocess

from ciphlet.voice.base import AudioProcessor, STTProvider, TTSProvider, VoiceUnavailableError, WakeProvider


class WebRTCVadAudioProcessor(AudioProcessor):
    def __init__(self, sample_rate: int = 16000, aggressiveness: int = 2) -> None:
        self._sample_rate = sample_rate
        self._aggressiveness = aggressiveness
        self._vad = None

    def _get_vad(self):
        if self._vad is None:
            try:
                import webrtcvad
            except ImportError as exc:
                raise VoiceUnavailableError(
                    "'webrtcvad' is not installed. Install Ciphlet's voice extras on the Pi."
                ) from exc
            self._vad = webrtcvad.Vad(self._aggressiveness)
        return self._vad

    def condition(self, audio: bytes) -> bytes:
        # RNNoise-class denoise / echo mitigation is a future candidate
        # (§20B); pass-through for now.
        return audio

    def is_speech(self, audio_chunk: bytes) -> bool:
        return self._get_vad().is_speech(audio_chunk, self._sample_rate)


class OpenWakeWordProvider(WakeProvider):
    """openWakeWord expects ~80ms (1280-sample @16kHz) windows; detect() here
    just runs prediction on whatever chunk it's handed. The caller
    (voice/pipeline.py HandsFreeVoiceSession) is responsible for
    accumulating VAD-sized frames into properly-sized windows before
    calling this — see WAKE_CHUNK_SAMPLES there."""

    def __init__(self, model_path: str | None = None, threshold: float = 0.5) -> None:
        self._model_path = model_path
        self._threshold = threshold
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from openwakeword.model import Model
            except ImportError as exc:
                raise VoiceUnavailableError(
                    "'openwakeword' is not installed. Install Ciphlet's voice extras on the Pi."
                ) from exc
            kwargs = {"wakeword_models": [self._model_path]} if self._model_path else {}
            self._model = Model(**kwargs)
        return self._model

    def detect(self, audio_chunk: bytes) -> bool:
        import numpy as np

        model = self._get_model()
        samples = np.frombuffer(audio_chunk, dtype=np.int16)
        predictions = model.predict(samples)
        score = max(predictions.values()) if predictions else 0.0
        return score >= self._threshold


class VoskSTT(STTProvider):
    """VOSK — fully offline, streaming-capable, proven on Pi-class hardware
    (adopt-adapt evidence: duckida/RPi-local-voice-assistant uses it as its
    sole STT; see docs/THIRD_PARTY_NOTICES.md). Replaces an earlier
    faster-whisper candidate that was never hardware-tested; VOSK's lighter
    footprint and simpler batch-decode API are a better fit here.
    `model_path` is a directory (an unzipped VOSK model, e.g.
    vosk-model-en-us-0.22-lgraph), not a single file."""

    def __init__(self, model_path: str, sample_rate: int = 16000) -> None:
        self._model_path = model_path
        self._sample_rate = sample_rate
        self._model = None

    def _get_model(self):
        if self._model is None:
            try:
                from vosk import Model
            except ImportError as exc:
                raise VoiceUnavailableError(
                    "'vosk' is not installed. Install Ciphlet's voice extras on the Pi."
                ) from exc
            self._model = Model(self._model_path)
        return self._model

    def transcribe(self, audio: bytes) -> str:
        import json

        model = self._get_model()

        try:
            from vosk import KaldiRecognizer
        except ImportError as exc:
            raise VoiceUnavailableError(
                "'vosk' is not installed. Install Ciphlet's voice extras on the Pi."
            ) from exc

        recognizer = KaldiRecognizer(model, self._sample_rate)
        recognizer.AcceptWaveform(audio)
        result = json.loads(recognizer.FinalResult())
        return result.get("text", "").strip()


class PiperTTS(TTSProvider):
    def __init__(
        self,
        model_path: str,
        sample_rate: int = 22050,
        piper_bin: str = "piper",
        player_bin: str = "aplay",
    ) -> None:
        self._model_path = model_path
        self._sample_rate = sample_rate
        self._piper_bin = piper_bin
        self._player_bin = player_bin
        self._player_proc: subprocess.Popen | None = None

    def speak(self, text: str) -> None:
        if shutil.which(self._piper_bin) is None:
            raise VoiceUnavailableError(f"'{self._piper_bin}' binary not found on PATH. Install Piper on the Pi.")
        if shutil.which(self._player_bin) is None:
            raise VoiceUnavailableError(f"'{self._player_bin}' binary not found on PATH.")

        piper = subprocess.Popen(
            [self._piper_bin, "--model", self._model_path, "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
        )
        player = subprocess.Popen(
            [self._player_bin, "-q", "-r", str(self._sample_rate), "-f", "S16_LE", "-t", "raw", "-"],
            stdin=piper.stdout,
        )
        self._player_proc = player
        try:
            assert piper.stdin is not None
            piper.stdin.write(text.encode("utf-8"))
            piper.stdin.close()
            player.wait()
        finally:
            self._player_proc = None

    def stop(self) -> None:
        if self._player_proc is not None:
            self._player_proc.terminate()
            self._player_proc = None
