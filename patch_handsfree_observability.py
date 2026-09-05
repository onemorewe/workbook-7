from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# ---------------------------------------------------------------------------
# AgentService: hands-free sessions are intentionally frictionless while this
# prototype is being debugged: AUTO_APPROVE + trace always on. If the currently
# running session was created with stricter policy, start a fresh hands-free
# session instead of getting stuck on an approval prompt the driver cannot see.
# ---------------------------------------------------------------------------
agent = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
text = agent.read_text(encoding='utf-8')
if 'import ai.closepaw.protocol.ApprovalMode\n' not in text:
    text = text.replace(
        'import ai.closepaw.protocol.Op\n',
        'import ai.closepaw.protocol.Op\nimport ai.closepaw.protocol.ApprovalMode\n',
        1,
    )
agent.write_text(text, encoding='utf-8')

replace_once(
    agent,
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
''',
    '''    fun submitHandsFreeCommand(text: String) {
        val command = text.trim()
        if (command.isEmpty()) return
        val current = session
        val reusableHandsFreeSession = current != null &&
            current.state.value != SessionState.Shutdown &&
            current.getServices().config.approvalMode == ApprovalMode.AUTO_APPROVE &&
            current.getServices().config.traceEnabled

        if (!reusableHandsFreeSession) {
            ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
                "agent",
                "starting fresh hands-free session: auto-approve=true trace=true",
            )
            runAgent(command, handsFree = true)
            return
        }

        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish("agent", "submitting intent to existing hands-free session")
        serviceScope.launch {
            when (current!!.state.value) {
                SessionState.Created, SessionState.Idle -> current.submit(Op.UserInput(command))
                SessionState.Running, SessionState.Paused -> current.submit(Op.Supplement(command))
                SessionState.Shutdown -> runAgent(command, handsFree = true)
            }
        }
    }
