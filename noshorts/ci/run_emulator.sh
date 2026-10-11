#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
python3 ci/fixture_server.py > ci-results/fixture.log 2>&1 &
fixture_pid=$!
trap 'kill "$fixture_pid" 2>/dev/null || true' EXIT
python3 ci/emulator_checks.py
gradle --no-daemon :app:connectedDebugAndroidTest --stacktrace
