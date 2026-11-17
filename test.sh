#!/bin/bash
# Docker-backed integration tests. Usage: bash test.sh [test_name ...]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# shellcheck disable=SC1091 # Resolved from this script's directory at runtime.
source "$SCRIPT_DIR/tests/common.sh"
for f in "$SCRIPT_DIR"/tests/test_*.sh; do
    # shellcheck disable=SC1090 # Every repository-owned test module.
    source "$f"
done

if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    echo "Usage: $0 [test_name ...]"
    printf '  %s\n' "${ALL_TESTS[@]}"
    exit 0
fi

TESTS_TO_RUN=("$@")
if [ ${#TESTS_TO_RUN[@]} -eq 0 ]; then
    TESTS_TO_RUN=("${ALL_TESTS[@]}")
fi
for t in "${TESTS_TO_RUN[@]}"; do
    if ! declare -f "$t" >/dev/null 2>&1; then
        echo "Unknown test: $t"
        exit 1
    fi
done

trap cleanup EXIT
setup

PASSED=0
FAILED_TESTS=()
for t in "${TESTS_TO_RUN[@]}"; do
    log="$RESULTS_DIR/${t}.log"
    echo -n "[$(date '+%H:%M:%S')] $t ... "
    if "$t" >"$log" 2>&1; then
        PASSED=$((PASSED + 1))
        echo "OK"
    else
        FAILED_TESTS+=("$t")
        echo "FAIL (see tests/results/${t}.log)"
        sed 's/^/    /' "$log" | tail -15
    fi
    test_teardown
done

echo ""
echo "=== ${PASSED} passed, ${#FAILED_TESTS[@]} failed ==="
if [ ${#FAILED_TESTS[@]} -gt 0 ]; then
    printf '  %s\n' "${FAILED_TESTS[@]}"
    exit 1
fi
