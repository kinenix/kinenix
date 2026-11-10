#!/usr/bin/env bash
# ==============================================================================
# Kinenix - install a released version as a brand-new Linux user and check it
#
#   sudo .github/scripts/fresh_user_test.sh 1.0.0                      from PyPI
#   sudo .github/scripts/fresh_user_test.sh 1.0.0rc5 --index testpypi  from TestPyPI
#
# Creates a temporary user (kxt + date and time), installs kinenix, kinenix-hub, and
# kinenix-worker in a new virtual environment as that user, checks them, writes a
# Markdown report, and deletes the user. No setting or flow of another user is read
# or changed. Exit code 0 when every check passed, 1 when one failed, 2 on wrong use.
#
# Options:
#   --index pypi|testpypi   where to install from (default pypi)
#   --report FILE           where to write the report (default /var/tmp/kinenix-fresh-<version>-<time>.md)
#   --keep                  keep the user and its files for a look afterwards
#
# An AI assistant may run this script through a sudoers rule for this path only
# (docs/releasing.md, section 2.1); it must never get general sudo rights.
# ==============================================================================
set -uo pipefail

usage() { sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2; }

VERSION="${1:-}"
[ -n "$VERSION" ] && [ "${VERSION#-}" = "$VERSION" ] || usage
shift
INDEX="pypi"
REPORT=""
KEEP=0
while [ $# -gt 0 ]; do
    case "$1" in
        --index) INDEX="${2:-}"; shift 2 ;;
        --report) REPORT="${2:-}"; shift 2 ;;
        --keep) KEEP=1; shift ;;
        *) usage ;;
    esac
done

if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+((a|b|rc)[0-9]+)?$ ]]; then
    echo "ERROR: '$VERSION' is not a version such as 1.0.0 or 1.0.0rc5." >&2; exit 2
fi
if [ "$INDEX" != "pypi" ] && [ "$INDEX" != "testpypi" ]; then
    echo "ERROR: --index must be pypi or testpypi." >&2; exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run with sudo; creating and deleting a user needs root." >&2; exit 2
fi
for tool in useradd userdel runuser python3 curl timeout ss; do
    command -v "$tool" >/dev/null 2>&1 || { echo "ERROR: $tool is not installed." >&2; exit 2; }
done

STAMP="$(date +%m%d%H%M%S)"
TEST_USER="kxt${STAMP}"
REPORT="${REPORT:-/var/tmp/kinenix-fresh-${VERSION}-${STAMP}.md}"
CREATED=0

cleanup() {
    if [ "$CREATED" -eq 1 ] && [ "$KEEP" -eq 0 ]; then
        pkill -9 -u "$TEST_USER" 2>/dev/null || true
        sleep 1
        userdel -r "$TEST_USER" 2>/dev/null || true
    fi
}
trap cleanup EXIT

useradd --create-home --shell /bin/bash "$TEST_USER" || { echo "ERROR: could not create $TEST_USER." >&2; exit 1; }
CREATED=1
HOME_DIR="$(getent passwd "$TEST_USER" | cut -d: -f6)"
chmod 750 "$HOME_DIR"

# Runs a command as the test user, in a clean environment and without a terminal, so nothing asks a question
as_user() {
    runuser -u "$TEST_USER" -- env -i HOME="$HOME_DIR" USER="$TEST_USER" LANG=C.UTF-8 \
        PATH="$HOME_DIR/kx/bin:/usr/local/bin:/usr/bin:/bin" KINENIX_FLOWS_DIR="$HOME_DIR/kinenix-flows" \
        bash -c "cd \"$HOME_DIR\" && $1" </dev/null
}

PASSED=0
FAILED=0
ROWS=""
DETAILS=""

# check NAME EXPECTED_EXIT COMMAND: runs COMMAND as the test user and records the result
check() {
    local name="$1" expected="$2" command="$3" output code
    output="$(as_user "$command" 2>&1)"; code=$?
    if [ "$code" -eq "$expected" ]; then
        PASSED=$((PASSED + 1)); ROWS+="| $name | $expected | $code | pass |"$'\n'
    else
        FAILED=$((FAILED + 1)); ROWS+="| $name | $expected | $code | **FAIL** |"$'\n'
        DETAILS+=$'\n'"### $name"$'\n\n```text\n'"$(printf '%s\n' "$output" | tail -n 25)"$'\n```\n'
    fi
    echo "[$( [ "$code" -eq "$expected" ] && echo pass || echo FAIL )] $name (exit $code, expected $expected)"
}

