#!/usr/bin/env bash
# Mac -> Pi deploy. Mac `main` is canonical; the Pi directory is NOT a git repo,
# so code is pushed with rsync (never `git pull` on the Pi).
#
# Usage (from the Mac, in the repo):
#   bash deploy/sync_to_pi.sh              # rsync code to the Pi
#   bash deploy/sync_to_pi.sh --dry-run    # show what would change, change nothing
#   bash deploy/sync_to_pi.sh --install    # rsync, then run deploy/install_voice.sh on the Pi
#
# Runtime state on the Pi is never touched: .env (secrets/config), .venv,
# models/, data/, *.db, caches. No --delete is used, so Pi-only files survive.
#
# Overrides: CIPHLET_PI (default ciphlet@10.0.0.23), CIPHLET_PI_DIR
# (default /home/ciphlet/Developer/CIPHLET), CIPHLET_SYNC_DEST (full rsync
# destination; used to test the exclusions against a local directory).

set -euo pipefail

PI="${CIPHLET_PI:-ciphlet@10.0.0.23}"
PI_DIR="${CIPHLET_PI_DIR:-/home/ciphlet/Developer/CIPHLET}"
DEST="${CIPHLET_SYNC_DEST:-$PI:$PI_DIR/}"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/"

DRY=""
INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY="--dry-run" ;;
        --install) INSTALL=1 ;;
        *) echo "unknown option: $arg (use --dry-run and/or --install)" >&2; exit 2 ;;
    esac
done

echo "== Syncing $SRC -> $DEST ${DRY:+(dry run)} =="
rsync -az --itemize-changes $DRY \
    --exclude '.git/' \
    --exclude '.venv/' \
    --exclude 'models/' \
    --exclude 'data/' \
    --exclude '.env' \
    --exclude '*.db' --exclude '*.db-shm' --exclude '*.db-wal' --exclude '*.sqlite*' \
    --exclude '__pycache__/' --exclude '*.pyc' \
    --exclude '.DS_Store' --exclude '.claude/' \
    "$SRC" "$DEST"

if [ "$INSTALL" = 1 ] && [ -z "$DRY" ]; then
    echo "== Running deploy/install_voice.sh on the Pi =="
    # -t: the installer uses sudo and interactive prompts
    ssh -t "$PI" "cd '$PI_DIR' && bash deploy/install_voice.sh"
fi
