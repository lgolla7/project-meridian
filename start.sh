#!/usr/bin/env bash
# Build the knowledge database from dataset/ and serve the app at http://127.0.0.1:8000
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m app.extract
exec .venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8000
