#!/usr/bin/env bash
# Start Codex in the miniAgent environment with OMX available.
# Usage: ./start-codex.sh [codex args...]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONDA_SH="/gpfs/software/miniforge3/25.3.1-3/etc/profile.d/conda.sh"
MINIAGENT_BIN="/gpfs/home/yininz6/.conda/envs/miniAgent/bin"

# Load conda and activate miniAgent env.
if ! command -v conda &>/dev/null; then
  if [[ -f "$CONDA_SH" ]]; then
    # shellcheck disable=SC1090
    source "$CONDA_SH"
  else
    echo "Run first: module load conda/Miniforge3-25.3.1-3"
    exit 1
  fi
fi
conda activate miniAgent

# Keep the environment binaries first on PATH after activation.
export PATH="$MINIAGENT_BIN:$PATH"

# Some login shells do not preserve the Cursor-installed Codex binary on PATH.
# When that happens, discover the newest available Codex install explicitly.
if ! command -v codex &>/dev/null; then
  mapfile -t CODEX_DIRS < <(ls -td /gpfs/home/yininz6/.cursor-server/extensions/openai.chatgpt-*/bin/linux-x86_64 2>/dev/null || true)
  if [[ "${#CODEX_DIRS[@]}" -gt 0 ]]; then
    export PATH="${CODEX_DIRS[0]}:$PATH"
    hash -r
  fi
fi

if ! command -v codex &>/dev/null; then
  echo "Codex CLI was not found."
  echo "Expected a binary in /gpfs/home/yininz6/.cursor-server/extensions/openai.chatgpt-*/bin/linux-x86_64/"
  exit 1
fi

cd "$SCRIPT_DIR"
exec codex "$@"
