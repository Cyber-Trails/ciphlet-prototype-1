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
# build-essential + python3-dev: webrtcvad ships sdist-only (no wheels), so pip
# compiles its C extension against the venv Python's headers. alsa-utils:
# aplay/amixer/arecord for speaker playback, detection and volume.
sudo apt-get install -y unzip build-essential python3-dev alsa-utils

# --- 2. Python voice extras (sounddevice, vosk, webrtcvad, piper-tts + openWakeWord's ONNX-path deps) ---
echo
echo "-- Installing Ciphlet voice extras (pip) --"
pip install -e '.[voice]'

# openWakeWord is installed separately with --no-deps: its metadata hard-requires
# `tflite-runtime` on Linux, which has no wheels for Python >= 3.12 (Pi OS ships
# 3.13), so a normal install is unsatisfiable. Ciphlet runs openWakeWord on its
# ONNX backend instead (see ciphlet/voice/providers.py), and its real runtime
# deps (onnxruntime, scipy, scikit-learn, tqdm, requests) are already installed
# by the '.[voice]' extra above. Exact pin: --no-deps bypasses the resolver, and
# the ONNX-only path was verified against 0.6.0 specifically.
echo
echo "-- Installing openWakeWord 0.6.0 (--no-deps, ONNX backend; no tflite-runtime) --"
pip install --no-deps 'openwakeword==0.6.0'

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

# --- 5. openWakeWord: generic pretrained wake models (fallback) ---
# Always fetched, even if a custom model (below) is already trained, since
# it's the harmless, always-useful fallback and costs little to have.
echo
echo "-- Fetching openWakeWord pretrained models --"
python3 -c "import openwakeword.utils as u; u.download_models()"

# --- 6. Custom "Hey Ciphlet" wake model, if already trained ---
# Training happens off-Pi (GPU-class job) — see deploy/wake_word/TRAINING.md.
# This just checks whether the trained file has already been placed here.
WAKE_MODEL="$MODELS_DIR/wake/hey_ciphlet.onnx"
mkdir -p "$MODELS_DIR/wake"

# --- 7. Wake-word smoke test: load the model(s) through Ciphlet's own provider ---
# Fails the install loudly here rather than at first `ciphlet voice --hands-free`.
# Runs one silent 80ms window (1280 samples of int16) through the ONNX pipeline.
echo
echo "-- Verifying wake-word runtimes (openWakeWord ONNX + PocketSphinx \"Hey Ciphlet\") --"
WAKE_CHECK_PATH=""
[ -f "$WAKE_MODEL" ] && WAKE_CHECK_PATH="$WAKE_MODEL"
WAKE_CHECK_PATH="$WAKE_CHECK_PATH" python3 - <<'PY'
import os, sys
from ciphlet.voice.base import VoiceUnavailableError
from ciphlet.voice.providers import OpenWakeWordProvider

path = os.environ.get("WAKE_CHECK_PATH") or None
try:
    OpenWakeWordProvider(model_path=path).detect(bytes(1280 * 2))
except VoiceUnavailableError as exc:
    print(f"Wake-word runtime check FAILED: {exc}", file=sys.stderr)
    sys.exit(1)
print("Wake-word runtime OK (" + (path or "bundled pretrained models") + ")")

# "Hey Ciphlet" via PocketSphinx keyword spotting (no trained model needed)
from ciphlet.voice.providers import PocketSphinxWakeProvider

try:
    PocketSphinxWakeProvider().detect(bytes(1280 * 2))
except VoiceUnavailableError as exc:
    print(f'"Hey Ciphlet" (PocketSphinx) wake check FAILED: {exc}', file=sys.stderr)
    sys.exit(1)
print('"Hey Ciphlet" wake phrase (PocketSphinx) OK')
PY

# --- 8. Wire model paths into .env (idempotent — never overwrites your config) ---
# deploy/env_defaults.py adds a managed key only if it is missing, fills it only
# if its value is blank, and leaves any non-empty value, unrelated key, secret,
# or comment byte-for-byte untouched. CIPHLET_WAKE_MODEL is only touched when a
# trained hey_ciphlet.onnx actually exists; otherwise it is left exactly as-is.
echo
echo "-- Updating .env (missing/blank voice keys only) --"
if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Created .env from .env.example (none existed)."
    else
        : > .env
        echo "Created empty .env (none existed)."
    fi
fi
python3 deploy/env_defaults.py --env .env \
    --set "CIPHLET_PIPER_MODEL=$PIPER_ONNX" \
    --set "CIPHLET_VOSK_MODEL_PATH=$VOSK_DIR" \
    --set-if-file "CIPHLET_WAKE_MODEL=$WAKE_MODEL"

# --- 9. Speaker: detect, unmute, verify playback, record in .env ---
# deploy/audio_setup.py picks the playback card (USB first), unmutes/raises its
# volume only where muted or low, plays a short beep through a plughw: route
# (so ALSA converts rates for speakers that only do 44.1/48 kHz), and writes
# CIPHLET_AUDIO_OUTPUT_DEVICE only if it is missing/blank. Never fails the install.
echo
echo "-- Setting up the speaker (you should hear a short beep) --"
python3 deploy/audio_setup.py --env .env || echo "(speaker auto-setup skipped; 'ciphlet voice --selftest' will diagnose)"

echo
echo "== Voice runtime setup complete =="
echo
echo ".env is configured for voice (existing non-empty values were preserved)."
if [ ! -f "$WAKE_MODEL" ]; then
    echo "No trained \"Hey Ciphlet\" model at $WAKE_MODEL yet, so CIPHLET_WAKE_MODEL"
    echo "was left alone and Ciphlet wakes on \"Hey Ciphlet\" using PocketSphinx keyword"
    echo "spotting (no training needed; tune with CIPHLET_WAKE_KWS_THRESHOLD). A trained"
    echo "openWakeWord model would be more accurate: see deploy/wake_word/TRAINING.md"
    echo "(GPU-class job — run on Colab, not here), place the result at $WAKE_MODEL,"
    echo "and re-run this script."
fi
echo
echo "Mic/speaker device selection (only needed if the Pi's default audio"
echo "device isn't the mic/speaker you want to use):"
echo "  CIPHLET_AUDIO_INPUT_DEVICE=   # list mics: python3 -m sounddevice"
echo "  CIPHLET_AUDIO_OUTPUT_DEVICE=  # list speakers: aplay -L"

# --- 10. Integrated hardware self-test (speaker + mic + VOSK + wake + barge-in) ---
# Interactive (you listen, then speak), so only offered when run from a terminal.
if [ -t 0 ]; then
    echo
    read -r -p "Run the integrated voice self-test now? [Y/n] " REPLY_YN || REPLY_YN="n"
    case "$REPLY_YN" in
        [nN]*) ;;
        *) python3 -m ciphlet voice --selftest || true ;;
    esac
fi

echo
echo "Voice commands (activate the venv first: source .venv/bin/activate):"
echo "  ciphlet voice --selftest     # integrated check: speaker, mic, VOSK, wake, barge-in safety"
echo "  ciphlet voice --ptt          # push-to-talk"
echo "  ciphlet voice --hands-free   # wake word + listen + reply + barge-in"
