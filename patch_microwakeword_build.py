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

# The first microWakeWord APK is an English control model only. The runtime is exactly the one that
# will host the trained Alyosha model; keeping this label truthful prevents accidental test confusion.
settings = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/LlmAuthSettingsPage.kt'
text = settings.read_text(encoding='utf-8')
text = text.replace(
    'Text("Hands-free wake: local Russian model • no cloud audio before “Алёша”", style = MaterialTheme.typography.bodySmall)',
    'Text("Hands-free wake: local microWakeWord • no cloud audio before wake", style = MaterialTheme.typography.bodySmall)',
)
settings.write_text(text, encoding='utf-8')

print('microWakeWord build patch applied')
