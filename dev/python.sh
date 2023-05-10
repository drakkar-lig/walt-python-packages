#!/bin/bash
set -e
DEV_DIR="$(cd $(dirname "$0"); pwd)"
ROOT_DIR="$(cd $(dirname "$DEV_DIR"); pwd)"
if [ ! -d "$ROOT_DIR/.venv" ]
then
    echo "Installing python3-venv if missing"
    apt-get update || true  # failure about secondary repositories is usually not an issue
    apt-get install -y python3-venv
    echo "Creating a virtual environment at .venv"
    python3 -m venv "$ROOT_DIR/.venv"
    "$ROOT_DIR"/.venv/bin/python -m pip install --upgrade pip
fi
"$ROOT_DIR"/.venv/bin/python "$@"
