#!/usr/bin/env bash
# One shell is required: android-emulator-runner splits its script input by line.
# Run from the generated closepaw directory. Preserve the instrumentation result.
set +e
# Keep private diagnostic files until collection; the CI action then shuts down the emulator.
./gradlew :app:connectedDebugAndroidTest --stacktrace -Pandroid.testInstrumentationRunnerArguments.class=ai.closepaw.ui.capsule.voice.HandsFreeSafetyInstrumentedTest,ai.closepaw.ui.capsule.voice.VoiceRuntimeUiInstrumentedTest -Pandroid.injected.androidTest.leaveApksInstalledAfterRun=true
test_status=$?

diagnostics_dir=app/build/reports/ui-diagnostics
if mkdir -p "$diagnostics_dir"; then
  printf 'instrumentation_exit_status=%s\n' "$test_status" > "$diagnostics_dir/status.txt"
  # Only files written by the hermetic UI test, not app data or credential stores.
  adb exec-out run-as ai.closepaw tar -C files/ui-diagnostics -cf - . \
    > "$diagnostics_dir/device-captures.tar" 2> "$diagnostics_dir/capture-error.txt"
  capture_status=$?
  # exec-out may return 0 with a run-as error in stdout (observed in CI146).
  if [ "$capture_status" -eq 0 ] && ! tar -tf "$diagnostics_dir/device-captures.tar" >/dev/null 2>> "$diagnostics_dir/capture-error.txt"; then
    printf '\nInvalid capture payload (first 1024 bytes):\n' >> "$diagnostics_dir/capture-error.txt"
    head -c 1024 "$diagnostics_dir/device-captures.tar" >> "$diagnostics_dir/capture-error.txt"
    capture_status=1
  fi
  if [ "$capture_status" -ne 0 ]; then
    rm -f "$diagnostics_dir/device-captures.tar"
    printf 'UI diagnostic capture unavailable (capture status %s)\n' "$capture_status"
  fi
else
  printf 'Could not create UI diagnostic output directory\n'
fi
exit "$test_status"
