"""Check smoke selectors against CI's patched Kotlin output, without Android.

Run after the complete patch chain, with the same generated source directory as
the Android build: python3 tests/test_voice_runtime_ui_contract.py closepaw

This is a source integration check, not rendered UI or instrumentation evidence.
It catches selectors left behind when a later patch changes the copied screen.
"""

import argparse
from pathlib import Path
import re
import unittest


class GeneratedVoiceRuntimeContractTest(unittest.TestCase):
    source_root: Path

    def test_panel_smoke_selectors_match_generated_render_calls(self):
        panel = (self.source_root / "app/src/main/kotlin/ai/closepaw/ui/settings/VoiceRuntimeSettingsPage.kt").read_text(encoding="utf-8")
        smoke = (self.source_root / "app/src/androidTest/kotlin/ai/closepaw/ui/capsule/voice/VoiceRuntimeUiInstrumentedTest.kt").read_text(encoding="utf-8")

        # Inspect the artifact actually consumed by Gradle, not custom/ (which is
        # only the input to the patch chain). Reject accidentally checking it
        # before the shared transcription / explicit Agent selector patch ran.
        self.assertIn("onAgentModelChange = onModelChange", (self.source_root / "app/src/main/kotlin/ai/closepaw/ui/settings/SettingsSheet.kt").read_text(encoding="utf-8"))

        # Restrict selectors to this screen, after navigation and before the
        # state-changing click. Drawer entries and resulting errors belong to
        # different states and must not be treated as initial panel contents.
        self.assertIn("voiceRuntime.click()", smoke)
        panel_checks = smoke.split("voiceRuntime.click()", 1)[1]
        self.assertIn("enable.click()", panel_checks)
        panel_checks = panel_checks.split("enable.click()", 1)[0]
        selectors = re.findall(r'By\.text\("([^"\n]+)"\)', panel_checks)
        self.assertTrue(selectors, "Smoke no longer checks any panel text")

        # These are actual Compose render calls in the final source. Do not
        # count unrelated strings, comments or error messages as rendered text.
        rendered = set(re.findall(
            r'(?:SettingsSection|PageMastheadDrillDown)\(title = "([^"\n]+)"',
            panel,
        ))
        rendered.update(re.findall(r'\bText\("([^"\n]+)"', panel))
        for conditional_text in re.findall(r'\bText\(if [^\n]+\)', panel):
            rendered.update(re.findall(r'"([^"\n]+)"', conditional_text))

        missing = sorted(set(selectors) - rendered)
        self.assertEqual(
            [], missing,
            "Smoke selectors have no matching generated Compose render call: "
            f"{missing}. Available literal text: {sorted(rendered)}",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("generated_source", type=Path)
    args = parser.parse_args()
    GeneratedVoiceRuntimeContractTest.source_root = args.generated_source.resolve()
    unittest.main(argv=[__file__], verbosity=2)
