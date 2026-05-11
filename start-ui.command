#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

if ! .venv/bin/python -c "import openai, dotenv, yaml, pandas, tabulate" >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi

.venv/bin/python -m src.web.server --host 127.0.0.1 --port 8765
