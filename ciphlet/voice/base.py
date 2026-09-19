"""Voice provider interfaces (architecture §20B).

Wake word, VAD/audio conditioning, STT, and TTS are kept behind these four
interfaces specifically so no concrete engine gets bound into the pipeline
permanently (§20B: "Piper must not automatically become Ciphlet's permanent
final voice merely because it is local" — the same non-freezing applies to
every provider here).
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class VoiceUnavailableError(Exception):
    """Raised when a voice provider's dependencies/hardware aren't available.

    Voice is optional in this build — the text conversation path must keep
    working even when no microphone/speaker/ML packages are present.
    """


class AudioProcessor(ABC):
    """Conditioning (denoise/echo mitigation) + voice activity detection."""

    @abstractmethod
    def condition(self, audio: bytes) -> bytes:
        """Return denoised/conditioned audio for the given raw PCM chunk."""

    @abstractmethod
    def is_speech(self, audio_chunk: bytes) -> bool:
        """VAD: does this chunk contain speech?"""


class WakeProvider(ABC):
    @abstractmethod
    def detect(self, audio_chunk: bytes) -> bool:
        """Does this chunk contain the wake phrase ("Hey Ciphlet")?"""

    def reset(self) -> None:
        """Forget buffered audio/scores (e.g. after a turn, so the wake phrase
        or TTS echo from before it can't re-trigger). Optional; no-op default."""


class STTProvider(ABC):
    @abstractmethod
    def transcribe(self, audio: bytes) -> str:
        """Transcribe a captured utterance to text."""


class TTSProvider(ABC):
    @abstractmethod
    def speak(self, text: str) -> None:
        """Synthesize and play text. Should block until playback completes
        or stop() is called."""

    @abstractmethod
    def stop(self) -> None:
        """Immediately halt any in-progress playback (true barge-in, §4.6)."""
