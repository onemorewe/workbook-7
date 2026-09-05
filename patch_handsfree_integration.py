from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Vosk is used only for the local, always-on wake word. No idle audio leaves the phone.
gradle = root / 'app/build.gradle.kts'
replace_once(
    gradle,
    '    // OkHttp — used by CodexResponseClient for raw SSE streaming to chatgpt.com\n'
    '    implementation("com.squareup.okhttp3:okhttp:4.12.0")\n',
    '    // OkHttp — used by CodexResponseClient and hands-free Realtime WebSocket\n'
    '    implementation("com.squareup.okhttp3:okhttp:4.12.0")\n\n'
    '    // Local Russian wake-word recognizer. Constrained grammar; no network at runtime.\n'
    '    implementation("com.alphacephei:vosk-android:0.3.75")\n',
)

# Manifest: microphone foreground service.
manifest = root / 'app/src/main/AndroidManifest.xml'
replace_once(
    manifest,
    '    <uses-permission android:name="android.permission.RECORD_AUDIO" />\n',
    '    <uses-permission android:name="android.permission.RECORD_AUDIO" />\n'
    '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />\n'
    '    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MICROPHONE" />\n',
)
replace_once(
    manifest,
    '        <!-- Shizuku content provider for binder forwarding -->\n',
    '        <service\n'
    '            android:name=".ui.capsule.voice.HandsFreeVoiceService"\n'
    '            android:exported="false"\n'
    '            android:foregroundServiceType="microphone" />\n\n'
    '        <!-- Shizuku content provider for binder forwarding -->\n',
)

# Route a normalized hands-free intent into the current session or start a new task.
# Also fix the upstream service-start path to use the user's selected model; otherwise it silently
# falls back to SessionConfig's default model when hands-free starts a fresh agent session.
service = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
replace_once(service, 'import ai.closepaw.protocol.SessionConfig\n', 'import ai.closepaw.protocol.SessionConfig\nimport ai.closepaw.protocol.SessionState\n')
replace_once(
    service,
    '    fun stopAgent() {\n',
    '''    fun submitHandsFreeCommand(text: String) {
        val command = text.trim()
        if (command.isEmpty()) return
        val current = session
        if (current == null || current.state.value == SessionState.Shutdown) {
            runAgent(command)
            return
        }
        serviceScope.launch {
            when (current.state.value) {
                SessionState.Created, SessionState.Idle -> current.submit(Op.UserInput(command))
                SessionState.Running, SessionState.Paused -> current.submit(Op.Supplement(command))
                SessionState.Shutdown -> runAgent(command)
            }
        }
    }

    fun stopAgent() {
''',
)
replace_once(
    service,
    '''                        SessionConfig(
                                debugMode = true,
                                traceEnabled = settings.traceEnabled,
                                platformMode = platformMode
                        )''',
    '''                        SessionConfig(
                                mainModel = settings.selectedModel,
                                approvalMode = settings.approvalMode,
                                debugMode = true,
                                traceEnabled = settings.traceEnabled,
                                platformMode = platformMode
                        )''',
)
replace_once(
    service,
    '        serviceScope.cancel()\n',
    '        ai.closepaw.ui.capsule.voice.HandsFreeSpeaker.shutdown()\n        serviceScope.cancel()\n',
)

# Speak final answers while hands-free is enabled.
handler = root / 'app/src/main/kotlin/ai/closepaw/app/AgentServiceEventHandler.kt'
replace_once(
    handler,
    '    private val sessionCleared: () -> Unit,\n    private val overlayController: () -> ServiceOverlayController?\n) {',
    '    private val sessionCleared: () -> Unit,\n    private val overlayController: () -> ServiceOverlayController?,\n    private val speakAnswer: (String) -> Unit = {},\n) {',
)
replace_once(
    handler,
    '                overlay?.onTaskCompleted(event.outcome, event.result)\n',
    '                overlay?.onTaskCompleted(event.outcome, event.result)\n                if (realAnswer != null && !event.outcome.isError()) speakAnswer(realAnswer)\n',
)
replace_once(
    service,
    '                    overlayController = { overlayController }\n            )\n',
    '                    overlayController = { overlayController },\n                    speakAnswer = { answer -> ai.closepaw.ui.capsule.voice.HandsFreeSpeaker.speak(this@AgentService, answer) }\n            )\n',
)

# While a hands-free command is active, mirror live STT deltas into the main input field. This is
# intentionally visible in the first build so recognition quality and endpoint timing are debuggable.
bar = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/surface/CapsuleInputBar.kt'
replace_once(
    bar,
    'import androidx.compose.runtime.Composable\n',
    'import androidx.compose.runtime.Composable\nimport androidx.compose.runtime.collectAsState\n',
)
replace_once(
    bar,
    'import ai.closepaw.ui.capsule.voice.RecognizerFactory\n',
    'import ai.closepaw.ui.capsule.voice.RecognizerFactory\nimport ai.closepaw.ui.capsule.voice.HandsFreeVoiceService\n',
)
replace_once(
    bar,
    '    var inputText by remember { mutableStateOf("") }\n',
    '''    var inputText by remember { mutableStateOf("") }
    val handsFreeTranscript by HandsFreeVoiceService.liveTranscript.collectAsState()
    val handsFreeActive by HandsFreeVoiceService.commandSessionActive.collectAsState()
    LaunchedEffect(handsFreeTranscript, handsFreeActive) {
        if (handsFreeActive || handsFreeTranscript.isNotBlank()) {
            inputText = handsFreeTranscript
        }
    }
''',
)

