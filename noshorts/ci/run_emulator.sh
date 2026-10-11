#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
python3 ci/fixture_server.py > ci-results/fixture.log 2>&1 &
fixture_pid=$!
collect_evidence() {
    local result=$?
    set +e
    timeout 15s adb logcat -d > ci-results/logcat.txt 2>/dev/null
    timeout 15s adb pull /sdcard/Android/data/dev.noshorts.chrome/files/ci-evidence ci-results/device-evidence >/dev/null 2>&1
    timeout 15s adb shell uiautomator dump /sdcard/final-ui.xml >/dev/null 2>&1
    timeout 15s adb pull /sdcard/final-ui.xml ci-results/final-ui.xml >/dev/null 2>&1
    timeout 15s adb shell screencap -p /sdcard/final-screen.png >/dev/null 2>&1
    timeout 15s adb pull /sdcard/final-screen.png ci-results/final-screen.png >/dev/null 2>&1
    kill "$fixture_pid" 2>/dev/null || true
    return "$result"
}
trap collect_evidence EXIT
python3 ci/update_chrome.py
python3 ci/emulator_checks.py
gradle --no-daemon :app:connectedReleaseAndroidTest --stacktrace
