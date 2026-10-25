#!/usr/bin/env bash
# Linux/macOS equivalent of check.ps1 (used in the development workspace).
set -u
root="$(cd "$(dirname "$0")/.." && pwd)"
fail=0
cd "$root/backend"
echo "== Backend: compile"; .venv/bin/python -m compileall -q claw tests || fail=1
echo "== Backend: tests";   .venv/bin/python -m pytest -q || fail=1
cd "$root/desktop"
echo "== Desktop: syntax";  npm run -s check || fail=1
echo "== Desktop: unit";    npm test || fail=1
echo "== Desktop: e2e"
if [ -z "${DISPLAY:-}" ] && command -v xvfb-run >/dev/null; then
  CLAW_E2E_NO_SANDBOX=${CLAW_E2E_NO_SANDBOX:-$([ "$(id -u)" = 0 ] && echo 1)} xvfb-run -a -s "-screen 0 1400x900x24" node tests/e2e.mjs || fail=1
else
  node tests/e2e.mjs || fail=1
fi
[ $fail = 0 ] && echo "All checks passed" || { echo "SOME CHECKS FAILED"; exit 1; }
