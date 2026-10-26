#!/usr/bin/env bash
# Checks this project with real tools before you deploy it:
#   bash scripts/check.sh
# cfn-lint is optional locally (pip install cfn-lint).
set -uo pipefail
export MSYS_NO_PATHCONV=1
cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPORT="${CHECK_REPORT:-}"
STRICT="${CHECK_STRICT:-0}"
failed=0
results=()

run() {
  local name="$1"; shift
  printf '\n\033[1;36m==> %s\033[0m\n' "$name"
  local log; log="$(mktemp)"
  if "$@" >"$log" 2>&1; then
    echo "ok"; results+=("{\"name\":\"$name\",\"ok\":true}")
  else
    tail -n 40 "$log"; echo "FAILED: $name"; failed=1
    local detail; detail="$(tail -n 12 "$log" | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g' | cut -c1-900)"
    results+=("{\"name\":\"$name\",\"ok\":false,\"detail\":\"$detail\"}")
  fi
  rm -f "$log"
}
skip() {
  printf '\n\033[1;33m==> %s: skipped (%s)\033[0m\n' "$1" "$2"
  if [ "$STRICT" = "1" ]; then failed=1; results+=("{\"name\":\"$1\",\"ok\":false,\"detail\":\"$2\"}"); fi
}

# Static analysis of the infrastructure. W3002 only notes that the local code paths need
# \`aws cloudformation package\`, which scripts/deploy.sh runs.
if command -v cfn-lint >/dev/null 2>&1; then
  run "CloudFormation template (cfn-lint)" cfn-lint --ignore-checks W3002 -- infrastructure/template.yaml
else
  skip "CloudFormation template (cfn-lint)" "cfn-lint is not installed"
fi
run "Shell scripts (bash -n)" bash -c 'for f in scripts/*.sh; do bash -n "$f" || exit 1; done'
PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  skip "Python checks" "Python 3.12+ is not installed"
else
  run "Create a virtual environment (.venv)" "$PY" -m venv .venv
  VPY=".venv/bin/python"; [ -x "$VPY" ] || VPY=".venv/Scripts/python.exe"
  export VPY
  run "Install dependencies (pip)" "$VPY" -m pip install --quiet --disable-pip-version-check -r requirements-dev.txt
  run "Lint (ruff)" "$VPY" -m ruff check functions scripts
  run "Type-check (mypy --strict)" bash -c 'for d in functions/*/; do [ -f "$d/index.py" ] || continue; "$VPY" -m mypy "$d" || exit 1; done'
  run "Unit tests (pytest)" "$VPY" -m pytest
  run "Security scan (bandit)" "$VPY" -m bandit -q -c pyproject.toml -r functions -x "*/test_index.py,*/conftest.py"
  run "Build the Lambda code" "$VPY" scripts/build.py
  run "Known vulnerabilities in dependencies (pip-audit)" "$VPY" -m pip_audit -r requirements-dev.txt
fi
if [ -n "$REPORT" ]; then
  (IFS=,; printf '{"ok":%s,"checks":[%s]}\n' "$([ "$failed" = 0 ] && echo true || echo false)" "${results[*]}") > "$REPORT"
fi
if [ "$failed" = 0 ]; then printf '\n\033[1;32mAll checks passed.\033[0m\n'; else printf '\n\033[1;31mSome checks failed.\033[0m\n'; exit 1; fi
