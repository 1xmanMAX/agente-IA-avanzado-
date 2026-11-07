#!/usr/bin/env bash
# macOS / Linux
cd "$(dirname "$0")"
[ -d .venv ] || { python3 -m venv .venv && . .venv/bin/activate && pip install -e .; }
. .venv/bin/activate
python -m pixagent serve
