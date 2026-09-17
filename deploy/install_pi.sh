#!/usr/bin/env bash
# Ciphlet — single-command Raspberry Pi 5 (8GB) deployment.
#
# Installs the free/local baseline: Ollama (persistent local LLM server) +
# a small Pi-appropriate model, Ciphlet's own Python package (core deps
# only — cloud routing + memory + CLI), and prepares .env. Voice
# dependencies (VOSK/Piper/openWakeWord/etc.) are optional and installed
# separately (see the printed instructions at the end) since they require
# real microphone/speaker hardware to actually use.
#
# Usage (from the Ciphlet repo root, on the Pi):
#   bash deploy/install_pi.sh
#
# Safe to re-run: every step is idempotent (checks before installing).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "== Ciphlet Pi deployment =="
echo "Repo: $REPO_ROOT"

# --- 1. System packages needed by the core + (later, optional) voice stack ---
echo
echo "-- Installing system packages (sudo apt) --"
sudo apt-get update -y
sudo apt-get install -y \
    python3-venv python3-pip \
    portaudio19-dev libasound2-dev alsa-utils \
    curl

# --- 2. Ollama: persistent local LLM server (the free/local baseline) ---
echo
echo "-- Installing Ollama (if not already installed) --"
if ! command -v ollama >/dev/null 2>&1; then
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "Ollama already installed: $(command -v ollama)"
fi

echo "-- Ensuring the Ollama service is running --"
if command -v systemctl >/dev/null 2>&1 && systemctl list-unit-files | grep -q '^ollama.service'; then
    sudo systemctl enable --now ollama
else
    # Fallback: start it in the background if it isn't already up.
    if ! curl -fsS http://localhost:11434/api/tags >/dev/null 2>&1; then
        nohup ollama serve >/tmp/ollama_serve.log 2>&1 &
        sleep 3
    fi
fi

# gemma3:1b-it-q4_K_M replaced an unsuccessful qwen2.5:3b-instruct-q4_K_M
# default: real Pi measurements on two different models both showed full
# prompt re-evaluation every turn — a verified Ollama CPU-backend bug for
# /api/chat (ollama/ollama#14780), fixed in code via /api/generate +
# context. A smaller 1B model on top of that fix targets conversational
# speed for the voice-first baseline.
DEFAULT_MODEL="gemma3:1b-it-q4_K_M"
echo "-- Pulling the default local model ($DEFAULT_MODEL) --"
ollama pull "$DEFAULT_MODEL"

# --- 3. Ciphlet's own Python package (core: cloud routing + memory + CLI) ---
echo
echo "-- Setting up Ciphlet's Python virtual environment --"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# --- 4. Environment file ---
if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "-- Created .env from .env.example — edit it to add GROQ_API_KEY etc. --"
else
    echo
    echo ".env already exists — left untouched."
fi

echo
echo "== Core install complete =="
echo "Free/local baseline is ready: 'ciphlet chat --local-only' will work now"
echo "(uses Ollama + $DEFAULT_MODEL, zero API credits required)."
echo
echo "Optional: add a free Groq key to .env (GROQ_API_KEY=...) for stronger"
echo "cloud-enhanced replies when available — never required."
echo
echo "Optional: try a stronger local model instead of $DEFAULT_MODEL (this"
echo "does not remove/replace the one just installed):"
echo "  ollama pull qwen3:4b-instruct-q4_K_M"
echo "  # then set CIPHLET_OLLAMA_MODEL=qwen3:4b-instruct-q4_K_M in .env"
echo
echo "Optional: for voice (mic/speaker), also run:"
echo "  source .venv/bin/activate && pip install -e '.[voice]'"
echo "  # then download a VOSK STT model and a Piper voice model, and set"
echo "  # CIPHLET_VOSK_MODEL_PATH / CIPHLET_PIPER_MODEL in .env"
echo
echo "Start Ciphlet:"
echo "  source .venv/bin/activate && ciphlet chat"
