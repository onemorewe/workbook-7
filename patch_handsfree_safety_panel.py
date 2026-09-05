from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:160]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# --- HandsFreeVoiceService: never let a missing permission / bad auth / FGS restriction crash UI ---
service = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
text = service.read_text(encoding='utf-8')
text = text.replace(
    'import ai.closepaw.app.AgentService\nimport ai.closepaw.app.AuthStoreHolder\n',
    'import ai.closepaw.app.AgentService\nimport ai.closepaw.app.AppSettingsStore\nimport ai.closepaw.app.AuthStoreHolder\n',
    1,
)
text = text.replace(
    'import ai.closepaw.llm.LLMProvider\n',
    'import ai.closepaw.llm.LLMProvider\nimport ai.closepaw.llm.ModelCatalogRepositoryHolder\n',
    1,
)

old_companion = '''        private val _commandSessionActive = MutableStateFlow(false)
        val commandSessionActive: StateFlow<Boolean> = _commandSessionActive.asStateFlow()

        fun isEnabled(context: Context): Boolean =
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(KEY_ENABLED, false)

        fun setEnabled(context: Context, enabled: Boolean) {
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putBoolean(KEY_ENABLED, enabled).apply()
            if (!enabled) {
                _commandSessionActive.value = false
                _liveTranscript.value = ""
            }
            val intent = Intent(context, HandsFreeVoiceService::class.java).apply {
                action = if (enabled) ACTION_START else ACTION_STOP
            }
            if (enabled) ContextCompat.startForegroundService(context, intent)
            else context.stopService(intent)
        }
'''
new_companion = '''        private val _commandSessionActive = MutableStateFlow(false)
        val commandSessionActive: StateFlow<Boolean> = _commandSessionActive.asStateFlow()

        private val _runtimeStatus = MutableStateFlow("Off")
        val runtimeStatus: StateFlow<String> = _runtimeStatus.asStateFlow()

        private val _lastError = MutableStateFlow<String?>(null)
        val lastError: StateFlow<String?> = _lastError.asStateFlow()

        fun isEnabled(context: Context): Boolean =
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(KEY_ENABLED, false)

        /**
         * Starts/stops hands-free without throwing into the Compose caller.
         * Returns a human-readable error when startup is blocked.
         */
        fun setEnabled(context: Context, enabled: Boolean): String? {
            val app = context.applicationContext
            val prefs = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

            if (!enabled) {
                prefs.edit().putBoolean(KEY_ENABLED, false).apply()
                _commandSessionActive.value = false
                _liveTranscript.value = ""
                _runtimeStatus.value = "Off"
                val intent = Intent(app, HandsFreeVoiceService::class.java).apply { action = ACTION_STOP }
                runCatching { app.stopService(intent) }
                return null
            }

            val blocked = preflightError(app)
            if (blocked != null) {
                prefs.edit().putBoolean(KEY_ENABLED, false).apply()
                _lastError.value = blocked
                _runtimeStatus.value = "Blocked"
                return blocked
            }

            val intent = Intent(app, HandsFreeVoiceService::class.java).apply { action = ACTION_START }
            val startError = runCatching { ContextCompat.startForegroundService(app, intent) }.exceptionOrNull()
            if (startError != null) {
                val message = "Could not start microphone service: ${startError.message ?: startError::class.java.simpleName}"
                prefs.edit().putBoolean(KEY_ENABLED, false).apply()
                _lastError.value = message
                _runtimeStatus.value = "Error"
                return message
            }

            prefs.edit().putBoolean(KEY_ENABLED, true).apply()
            _lastError.value = null
            _runtimeStatus.value = "Starting"
            return null
        }

        private fun preflightError(context: Context): String? {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                return "Microphone permission is required"
            }
            val auth = runCatching { AuthStoreHolder.get(context) }.getOrElse {
                return "Secure credential storage is unavailable: ${it.message ?: it::class.java.simpleName}"
            }
            val apiKeyReady = runCatching {
                auth.requireApiKey(LLMProvider.OPENAI_API).isNotBlank()
            }.getOrDefault(false)
            if (!apiKeyReady) return "OpenAI API key is required for live transcription"

            val selected = runCatching { AppSettingsStore(context).load().selectedModel }.getOrNull()
                ?: return "Could not read the selected reasoning model"
            val entry = runCatching {
                ModelCatalogRepositoryHolder.get(context).catalog.value.resolveOrNull(selected)
            }.getOrNull() ?: return "Selected reasoning model '$selected' is not available in the model catalog"
            if (entry.provider != LLMProvider.OPENAI_CODEX) {
                return "Hands-free intent gate requires a ChatGPT subscription model; '$selected' uses ${entry.provider}"
            }
            if (!runCatching { auth.has(LLMProvider.OPENAI_CODEX) }.getOrDefault(false)) {
                return "ChatGPT sign-in is required for the hands-free intent gate"
            }
            return null
        }
'''
if old_companion not in text:
    raise SystemExit('HandsFreeVoiceService companion anchor not found')
text = text.replace(old_companion, new_companion, 1)

