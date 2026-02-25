#!/usr/bin/env bash
# Start miniAgent backend (requires conda miniAgent env).
# Usage: ./start-backend.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"

# Load conda and activate miniAgent env
if ! command -v conda &>/dev/null; then
  if [[ -f /gpfs/software/miniforge3/25.3.1-3/etc/profile.d/conda.sh ]]; then
    source /gpfs/software/miniforge3/25.3.1-3/etc/profile.d/conda.sh
  else
    echo "Run first: module load conda/Miniforge3-25.3.1-3"
    exit 1
  fi
fi
conda activate miniAgent

cd "$BACKEND_DIR"
exec uvicorn app:app --port 8002 --host 0.0.0.0 --reload
