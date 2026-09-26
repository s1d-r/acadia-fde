#!/usr/bin/env bash
# One command setup without Docker.
#
#     ./scripts/run.sh
#
# Creates a virtual environment, installs the project, and starts the service
# on http://127.0.0.1:8000. Safe to run again: it reuses what is already there.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python

if [ ! -d .venv ]; then
  echo "Creating .venv"
  "$PYTHON" -m venv .venv
fi

VENV_PYTHON=".venv/bin/python"
[ -x "$VENV_PYTHON" ] || VENV_PYTHON=".venv/Scripts/python.exe"

echo "Installing dependencies"
"$VENV_PYTHON" -m pip install --quiet --upgrade pip
"$VENV_PYTHON" -m pip install --quiet -e ".[dev]"

# The service needs a model server. It is not started here, because on a
# developer machine Ollama is usually already running and starting a second
# copy would fail on the port.
if ! curl -s --max-time 2 "${INSIGHTS_OLLAMA_HOST:-http://localhost:11434}/api/tags" >/dev/null 2>&1; then
  echo
  echo "WARNING: no model server answered at ${INSIGHTS_OLLAMA_HOST:-http://localhost:11434}"
  echo "         Start one with:  ollama serve"
  echo "         And pull the model with:  ollama pull ${INSIGHTS_OLLAMA_MODEL:-qwen2.5-coder:7b}"
  echo "         The service will still start. Ingestion works; questions will return 503."
  echo
fi

echo "Starting on http://${INSIGHTS_HOST:-127.0.0.1}:${INSIGHTS_PORT:-8000}"
exec "$VENV_PYTHON" -m insights
