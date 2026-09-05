from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

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

# Route wake-word commands into current session or start a new task.
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

# Make Voice Recognition status explicit and add a hands-free toggle.
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
            AuthMode.OAuth -> "ChatGPT sign-in / Plus-Codex allowance"
            AuthMode.ApiKey -> "API key billing"
            AuthMode.Local -> "On-device"
            null -> "Unknown"
        }
        SettingsSection(title = "Active voice configuration") {
            Text("Agent model: $selectedModel", style = MaterialTheme.typography.bodyMedium)
            Text("Agent auth: $agentAuth", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Spacer(modifier = Modifier.height(8.dp))
            Text("Speech model: $voiceModel", style = MaterialTheme.typography.bodyMedium)
            Text(
                text = if (voiceModel == VoiceTranscriptionSettings.SYSTEM) {
                    "Speech: Android system recognizer"
                } else if (apiKeyText.isNotBlank()) {
                    "Speech: OpenAI API key connected • language auto RU/EN"
                } else {
                    "Speech: OpenAI key missing • mic falls back to Android"
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
                    if (selected == VoiceTranscriptionSettings.SYSTEM && handsFree) {
                        handsFree = false
                        ai.closepaw.ui.capsule.voice.HandsFreeVoiceService.setEnabled(voiceContext, false)
                    }
                },
            )
            Spacer(modifier = Modifier.height(10.dp))
            androidx.compose.material3.Button(
                onClick = {
                    handsFree = !handsFree
                    ai.closepaw.ui.capsule.voice.HandsFreeVoiceService.setEnabled(voiceContext, handsFree)
                },
                enabled = apiKeyText.isNotBlank() && voiceModel != VoiceTranscriptionSettings.SYSTEM,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (handsFree) "Turn off hands-free “Алёша”" else "Turn on hands-free “Алёша”")
            }
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (handsFree) {
                    "Listening in background. Say “Алёша, поставь ...” or say “Алёша”, wait for the beep, then the command. Final agent answers are read aloud."
                } else {
                    "Normal mic: one tap → speak → ~1.1 s silence → automatic transcription and send. Hands-free is off."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Text(
                "Privacy/cost: while hands-free is on, local VAD sends speech-sized audio segments to your selected OpenAI transcription model so it can detect “Алёша”.",
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

print('Hands-free integration patch applied')
