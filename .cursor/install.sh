#!/usr/bin/env bash
set -euo pipefail

# Idempotent bootstrap for the slogger development environment.
#
# Creates a project-local virtualenv and installs slogger (editable) together
# with the build tooling and the dependencies required by the examples
# (fastapi + uvicorn for examples/echo_server.py).

cd "$(dirname "$0")/.."

# The default base image ships python3 + pip but not the venv module, which is
# required to create an isolated environment. Install it once if missing.
if ! python3 -c "import ensurepip" >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3-venv
fi

VENV_DIR=".venv"

if [ ! -d "${VENV_DIR}" ]; then
  python3 -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

python -m pip install --upgrade pip setuptools wheel build

# Install slogger in editable mode plus example runtime dependencies.
python -m pip install -e .
python -m pip install fastapi "uvicorn[standard]"

echo "slogger development environment ready."
