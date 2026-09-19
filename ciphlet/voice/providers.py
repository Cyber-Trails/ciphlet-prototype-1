"""Concrete Pi-targeted voice providers (architecture §20B candidates).

Every class here does a lazy import of its ML/audio dependency and raises
VoiceUnavailableError if it's missing, so importing this module — or running
Ciphlet in text mode — never requires any of these packages to be installed.

These are the leading candidates named in §20B, not a frozen final stack:

- WebRTCVadAudioProcessor — WebRTC-class VAD. `condition()` is currently a
  pass-through placeholder; RNNoise-class denoising and real acoustic-echo
  mitigation are future work, not implemented here.
- OpenWakeWordProvider — openWakeWord, run on its ONNX backend (no
  tflite-runtime). Ships with generic wake-phrase models
  only; a custom "Hey Ciphlet" model must be trained before wake detection
  matches the intended phrase (§4.1). Point CIPHLET_WAKE_MODEL at a trained
  model file once one exists.
- VoskSTT — VOSK, offline batch-decode STT (donor-proven, §20B).
- PiperTTS — Piper via its CLI binary + `aplay` for playback, so stop()
  can kill the playback subprocess for true barge-in (§4.6). Piper is a
  candidate, not Ciphlet's permanently frozen final voice (§20B).
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

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


# openWakeWord's bundled models also include non-wake-phrase classifiers
# ("timer", "weather") that would fire on ordinary speech, so only the actual
# wake-phrase models are loaded when no custom CIPHLET_WAKE_MODEL is set.
GENERIC_WAKE_PHRASES = ("alexa", "hey_mycroft", "hey_jarvis", "hey_rhasspy")


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
            kwargs = {"wakeword_models": [self._model_path] if self._model_path else list(GENERIC_WAKE_PHRASES)}
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

    def reset(self) -> None:
        # openWakeWord keeps a rolling audio-feature/score buffer; clear it so
        # the phrase (or TTS echo) from before a turn can't re-trigger.
        if self._model is not None:
            self._model.reset()


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


def _playback_device(device: str | None) -> str | None:
    """`aplay -D` value. A bare `hw:X,Y` is raw hardware with NO rate/format
    conversion, so it fails whenever the speaker's supported rates differ from
    Piper's voice rate (same failure class as a USB mic that only does
    44.1/48 kHz). `plughw:X,Y` is the same card with ALSA doing the conversion."""
    if device and device.startswith("hw:"):
        return "plug" + device
    return device


def _voice_sample_rate(model_path: str, fallback: int) -> int:
    """Piper emits raw PCM at the *voice's* rate, recorded in `<model>.json`."""
    try:
        with open(model_path + ".json", encoding="utf-8") as fh:
            return int(json.load(fh)["audio"]["sample_rate"])
    except (OSError, ValueError, KeyError, TypeError):
        return fallback


class PiperTTS(TTSProvider):
    def __init__(
        self,
        model_path: str,
        sample_rate: int | None = None,
        piper_bin: str = "piper",
        player_bin: str = "aplay",
        output_device: str | None = None,
    ) -> None:
        self._model_path = model_path
        # Default: read the real rate from the voice's .onnx.json (22050 if unreadable).
        self._sample_rate = sample_rate or _voice_sample_rate(model_path, 22050)
        self._piper_bin = piper_bin
        self._player_bin = player_bin
        self._output_device = output_device
        self._piper_proc: subprocess.Popen | None = None
        self._player_proc: subprocess.Popen | None = None
        self._stopped = False

    def _piper_command(self) -> list[str]:
        """The `piper` script if reachable, else `python -m piper` from the
        running interpreter — so it works without the venv being activated."""
        found = shutil.which(self._piper_bin)
        if found:
            return [found]
        sibling = Path(sys.executable).parent / self._piper_bin
        if sibling.exists():
            return [str(sibling)]
        if importlib.util.find_spec("piper") is not None:
            return [sys.executable, "-m", "piper"]
        raise VoiceUnavailableError(
            f"Piper not found ('{self._piper_bin}' is not on PATH and the 'piper' package isn't installed). "
            "Run deploy/install_voice.sh on the Pi."
        )

    def speak(self, text: str) -> None:
        piper_cmd = self._piper_command()
        if shutil.which(self._player_bin) is None:
            raise VoiceUnavailableError(
                f"'{self._player_bin}' not found on PATH. Install it with: sudo apt-get install -y alsa-utils"
            )

        player_cmd = [self._player_bin, "-q"]
        device = _playback_device(self._output_device)
        if device:
            player_cmd += ["-D", device]
        player_cmd += ["-r", str(self._sample_rate), "-f", "S16_LE", "-c", "1", "-t", "raw", "-"]

        self._stopped = False
        # stderr goes to temp files, not pipes: an unread pipe can fill and
        # deadlock a chatty child, and we still want the text on failure.
        with tempfile.TemporaryFile() as piper_err, tempfile.TemporaryFile() as player_err:
            piper = subprocess.Popen(
                [*piper_cmd, "--model", self._model_path, "--output-raw"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=piper_err,
            )
            self._piper_proc = piper
            player = subprocess.Popen(player_cmd, stdin=piper.stdout, stderr=player_err)
            self._player_proc = player
            assert piper.stdout is not None
            piper.stdout.close()  # let piper see SIGPIPE if player exits early (barge-in stop())

            try:
                assert piper.stdin is not None
                try:
                    piper.stdin.write(text.encode("utf-8"))
                    piper.stdin.close()
                except BrokenPipeError:
                    pass  # piper died early; its exit code + stderr are reported below
                player.wait()
                piper.wait()
            finally:
                self._piper_proc = None
                self._player_proc = None

            if self._stopped:
                return  # intentional barge-in interruption (§4.6), not a failure

            piper_err.seek(0)
            player_err.seek(0)
            piper_msg = piper_err.read().decode(errors="replace").strip()
            player_msg = player_err.read().decode(errors="replace").strip()

        if piper.returncode != 0:
            raise VoiceUnavailableError(f"Piper synthesis failed (exit {piper.returncode}): {piper_msg}")
        if player.returncode != 0:
            where = f" on '{device}'" if device else ""
            raise VoiceUnavailableError(
                f"Audio playback failed{where} (exit {player.returncode}): {player_msg} — check the speaker "
                "with 'aplay -l', or set CIPHLET_AUDIO_OUTPUT_DEVICE (deploy/install_voice.sh detects it)."
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