old_start = '''    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP || !isEnabled(this)) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NOTIFICATION_ID, notification("Алёша • запускаю локальное распознавание…"))
        if (listenJob == null) startListening()
        return START_STICKY
    }
'''
new_start = '''    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP || !isEnabled(this)) {
            _runtimeStatus.value = "Off"
            stopSelf()
            return START_NOT_STICKY
        }

        val blocked = preflightError(this)
        if (blocked != null) {
            getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, false).apply()
            _lastError.value = blocked
            _runtimeStatus.value = "Blocked"
            stopSelf()
            return START_NOT_STICKY
        }

        val foregroundError = runCatching {
            startForeground(NOTIFICATION_ID, notification("Hands-free • starting local wake detection…"))
        }.exceptionOrNull()
        if (foregroundError != null) {
            val message = "Foreground microphone service rejected: ${foregroundError.message ?: foregroundError::class.java.simpleName}"
            getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, false).apply()
            _lastError.value = message
            _runtimeStatus.value = "Error"
            stopSelf()
            return START_NOT_STICKY
        }

        _lastError.value = null
        _runtimeStatus.value = "Starting"
        if (listenJob == null) startListening()
        return START_STICKY
    }
'''
if old_start not in text:
    raise SystemExit('HandsFreeVoiceService onStartCommand anchor not found')
text = text.replace(old_start, new_start, 1)

old_recorder = '''    @SuppressLint("MissingPermission")
    private fun createRecorder(): AudioRecord? {
        val min = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val r = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .build()
            )
            .setBufferSizeInBytes(maxOf(min.coerceAtLeast(0), FRAME_SAMPLES * 2 * 8))
            .build()
        return if (r.state == AudioRecord.STATE_INITIALIZED) r else {
            r.release()
            null
        }
    }
'''
new_recorder = '''    @SuppressLint("MissingPermission")
    private fun createRecorder(): AudioRecord? = runCatching {
        val min = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val r = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .build()
            )
            .setBufferSizeInBytes(maxOf(min.coerceAtLeast(0), FRAME_SAMPLES * 2 * 8))
            .build()
        if (r.state == AudioRecord.STATE_INITIALIZED) r else {
            r.release()
            null
        }
    }.getOrElse {
        _lastError.value = "AudioRecord initialization failed: ${it.message ?: it::class.java.simpleName}"
        null
    }
'''
if old_recorder not in text:
    raise SystemExit('HandsFreeVoiceService recorder anchor not found')
text = text.replace(old_recorder, new_recorder, 1)

text = text.replace(
    '''    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }
''',
    '''    private fun updateNotification(text: String) {
        _runtimeStatus.value = text
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }
''',
    1,
)
text = text.replace(
    '''    private fun failAndDisable(message: String) {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, false).apply()
        _commandSessionActive.value = false
        _liveTranscript.value = ""
        updateNotification("Алёша выключена • $message")
        stopSelf()
    }
''',
    '''    private fun failAndDisable(message: String) {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, false).apply()
        _commandSessionActive.value = false
        _liveTranscript.value = ""
        _lastError.value = message
        updateNotification("Hands-free error • $message")
        stopSelf()
    }
''',
    1,
)
service.write_text(text, encoding='utf-8')

# Expose the model actually pinned into an already-running AgentSession.
session = root / 'app/src/main/kotlin/ai/closepaw/session/AgentSession.kt'
replace_once(
    session,
    '    fun getServices(): SessionServices = services\n',
    '    fun getServices(): SessionServices = services\n\n    /** Model pinned into this running session; settings changes do not rewrite it mid-run. */\n    fun effectiveMainModel(): String = config.mainModel\n',
)

# Remove the voice controls that earlier patches injected into the LLM/Auth page.
llm_page = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/LlmAuthSettingsPage.kt'
llm_text = llm_page.read_text(encoding='utf-8')
marker = '        SettingsSection(title = "Active voice configuration") {'
marker_pos = llm_text.find(marker)
if marker_pos < 0:
    raise SystemExit('Active voice configuration block not found')
start = llm_text.rfind('    if (selectedProvider == LLMProvider.OPENAI_API) {', 0, marker_pos)
end_marker = '    // Auto-flip rule: when the user is in the OTHER sub-tab and all three fields\n'
end = llm_text.find(end_marker, marker_pos)
if start < 0 or end < 0:
    raise SystemExit('Could not bound injected voice block')
llm_page.write_text(llm_text[:start] + llm_text[end:], encoding='utf-8')

# Add a dedicated settings page and navigation row.
sheet = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/SettingsSheet.kt'
replace_once(
    sheet,
    '    LLM_AUTH,\n    AGENT_BEHAVIOR,\n',
    '    LLM_AUTH,\n    VOICE_RUNTIME,\n    AGENT_BEHAVIOR,\n',
)
replace_once(
    sheet,
    '''                    SettingsPage.AGENT_BEHAVIOR -> AgentBehaviorSettingsPage(
''',
    '''                    SettingsPage.VOICE_RUNTIME -> VoiceRuntimeSettingsPage(
                        selectedModel = selectedModel,
                        modelCatalog = modelCatalog,
                        onBack = { settingsPage = SettingsPage.HOME },
                        onClose = onDismiss,
                    )
                    SettingsPage.AGENT_BEHAVIOR -> AgentBehaviorSettingsPage(
''',
)

home = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/SettingsHomePage.kt'
replace_once(
    home,
    '''            SettingsNavigationRow(
                title = "Agent Behavior",
''',
    '''            SettingsNavigationRow(
                title = "Voice & Runtime",
                subtitle = "Effective models, auth, wake word, STT and TTS",
                onClick = { onNavigate(SettingsPage.VOICE_RUNTIME) }
            )
            SettingsNavigationRow(
                title = "Agent Behavior",
''',
)

print('Hands-free safety + dedicated runtime panel patch applied')