# Make voice routing explicit. Normal mic can still use the existing selected STT model; hands-free
# always uses local Vosk wake + gpt-live-transcribe + the selected OAuth/Codex model as intent gate.
settings = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/LlmAuthSettingsPage.kt'
old = '''    if (selectedProvider == LLMProvider.OPENAI_API) {
        Spacer(modifier = Modifier.height(20.dp))
        val voiceContext = LocalContext.current
        var voiceModel by remember { mutableStateOf(VoiceTranscriptionSettings.load(voiceContext)) }
        SettingsSection(title = "Voice Recognition") {
            CloudModelDropdown(
                selectedModel = voiceModel,
                modelOptions = VoiceTranscriptionSettings.modelOptions,
                onModelChange = { selected ->
                    voiceModel = selected
                    VoiceTranscriptionSettings.save(voiceContext, selected)
                },
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (voiceModel == VoiceTranscriptionSettings.SYSTEM) {
                    "Uses Android's built-in speech recognizer."
                } else {
                    "Language: Auto — Russian, English, and mixed speech. Uses the OpenAI API key above; without an API key ClosePaw falls back to Android speech."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(modifier = Modifier.height(20.dp))
    }
'''
new = '''    if (selectedProvider == LLMProvider.OPENAI_API) {
        Spacer(modifier = Modifier.height(20.dp))
        val voiceContext = LocalContext.current
        var voiceModel by remember { mutableStateOf(VoiceTranscriptionSettings.load(voiceContext)) }
        var handsFree by remember { mutableStateOf(ai.closepaw.ui.capsule.voice.HandsFreeVoiceService.isEnabled(voiceContext)) }
        val agentMode = modelCatalog.resolveOrNull(selectedModel)?.provider?.mode
        val agentAuth = when (agentMode) {
            AuthMode.OAuth -> "ChatGPT sign-in / subscription allowance"
            AuthMode.ApiKey -> "API key billing"
            AuthMode.Local -> "On-device"
            null -> "Unknown"
        }
        SettingsSection(title = "Active voice configuration") {
            Text("Agent model: $selectedModel", style = MaterialTheme.typography.bodyMedium)
            Text("Agent auth: $agentAuth", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(modifier = Modifier.height(8.dp))
            Text("Normal mic STT: $voiceModel", style = MaterialTheme.typography.bodyMedium)
            Text(
                text = if (voiceModel == VoiceTranscriptionSettings.SYSTEM) {
                    "Normal mic: Android system recognizer"
                } else if (apiKeyText.isNotBlank()) {
                    "Normal mic: OpenAI API key connected • language auto RU/EN"
                } else {
                    "Normal mic: OpenAI key missing • falls back to Android"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(modifier = Modifier.height(10.dp))
            CloudModelDropdown(
                selectedModel = voiceModel,
                modelOptions = VoiceTranscriptionSettings.modelOptions,
                onModelChange = { selected ->
                    voiceModel = selected
                    VoiceTranscriptionSettings.save(voiceContext, selected)
                },
            )
            Spacer(modifier = Modifier.height(12.dp))
            Text("Hands-free wake: local Russian model • no cloud audio before “Алёша”", style = MaterialTheme.typography.bodySmall)
            Text("Hands-free STT: gpt-live-transcribe • OpenAI API key", style = MaterialTheme.typography.bodySmall)
            Text("Intent gate: $selectedModel • ChatGPT subscription", style = MaterialTheme.typography.bodySmall)
            Spacer(modifier = Modifier.height(10.dp))
            androidx.compose.material3.Button(
                onClick = {
                    handsFree = !handsFree
                    ai.closepaw.ui.capsule.voice.HandsFreeVoiceService.setEnabled(voiceContext, handsFree)
                },
                enabled = apiKeyText.isNotBlank() && agentMode == AuthMode.OAuth,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (handsFree) "Turn off hands-free “Алёша”" else "Turn on hands-free “Алёша”")
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = when {
                    apiKeyText.isBlank() -> "Hands-free needs an OpenAI API key for live transcription."
                    agentMode != AuthMode.OAuth -> "Hands-free intent gate needs ChatGPT Sign in as the selected agent model."
                    handsFree -> "Idle audio stays local. After “Алёша”, live transcript appears in the main input. Each server-VAD pause is checked by the subscription model; it returns NOT_READY or the normalized intent. Final agent answers are read aloud."
                    else -> "Hands-free is off."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "Privacy/cost: before the local wake word, microphone audio is not uploaded. After wake, command audio is sent to OpenAI live STT only until the intent is accepted; the socket is closed before the action runs.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(modifier = Modifier.height(20.dp))
    }
'''
replace_once(settings, old, new)

# Yandex Music skill for voice playback requests.
yandex = root / 'app/src/main/assets/app_skills/ru.yandex.music/SKILL.md'
yandex.parent.mkdir(parents=True, exist_ok=True)
yandex.write_text('''---
name: app-yandex-music
description: App-specific guidance for Yandex Music hands-free search and playback.
metadata:
  package: ru.yandex.music
---

- For a request to play a song or artist, use Search and start the best exact result.
- Prefer exact track title + artist over playlists, mixes, podcasts, or covers unless requested.
- Preserve Russian/English spelling from the user's request when searching.
- Playback, search, and browsing are safe without confirmation.
- Do not like/dislike, edit library, subscribe, purchase, or change account settings unless explicitly asked.
''', encoding='utf-8')

print('Hands-free live intent integration patch applied')
