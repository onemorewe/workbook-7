from pathlib import Path

p = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt')
s = p.read_text(encoding='utf-8')

old = '''    private fun evaluateIntent(serial: Long, generation: Long, transcript: String) {
        gateJob?.cancel()
        val gate = intentGate ?: return
        gateJob = scope.launch {
            val result = gate.classify(transcript)
            if (!isCurrent(serial) || generation != speechGeneration.get()) return@launch

            result.fold(
                onSuccess = { intent ->
                    if (intent.isNullOrBlank()) {
                        updateNotification("Алёша • intent ещё не готов, слушаю дальше…")
                    } else {
                        // Critical ordering: stop cloud audio BEFORE the command can start music/TTS.
                        closeCommand(clearTranscript = false)
                        _liveTranscript.value = intent
                        updateNotification("Алёша → ${intent.take(80)}")
                        val agent = AgentService.instance
                        if (agent == null) {
                            updateNotification("Алёша услышала • включи Accessibility")
                        } else {
                            agent.submitHandsFreeCommand(intent)
                        }
                        scope.launch {
                            delay(2_500L)
                            if (realtime == null) _liveTranscript.value = ""
                        }
                    }
                },
                onFailure = { error ->
                    // Do not silently fall back to API billing: this gate is intentionally OAuth-only.
                    abortCommand("Intent gate error • ${error.message?.take(80) ?: "проверь ChatGPT sign-in"}")
                },
            )
        }
    }
'''

new = '''    private fun evaluateIntent(serial: Long, generation: Long, transcript: String) {
        gateJob?.cancel()
        val gate = intentGate ?: return
        gateJob = scope.launch {
            updateNotification("Hands-free • intent gate: checking…")
            val first = gate.classify(transcript)
            if (!isCurrent(serial) || generation != speechGeneration.get()) return@launch

            first.fold(
                onSuccess = { intent ->
                    if (!intent.isNullOrBlank()) {
                        acceptIntent(intent)
                        return@fold
                    }

                    updateNotification("Hands-free • intent gate: waiting for completion…")
                    delay(1_400L)
                    if (!isCurrent(serial) || generation != speechGeneration.get()) return@launch

                    val finalPass = gate.classify(transcript, finalAfterSilence = true)
                    if (!isCurrent(serial) || generation != speechGeneration.get()) return@launch
                    finalPass.fold(
                        onSuccess = { finalIntent ->
                            if (finalIntent.isNullOrBlank()) {
                                updateNotification("Hands-free • still listening; continue speaking…")
                            } else {
                                acceptIntent(finalIntent)
                            }
                        },
                        onFailure = { error ->
                            abortCommand("Intent gate error • ${error.message?.take(80) ?: "check ChatGPT sign-in"}")
                        },
                    )
                },
                onFailure = { error ->
                    abortCommand("Intent gate error • ${error.message?.take(80) ?: "check ChatGPT sign-in"}")
                },
            )
        }
    }

    private fun acceptIntent(intent: String) {
        gateJob = null
        closeCommand(clearTranscript = false)
        _liveTranscript.value = intent
        updateNotification("Hands-free → ${intent.take(80)}")
        val agent = AgentService.instance
        if (agent == null) {
            updateNotification("Hands-free heard you • Accessibility service is not active")
        } else {
            agent.submitHandsFreeCommand(intent)
        }
        scope.launch {
            delay(2_500L)
            if (realtime == null) _liveTranscript.value = ""
        }
    }
'''

if old not in s:
    raise SystemExit('evaluateIntent anchor not found')

p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Black-box UI smoke test clicks through the real app with UiAutomator.
gradle = Path('app/build.gradle.kts')
g = gradle.read_text(encoding='utf-8')
anchor = '    androidTestImplementation("androidx.test.ext:junit:1.2.1")\n'
if anchor not in g:
    raise SystemExit('androidTest dependency anchor not found')
if 'androidx.test.uiautomator:uiautomator' not in g:
    g = g.replace(
        anchor,
        anchor + '    androidTestImplementation("androidx.test.uiautomator:uiautomator:2.3.0")\n',
        1,
    )
