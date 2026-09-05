from pathlib import Path

root = Path('.')

def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Replace the temporary Vosk dependency with the tiny stateful TFLite runtime used by microWakeWord.
gradle = root / 'app/build.gradle.kts'
replace_once(
    gradle,
    '    // Local Russian wake-word recognizer. Constrained grammar; no network at runtime.\n'
    '    implementation("com.alphacephei:vosk-android:0.3.75")\n',
    '    // Local microWakeWord streaming CNN. No network at runtime.\n'
    '    implementation("com.google.ai.edge.litert:litert:1.4.1")\n',
)

# Build the vendored TFLite-Micro audio frontend JNI library copied in by CI.
replace_once(
    gradle,
    '    compileSdk = 36  // Required by Leap SDK 0.9.2 (depends on androidx.core:core-ktx:1.17.0)\n',
    '    compileSdk = 36  // Required by Leap SDK 0.9.2 (depends on androidx.core:core-ktx:1.17.0)\n\n'
    '    externalNativeBuild {\n'
    '        cmake {\n'
    '            path = file("src/main/cpp/CMakeLists.txt")\n'
    '            version = "3.22.1"\n'
    '        }\n'
    '    }\n',
)

# This branch intentionally carries the known-good English “Hey Jarvis” model as an A/B control.
# The final Russian Alyosha model will use this exact same runtime, so do not present the control APK
# as though its trigger were already “Алёша”.
settings = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/LlmAuthSettingsPage.kt'
text = settings.read_text(encoding='utf-8')
text = text.replace(
    'Text("Hands-free wake: local Russian model • no cloud audio before “Алёша”", style = MaterialTheme.typography.bodySmall)',
    'Text("Hands-free wake: microWakeWord “Hey Jarvis” control • fully local", style = MaterialTheme.typography.bodySmall)',
)
text = text.replace('"Turn off hands-free “Алёша”"', '"Turn off hands-free wake"')
text = text.replace('"Turn on hands-free “Алёша”"', '"Turn on hands-free wake"')
text = text.replace(
    '"Idle audio stays local. After “Алёша”, live transcript appears in the main input. Each server-VAD pause is checked by the subscription model; it returns NOT_READY or the normalized intent. Final agent answers are read aloud."',
    '"Idle audio stays local. This control build wakes on “Hey Jarvis”. After wake, live transcript appears in the main input. Each server-VAD pause is checked by the subscription model; it returns NOT_READY or the normalized intent. Final agent answers are read aloud."',
)
settings.write_text(text, encoding='utf-8')

print('microWakeWord build patch applied')