free_port() {
    local port
    for port in $(seq 8095 8199); do
        ss -ltn "sport = :$port" | grep -q LISTEN || { echo "$port"; return; }
    done
    echo 0
}

echo "Testing kinenix $VERSION from $INDEX as $TEST_USER"

check "Create a virtual environment" 0 "python3 -m venv ~/kx"
if [ "$INDEX" = "testpypi" ]; then
    # Only the three Kinenix packages come from TestPyPI; their dependencies come from PyPI (docs/releasing.md)
    check "Install from TestPyPI" 0 "for i in 1 2 3; do pip download -q --no-deps -d ~/tp --index-url https://test.pypi.org/simple/ kinenix==$VERSION kinenix-hub==$VERSION kinenix-worker==$VERSION && pip install -q --find-links ~/tp 'kinenix[hub,worker]==$VERSION' && exit 0; sleep 30; done; exit 1"
else
    # PyPI's index can lag for a minute after an upload, so the install is tried three times
    check "Install from PyPI" 0 "for i in 1 2 3; do pip install -q --no-cache-dir 'kinenix[hub,worker]==$VERSION' && exit 0; sleep 30; done; exit 1"
fi
check "kinenix --version is $VERSION" 0 "kinenix --version | grep -qx 'kinenix $VERSION'"
check "kinenix-worker --version is $VERSION" 0 "kinenix-worker --version | grep -qx 'kinenix-worker $VERSION'"
check "Install Chromium" 0 "playwright install chromium"

check "Copy the hello example" 0 "kinenix init demo --example hello"
check "Validate hello" 0 "kinenix validate demo"
check "Run hello" 0 "kinenix run demo"
check "Copy the quote_requests example" 0 "kinenix init quotes --example quote_requests"
check "Run quote_requests: 2 of 5 requests fail by design" 8 "kinenix run quotes"
check "Stop a run with SIGTERM" 130 "timeout --preserve-status -s TERM 8 kinenix run quotes"
check "The stopped run's log ends with _interrupted.json" 0 "find ~/kinenix-flows/logs -name '*_interrupted.json' | grep -q ."
check "A new project validates" 0 "kinenix init 'Fresh check' && kinenix validate fresh_check"

PORT="$(free_port)"
if [ "$PORT" -eq 0 ]; then
    FAILED=$((FAILED + 1)); ROWS+="| Start the Hub | 0 | - | **FAIL**: no free port from 8095 to 8199 |"$'\n'
else
    check "Start the Hub on port $PORT" 0 "(KINENIX_HUB_PORT=$PORT kinenix hub > ~/hub.log 2>&1 &) ; for i in \$(seq 1 30); do code=\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:$PORT/); [ \"\$code\" = 200 ] && exit 0; sleep 1; done; cat ~/hub.log; exit 1"
    check "The Hub applied every migration" 0 "grep -q 'Database migration 1 applied' ~/hub.log"
    pkill -u "$TEST_USER" -f "kinenix hub" 2>/dev/null || true
fi

MACHINE="$(uname -srm), $(python3 --version 2>&1)"
{
    echo "# Kinenix $VERSION on a new user"
    echo
    echo "- Installed from: $INDEX"
    echo "- Machine: $(hostname), $MACHINE"
    echo "- User: $TEST_USER, $( [ "$KEEP" -eq 1 ] && echo kept || echo deleted afterwards)"
    echo "- When: $(date '+%Y-%m-%d %H:%M %z')"
    echo "- Result: $PASSED passed, $FAILED failed"
    echo
    echo "| Check | Expected exit | Exit | Result |"
    echo "| :--- | :--- | :--- | :--- |"
    printf '%s' "$ROWS"
    if [ -n "$DETAILS" ]; then
        echo
        echo "## Output of the failed checks"
        printf '%s\n' "$DETAILS"
    fi
} > "$REPORT"
if [ -n "${SUDO_USER:-}" ]; then chown "$SUDO_USER" "$REPORT" 2>/dev/null || true; fi

echo
echo "$PASSED passed, $FAILED failed. Report: $REPORT"
[ "$FAILED" -eq 0 ]
