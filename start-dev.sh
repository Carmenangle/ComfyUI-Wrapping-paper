#!/usr/bin/env sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PYTHON=${PYTHON:-python3}
VENV="$ROOT/backend/.venv"

command -v "$PYTHON" >/dev/null 2>&1 || { echo "Python 3.10-3.14 is required" >&2; exit 1; }
command -v npm >/dev/null 2>&1 || { echo "Node.js 18+ is required" >&2; exit 1; }

if [ ! -x "$VENV/bin/python" ]; then
  "$PYTHON" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install \
  --no-index --find-links "$ROOT/vendor/pip" \
  -r "$ROOT/backend/requirements.txt"

(
  cd "$ROOT/frontend"
  npm ci --offline --cache "$ROOT/vendor/npm"
)

cleanup() {
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup INT TERM EXIT

(
  cd "$ROOT/backend"
  "$VENV/bin/python" -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload
) &
BACKEND_PID=$!

(
  cd "$ROOT/frontend"
  npm run dev -- --host 127.0.0.1
) &
FRONTEND_PID=$!

case "$(uname -s)" in
  Darwin) open http://127.0.0.1:5173 >/dev/null 2>&1 || true ;;
  Linux) xdg-open http://127.0.0.1:5173 >/dev/null 2>&1 || true ;;
esac

wait "$BACKEND_PID"
wait "$FRONTEND_PID"
