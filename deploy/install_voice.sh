#!/usr/bin/env bash
# Ciphlet — voice runtime setup (§20B), run AFTER deploy/install_pi.sh.
#
# Installs the voice extras (mic/speaker I/O, wake word, STT, TTS) and
# downloads the actual model files each provider needs to run — none of
# that is bundled by the pip packages themselves. Requires real
# microphone/speaker hardware to actually use afterward; safe to run
# without it (this script only fetches software/models).
#
# Voice TTS note: en_US-amy-medium (Piper) is wired in here as a TEMPORARY
# functional-test voice only — see docs/CIPHLET_VERIFIED_STATE.md. It is
# NOT Ciphlet's permanent voice identity; TTS stays swappable behind
# ciphlet/voice/base.py::TTSProvider.
#
# Usage (from the Ciphlet repo root, on the Pi, after install_pi.sh):
#   bash deploy/install_voice.sh
#
# Safe to re-run: every step is idempotent (checks before downloading).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Ciphlet voice runtime setup =="
echo "Repo: $REPO_ROOT"

if [ ! -d .venv ]; then
    echo "No .venv found — run deploy/install_pi.sh first." >&2
    exit 1
fi
source .venv/bin/activate

# --- 1. System packages voice needs beyond install_pi.sh's core list ---
echo
echo "-- Installing system packages (sudo apt) --"
sudo apt-get update -y
sudo apt-get install -y unzip

# --- 2. Python voice extras (sounddevice, vosk, openwakeword, webrtcvad, piper-tts) ---
echo
echo "-- Installing Ciphlet voice extras (pip) --"
pip install -e '.[voice]'

MODELS_DIR="$REPO_ROOT/models"
mkdir -p "$MODELS_DIR/piper" "$MODELS_DIR/vosk"

# --- 3. Piper TTS voice model: en_US-amy-medium (TEMPORARY test voice) ---
PIPER_ONNX="$MODELS_DIR/piper/en_US-amy-medium.onnx"
PIPER_JSON="$MODELS_DIR/piper/en_US-amy-medium.onnx.json"
echo
echo "-- Fetching Piper voice: en_US-amy-medium (temporary test voice) --"
if [ ! -f "$PIPER_ONNX" ]; then
    curl -fL -o "$PIPER_ONNX" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx"
else
    echo "Already present: $PIPER_ONNX"
fi
if [ ! -f "$PIPER_JSON" ]; then
    curl -fL -o "$PIPER_JSON" \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium/en_US-amy-medium.onnx.json"
else
    echo "Already present: $PIPER_JSON"
fi

# --- 4. VOSK STT model: small English model (fast bring-up default) ---
VOSK_DIR="$MODELS_DIR/vosk/vosk-model-small-en-us-0.15"
echo
echo "-- Fetching VOSK STT model: vosk-model-small-en-us-0.15 --"
if [ ! -d "$VOSK_DIR" ]; then
    curl -fL -o /tmp/vosk-model-small-en-us-0.15.zip \
        "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
    unzip -q -o /tmp/vosk-model-small-en-us-0.15.zip -d "$MODELS_DIR/vosk"
    rm -f /tmp/vosk-model-small-en-us-0.15.zip
else
    echo "Already present: $VOSK_DIR"
fi
echo "(Optional accuracy upgrade later: vosk-model-en-us-0.22-lgraph, ~128MB,"
echo " from the same alphacephei.com/vosk/models page — larger/slower than"
echo " the small model above; not needed for functional testing.)"

# --- 5. openWakeWord: generic pretrained wake models ---
# No custom "Hey Ciphlet" model exists yet (that requires training a new
# model — out of scope here). This downloads openWakeWord's bundled
# generic pretrained models (e.g. "hey_jarvis", "alexa") so the hands-free
# pipeline itself (wake -> VAD -> STT -> brain -> TTS -> barge-in) can be
# exercised end-to-end on real hardware now, using one of those phrases
# instead of "Hey Ciphlet" until a custom model is trained.
echo
echo "-- Fetching openWakeWord pretrained models --"
python3 -c "import openwakeword.utils as u; u.download_models()"

echo
echo "== Voice runtime setup complete =="
echo
echo "Add these to your .env (or edit the existing blank entries):"
echo "  CIPHLET_PIPER_MODEL=$PIPER_ONNX"
echo "  CIPHLET_VOSK_MODEL_PATH=$VOSK_DIR"
echo "  # CIPHLET_WAKE_MODEL left unset on purpose: no trained \"Hey Ciphlet\""
echo "  # model exists yet, so openWakeWord's default generic pretrained"
echo "  # models load instead (test with \"hey jarvis\" / \"alexa\" for now)."
echo
echo "Test push-to-talk (simplest bring-up path, §24 Stage 1-2):"
echo "  source .venv/bin/activate && ciphlet voice --ptt"
echo
echo "Test hands-free (wake word + VAD + barge-in):"
echo "  source .venv/bin/activate && ciphlet voice --hands-free"
