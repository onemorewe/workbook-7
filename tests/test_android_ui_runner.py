"""Exercise the actual workflow script with isolated Gradle/ADB boundary doubles.

The pinned emulator action executes every non-comment script line in a separate
sh process and stops on failure. A multiline status/diagnostics block therefore
must be called through one shell script. No Android device or network is used.
"""

from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


def workflow_script():
    workflow = (ROOT / '.github/workflows/build-closepaw-voice.yml').read_text()
    block = workflow.split('      - name: Run hands-free Android UI + parser sandbox', 1)[1]
    block = block.split('\n      - name:', 1)[0]
    lines = block.splitlines()
    index = next(i for i, line in enumerate(lines) if line.startswith('          script:'))
    value = lines[index].split('script:', 1)[1].strip()
    return textwrap.dedent('\n'.join(lines[index + 1:])) if value == '|' else value


class AndroidUiRunnerTest(unittest.TestCase):
    def run_workflow(self, gradle_status, adb_status=0):
        with tempfile.TemporaryDirectory(prefix='closepaw-runner-test-') as tmp:
            root = Path(tmp)
            app = root / 'closepaw'
            app.mkdir()
            tools = root / 'bin'
            tools.mkdir()
            calls = root / 'calls.jsonl'
            gradle = app / 'gradlew'
            gradle.write_text('#!/bin/sh\nexit "$FAKE_GRADLE_STATUS"\n')
            gradle.chmod(0o755)
            adb = tools / 'adb'
            adb.write_text('''#!/usr/bin/env python3
import json, os, sys
with open(os.environ['FAKE_ADB_CALLS'], 'a') as out:
    out.write(json.dumps(sys.argv[1:]) + '\\n')
if int(os.environ['FAKE_ADB_STATUS']):
    print('synthetic diagnostic transport failure', file=sys.stderr)
    sys.exit(int(os.environ['FAKE_ADB_STATUS']))
if sys.argv[1:] == ['exec-out', 'run-as', 'ai.closepaw', 'tar', '-C', 'files/ui-diagnostics', '-cf', '-', '.']:
    sys.stdout.buffer.write(b'synthetic scoped capture archive')
''')
            adb.chmod(0o755)
            wrapper = ROOT / 'scripts/run-android-ui-checks.sh'
            if wrapper.exists():
                (root / 'scripts').mkdir()
                shutil.copy2(wrapper, root / 'scripts' / wrapper.name)
            env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ['PATH'],
                       FAKE_GRADLE_STATUS=str(gradle_status), FAKE_ADB_STATUS=str(adb_status),
                       FAKE_ADB_CALLS=str(calls))
            status = 0
            # Same process boundary as the pinned action's parseScript + exec loop.
            for line in workflow_script().strip().splitlines():
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                result = subprocess.run(['sh', '-c', line], cwd=app, env=env,
                                        capture_output=True, text=True)
                status = result.returncode
                if status:
                    break
            captured = app / 'app/build/reports/ui-diagnostics/device-captures.tar'
            return status, captured.read_bytes() if captured.exists() else None, (
                [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []
            )

    def test_failing_gradle_still_collects_scoped_diagnostics_and_keeps_status(self):
        status, archive, calls = self.run_workflow(17)
        self.assertEqual(17, status)
        self.assertEqual(b'synthetic scoped capture archive', archive)
        self.assertIn(['exec-out', 'run-as', 'ai.closepaw', 'tar', '-C',
                       'files/ui-diagnostics', '-cf', '-', '.'], calls)

    def test_diagnostic_failure_does_not_mask_original_test_failure(self):
        status, archive, calls = self.run_workflow(17, 9)
        self.assertEqual(17, status)
        self.assertTrue(calls, 'Diagnostics were never attempted')
        self.assertIsNone(archive, 'Failed capture must not look like a valid archive')

    def test_successful_gradle_keeps_success_even_if_capture_is_unavailable(self):
        status, archive, calls = self.run_workflow(0, 9)
        self.assertEqual(0, status)
        self.assertTrue(calls, 'Diagnostics were never attempted')
        self.assertIsNone(archive)


if __name__ == '__main__':
    unittest.main(verbosity=2)