''',
)

replace_once(
    agent,
    '''    fun runAgent(
            goal: String,
            authStore: ai.closepaw.auth.AuthStore? = null,
            platformMode: PlatformMode = PlatformMode.ACCESSIBILITY
    ) {
''',
    '''    fun runAgent(
            goal: String,
            authStore: ai.closepaw.auth.AuthStore? = null,
            platformMode: PlatformMode = PlatformMode.ACCESSIBILITY,
            handsFree: Boolean = false,
    ) {
''',
)

replace_once(
    agent,
    '''                        SessionConfig(
                                mainModel = settings.selectedModel,
                                approvalMode = settings.approvalMode,
                                debugMode = true,
                                traceEnabled = settings.traceEnabled,
                                platformMode = platformMode
                        )''',
    '''                        SessionConfig(
                                mainModel = settings.selectedModel,
                                approvalMode = if (handsFree) ApprovalMode.AUTO_APPROVE else settings.approvalMode,
                                debugMode = true,
                                traceEnabled = if (handsFree) true else settings.traceEnabled,
                                platformMode = platformMode
                        )''',
)

# ---------------------------------------------------------------------------
# HandsFreeVoiceService: publish stage transitions, publish the committed
# transcript, and speak an immediate acknowledgement containing the normalized
# intent so the driver knows what the system accepted before execution starts.
# ---------------------------------------------------------------------------
voice = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
replace_once(
    voice,
    '''    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
''',
    '''    override fun onCreate() {
        super.onCreate()
        HandsFreeDebugRelay.configure(this)
        val nm = getSystemService(NotificationManager::class.java)
''',
)
replace_once(
    voice,
    '''        scope.cancel()
        super.onDestroy()
''',
    '''        HandsFreeDebugRelay.publish("voice", "hands-free service destroyed")
        HandsFreeDebugRelay.disable()
        scope.cancel()
        super.onDestroy()
''',
)
replace_once(
    voice,
    '''                override fun onTurnReady(itemId: String, cumulativeTranscript: String) {
                    if (!isCurrent(serial)) return
                    val generation = stoppedGeneration.remove(itemId) ?: speechGeneration.get()
''',
    '''                override fun onTurnReady(itemId: String, cumulativeTranscript: String) {
                    if (!isCurrent(serial)) return
                    HandsFreeDebugRelay.publish("stt-final", cumulativeTranscript)
                    val generation = stoppedGeneration.remove(itemId) ?: speechGeneration.get()
''',
)
replace_once(
    voice,
    '''        _liveTranscript.value = intent
        updateNotification("Hands-free → ${intent.take(80)}")
        val agent = AgentService.instance
''',
    '''        _liveTranscript.value = intent
        HandsFreeDebugRelay.publish("intent-accepted", intent)
        updateNotification("Hands-free → ${intent.take(80)}")
        HandsFreeSpeaker.speak(this, "Принял. ${intent.take(180)}")
        val agent = AgentService.instance
''',
)
replace_once(
    voice,
    '''            delay(2_500L)
            if (realtime == null) _liveTranscript.value = ""
''',
    '''            delay(8_000L)
            if (realtime == null) _liveTranscript.value = ""
''',
)
replace_once(
    voice,
    '''    private fun updateNotification(text: String) {
        _runtimeStatus.value = text
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }
''',
    '''    private fun updateNotification(text: String) {
        _runtimeStatus.value = text
        HandsFreeDebugRelay.publish("voice-status", text)
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }
''',
)

# ---------------------------------------------------------------------------
# Mirror the existing structured trace timeline to the same ephemeral debug
# topic. Artifact bodies (screenshots, prompts, tool args) stay local; only the
# trace JSONL event itself is mirrored.
# ---------------------------------------------------------------------------
trace = root / 'app/src/main/kotlin/ai/closepaw/trace/FileTraceRecorder.kt'
replace_once(
    trace,
    '''    override fun record(event: TraceEventRecord) {
        val line = TraceJson.instance.encodeToString(event)
        enqueue(WriteOp.AppendLine(line))
    }
''',
    '''    override fun record(event: TraceEventRecord) {
        val line = TraceJson.instance.encodeToString(event)
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publishTraceLine(line)
        enqueue(WriteOp.AppendLine(line))
    }
''',
)

# ---------------------------------------------------------------------------
# Voice & Runtime page: expose a copyable read URL. The random topic is created
# on-device, never committed to this public repository.
# ---------------------------------------------------------------------------
settings = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/VoiceRuntimeSettingsPage.kt'
text = settings.read_text(encoding='utf-8')
if 'import ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay\n' not in text:
    text = text.replace(
        'import ai.closepaw.ui.capsule.voice.HandsFreeVoiceService\n',
        'import ai.closepaw.ui.capsule.voice.HandsFreeVoiceService\nimport ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay\n',
        1,
    )
settings.write_text(text, encoding='utf-8')

replace_once(
    settings,
    '''            SettingsSection(title = "Hands-free") {
                val gateReady = agentProvider == LLMProvider.OPENAI_CODEX && agentCredentialPresent
                RuntimeCard(
''',
    '''            SettingsSection(title = "Hands-free") {
                val gateReady = agentProvider == LLMProvider.OPENAI_CODEX && agentCredentialPresent
                val debugUrl = remember(context, runtimeStatus) { HandsFreeDebugRelay.readUrl(context) }
                RuntimeCard(
''',
)
replace_once(
    settings,
    '''                        "Answer voice: Android TTS · $ttsEngine · language auto RU/EN",
                    ),
''',
    '''                        "Answer voice: Android TTS · $ttsEngine · language auto RU/EN",
                        "Approvals: AUTO-APPROVE while hands-free is active",
                        "Trace: forced ON for hands-free sessions",
                        "Debug stream: $debugUrl",
                    ),
''',
)
replace_once(
    settings,
    '''                Button(
                    onClick = {
                        localStartError = null
                        if (HandsFreeVoiceService.isEnabled(context)) {
                            HandsFreeVoiceService.setEnabled(context, false)
                        } else if (!microphoneGranted) {
                            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        } else {
                            localStartError = HandsFreeVoiceService.setEnabled(context, true)
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (handsFreeEnabled) "Turn off hands-free" else "Turn on hands-free")
                }
''',
    '''                Button(
                    onClick = {
                        localStartError = null
                        if (HandsFreeVoiceService.isEnabled(context)) {
                            HandsFreeVoiceService.setEnabled(context, false)
                        } else if (!microphoneGranted) {
                            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        } else {
                            localStartError = HandsFreeVoiceService.setEnabled(context, true)
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (handsFreeEnabled) "Turn off hands-free" else "Turn on hands-free")
                }
                Button(
                    onClick = {
                        val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as android.content.ClipboardManager
                        clipboard.setPrimaryClip(android.content.ClipData.newPlainText("ClosePaw debug stream", debugUrl))
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Copy debug stream URL")
                }
''',
)

print('Hands-free observability + auto-approve patch applied')
