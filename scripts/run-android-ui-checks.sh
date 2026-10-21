#!/usr/bin/env bash
# One shell is required: android-emulator-runner splits its script input by line.
# Run from the generated closepaw directory. Preserve the instrumentation result.
set +e
./gradlew :app:connectedDebugAndroidTest --stacktrace -Pandroid.testInstrumentationRunnerArguments.class=ai.closepaw.ui.capsule.voice.HandsFreeSafetyInstrumentedTest,ai.closepaw.ui.capsule.voice.VoiceRuntimeUiInstrumentedTest
test_status=$?

diagnostics_dir=app/build/reports/ui-diagnostics
if mkdir -p "$diagnostics_dir"; then
  printf 'instrumentation_exit_status=%s\n' "$test_status" > "$diagnostics_dir/status.txt"
  # Only files written by the hermetic UI test, not app data or credential stores.
  adb exec-out run-as ai.closepaw tar -C files/ui-diagnostics -cf - . \
    > "$diagnostics_dir/device-captures.tar" 2> "$diagnostics_dir/capture-error.txt"
  capture_status=$?
  if [ "$capture_status" -ne 0 ]; then
    rm -f "$diagnostics_dir/device-captures.tar"
    printf 'UI diagnostic capture unavailable (adb exit %s)\n' "$capture_status"
  fi
else
  printf 'Could not create UI diagnostic output directory\n'
fi
exit "$test_status"
