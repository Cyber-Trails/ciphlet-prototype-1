"""Concrete Pi-targeted voice providers (architecture §20B candidates).

Every class here does a lazy import of its ML/audio dependency and raises
VoiceUnavailableError if it's missing, so importing this module — or running
Ciphlet in text mode — never requires any of these packages to be installed.

These are the leading candidates named in §20B, not a frozen final stack:

- WebRTCVadAudioProcessor — WebRTC-class VAD. `condition()` is currently a
  pass-through placeholder; RNNoise-class denoising and real acoustic-echo
  mitigation are future work, not implemented here.
- OpenWakeWordProvider — openWakeWord, run on its ONNX backend (no
  tflite-runtime). Ships with generic pretrained models
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
            try:
                self._vad = webrtcvad.Vad(self._aggressiveness)
            except Exception as exc:
                raise VoiceUnavailableError(
                    f"Failed to initialize WebRTC VAD (aggressiveness={self._aggressiveness}): {exc}"
                ) from exc
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
                    f"'openwakeword' (or one of its dependencies) is not importable: {exc}. "
                    "Run deploy/install_voice.sh on the Pi — it installs openWakeWord separately "
                    "(--no-deps) because its tflite-runtime requirement is unsatisfiable on Python 3.13."
                ) from exc
            kwargs = {"wakeword_models": [self._model_path]} if self._model_path else {}
            try:
                # ONNX backend explicitly: tflite-runtime has no wheels for
                # Python >= 3.12 (see pyproject.toml voice extra), and
                # openWakeWord's implicit tflite->onnx fallback only fires
                # in some cases and logs a misleading warning.
                self._model = Model(inference_framework="onnx", **kwargs)
            except Exception as exc:
                where = f" from '{self._model_path}'" if self._model_path else " (bundled pretrained models)"
                raise VoiceUnavailableError(
                    f"Failed to load openWakeWord model{where}: {exc}. If using the bundled "
                    "pretrained models, run: python3 -c \"import openwakeword.utils as u; u.download_models()\". "
                    "If using CIPHLET_WAKE_MODEL, check the path is a valid .onnx model file "
                    "(.tflite models are not supported — Ciphlet runs openWakeWord on ONNX)."
                ) from exc
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
            try:
                self._model = Model(self._model_path)
            except Exception as exc:
                raise VoiceUnavailableError(
                    f"Failed to load VOSK model at '{self._model_path}': {exc}. Check CIPHLET_VOSK_MODEL_PATH "
                    "points at an unzipped VOSK model directory (see deploy/install_voice.sh)."
                ) from exc
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
        output_device: str | None = None,
    ) -> None:
        self._model_path = model_path
        self._sample_rate = sample_rate
        self._piper_bin = piper_bin
        self._player_bin = player_bin
        self._output_device = output_device
        self._piper_proc: subprocess.Popen | None = None
        self._player_proc: subprocess.Popen | None = None
        self._stopped = False

    def speak(self, text: str) -> None:
        if shutil.which(self._piper_bin) is None:
            raise VoiceUnavailableError(f"'{self._piper_bin}' binary not found on PATH. Install Piper on the Pi.")
        if shutil.which(self._player_bin) is None:
            raise VoiceUnavailableError(f"'{self._player_bin}' binary not found on PATH.")

        player_cmd = [self._player_bin, "-q"]
        if self._output_device:
            player_cmd += ["-D", self._output_device]
        player_cmd += ["-r", str(self._sample_rate), "-f", "S16_LE", "-t", "raw", "-"]

        self._stopped = False
        piper = subprocess.Popen(
            [self._piper_bin, "--model", self._model_path, "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._piper_proc = piper
        player = subprocess.Popen(player_cmd, stdin=piper.stdout, stderr=subprocess.PIPE)
        self._player_proc = player
        assert piper.stdout is not None
        piper.stdout.close()  # let piper see SIGPIPE if player exits early (barge-in stop())

        try:
            assert piper.stdin is not None
            piper.stdin.write(text.encode("utf-8"))
            piper.stdin.close()
            _, player_err = player.communicate()
            piper_err = piper.stderr.read() if piper.stderr else b""
            piper.wait()
        finally:
            self._piper_proc = None
            self._player_proc = None

        if self._stopped:
            return  # intentional barge-in interruption (§4.6), not a failure

        if piper.returncode != 0:
            raise VoiceUnavailableError(
                f"Piper synthesis failed (exit {piper.returncode}): {piper_err.decode(errors='replace').strip()}"
            )
        if player.returncode != 0:
            raise VoiceUnavailableError(
                f"Audio playback failed (exit {player.returncode}): {player_err.decode(errors='replace').strip()}"
            )

    def stop(self) -> None:
        # True barge-in (§4.6): kill both the player and the (possibly
        # still-synthesizing) piper process, not just playback — otherwise a
        # repeatedly-interrupted piper process can pile up/hang on a full
        # stdout pipe with no reader.
        self._stopped = True
        if self._player_proc is not None:
            self._player_proc.terminate()
        if self._piper_proc is not None:
            self._piper_proc.terminate()