gradle.write_text(g, encoding='utf-8')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Observability patch anchor not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# Zero-account debug relay. Topic is generated on-device and never committed.
relay = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeDebugRelay.kt')
relay.write_text(r'''package ai.closepaw.ui.capsule.voice

import android.content.Context
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

internal object HandsFreeDebugRelay {
    private const val PREFS = "voice_transcription_prefs"
    private const val KEY_TOPIC = "hands_free_debug_topic"
    private const val BASE = "https://ntfy.sh"
    private const val MAX_MESSAGE_CHARS = 3_500

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = OkHttpClient.Builder().callTimeout(5, TimeUnit.SECONDS).build()

    @Volatile private var topic: String? = null
    @Volatile private var enabled = false

    fun configure(context: Context) {
        topic = ensureTopic(context.applicationContext)
        enabled = true
        publish("relay", "debug relay online")
    }

    fun disable() {
        enabled = false
    }

    fun readUrl(context: Context): String {
        val t = topic ?: ensureTopic(context.applicationContext).also { topic = it }
        return "$BASE/$t/json?poll=1&since=12h"
    }

    fun publish(stage: String, message: String) {
        if (!enabled) return
        val payload = JSONObject()
            .put("ts", System.currentTimeMillis())
            .put("stage", stage.take(80))
            .put("message", sanitize(message))
            .toString()
        post(payload)
    }

    fun publishTraceLine(line: String) {
        if (!enabled) return
        val payload = JSONObject()
            .put("ts", System.currentTimeMillis())
            .put("stage", "trace")
            .put("message", sanitize(line))
            .toString()
        post(payload)
    }

    private fun post(payload: String) {
        val t = topic ?: return
        scope.launch {
            runCatching {
                val body = payload.take(MAX_MESSAGE_CHARS)
                    .toRequestBody("text/plain; charset=utf-8".toMediaType())
                val request = Request.Builder()
                    .url("$BASE/$t")
                    .header("Title", "ClosePaw hands-free debug")
                    .post(body)
                    .build()
                client.newCall(request).execute().use { }
            }
        }
    }

    private fun ensureTopic(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_TOPIC, null)?.takeIf { it.length >= 20 }
        if (existing != null) return existing
        val generated = "closepaw-${UUID.randomUUID().toString().replace("-", "")}".take(60)
        prefs.edit().putString(KEY_TOPIC, generated).apply()
        return generated
    }

    private fun sanitize(raw: String): String = raw
        .replace(Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/-]+=*"), "Bearer <redacted>")
        .replace(Regex("sk-[A-Za-z0-9_-]{12,}"), "sk-<redacted>")
        .replace(Regex("(?i)api[_ -]?key\\s*[:=]\\s*[^, }]+"), "api_key=<redacted>")
        .take(MAX_MESSAGE_CHARS)
}
''', encoding='utf-8')

# Hands-free commands should never get stuck waiting for an approval prompt while driving.
agent = Path('app/src/main/kotlin/ai/closepaw/app/AgentService.kt')
agent_text = agent.read_text(encoding='utf-8')
if 'import ai.closepaw.protocol.ApprovalMode\n' not in agent_text:
    agent_text = agent_text.replace(
        'import ai.closepaw.protocol.Op\n',
        'import ai.closepaw.protocol.Op\nimport ai.closepaw.protocol.ApprovalMode\n',
        1,
    )
agent.write_text(agent_text, encoding='utf-8')

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

# Voice stages + immediate spoken acknowledgement.
voice = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt')
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

# Mirror structured trace timeline only; heavy artifacts remain local.
trace = Path('app/src/main/kotlin/ai/closepaw/trace/FileTraceRecorder.kt')
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

# Surface the random read URL in Settings and make it one-tap copyable.
settings = Path('app/src/main/kotlin/ai/closepaw/ui/settings/VoiceRuntimeSettingsPage.kt')
settings_text = settings.read_text(encoding='utf-8')
if 'import ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay\n' not in settings_text:
    settings_text = settings_text.replace(
        'import ai.closepaw.ui.capsule.voice.HandsFreeVoiceService\n',
        'import ai.closepaw.ui.capsule.voice.HandsFreeVoiceService\nimport ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay\n',
        1,
    )
settings.write_text(settings_text, encoding='utf-8')

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
                        "Approvals: AUTO-APPROVE in hands-free",
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

# Music resolver policy: search first, do not hallucinate canonical titles before checking provider results.
yandex = Path('app/src/main/assets/app_skills/ru.yandex.music/SKILL.md')
yandex.parent.mkdir(parents=True, exist_ok=True)
yandex.write_text('''---
name: app-yandex-music
description: App-specific guidance for Yandex Music hands-free search and playback.
metadata:
  package: ru.yandex.music
---

- Treat spoken artist/title text as a possibly imperfect reference, not as guaranteed canonical metadata.
- First search Yandex Music using the important words exactly as understood. Do not invent or silently rewrite an artist or title before seeing provider results.
- Inspect candidate title + artist. If one candidate confidently matches the user's reference, select it.
- If the reference is a lyric, paraphrase, fuzzy description, or Yandex results are ambiguous, resolve the intended entity semantically first, then search again using canonical title + artist.
- Prefer an exact track over playlists, mixes, podcasts, remixes or covers unless requested.
- After playback starts, verify the playing title/artist matches the intended entity. A successful tap alone is not success.
- Search and playback are safe without confirmation in hands-free mode.
- Do not like/dislike, edit library, subscribe, purchase, or change account settings unless explicitly asked.
''', encoding='utf-8')

print('Hands-free pipeline reliability + observability patch applied')
