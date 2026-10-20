#!/usr/bin/env sh
cd "$(dirname "$0")"
PY=$(command -v python3 || command -v python)
"$PY" -m pip install -q -r requirements.txt 2>/dev/null || "$PY" -m pip install -q --user -r requirements.txt
command -v node >/dev/null 2>&1 || { echo "Node.js is required to build the React app." >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "npm is required to build the React app." >&2; exit 1; }
if [ ! -d frontend/node_modules ]; then
  npm --prefix frontend install
fi
npm --prefix frontend run build
exec "$PY" pinnwire_dashboard.py "$@"
