from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Jarvis visibility anchor not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# ---------------------------------------------------------------------------
# 1. Real bug from build 132: catalog key != wire model id.
#    OPENAI_CODEX catalog names such as gpt-5.5-codex resolve to modelId gpt-5.5.
#    Codex backend rejects the catalog key on the wire.
# ---------------------------------------------------------------------------
gate = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeIntentGate.kt'
g = gate.read_text(encoding='utf-8')
if 'model = selected,' not in g:
    raise SystemExit('Intent gate selected-model wire anchor missing')
g = g.replace(
    '''        val result = clientFor(catalog, selected).chatWithTools(
            systemPrompt = systemPrompt,
            inputItems = input,
            tools = emptyList(),
            model = selected,
        )
''',
    '''        HandsFreeDebugRelay.publish(
            stage = "intent-gate-request",
            message = "Intent gate request catalog=$selected wire=${entry.modelId} provider=${entry.provider}",
            metadata = mapOf(
                "catalog_model" to selected,
                "wire_model" to entry.modelId,
                "provider" to entry.provider.name,
            ),
        )
        val result = clientFor(catalog, selected).chatWithTools(
            systemPrompt = systemPrompt,
            inputItems = input,
            tools = emptyList(),
            model = entry.modelId,
        )
''',
    1,
)
gate.write_text(g, encoding='utf-8')


# ---------------------------------------------------------------------------
# 2. Process-local run ledger. Every wake gets its own run id and explicit resource state.
#    This is UI/debug state only; Supabase remains the durable remote trace.
# ---------------------------------------------------------------------------
tracker = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeRunTracker.kt'
tracker.write_text(r'''package ai.closepaw.ui.capsule.voice

import java.util.UUID
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

internal data class HandsFreeRunSnapshot(
    val runId: String,
    val startedAtMs: Long,
    val stage: String,
    val terminal: Boolean = false,
    val sttState: String = "CLOSED",
    val intentState: String = "IDLE",
    val agentSessionId: String? = null,
    val agentState: String = "NONE",
    val agentModel: String? = null,
    val transcript: String? = null,
    val intent: String? = null,
    val events: List<String> = emptyList(),
)

/** Human-readable resource ledger for Jarvis. No credentials, audio, prompts or screenshots. */
internal object HandsFreeRunTracker {
    private const val MAX_RUNS = 12
    private const val MAX_EVENTS = 8
    private val lock = Any()
    private val _runs = MutableStateFlow<List<HandsFreeRunSnapshot>>(emptyList())
    val runs: StateFlow<List<HandsFreeRunSnapshot>> = _runs.asStateFlow()

    fun begin(): String {
        val id = UUID.randomUUID().toString()
        mutateNew(
            HandsFreeRunSnapshot(
                runId = id,
                startedAtMs = System.currentTimeMillis(),
                stage = "WAKE",
                events = listOf("WAKE · local wake accepted"),
            )
        )
        return id
    }

    fun update(
        runId: String?,
        stage: String,
        detail: String,
        sttState: String? = null,
        intentState: String? = null,
        agentSessionId: String? = null,
        agentState: String? = null,
        agentModel: String? = null,
        terminal: Boolean? = null,
    ) {
        if (runId.isNullOrBlank()) return
        mutate(runId) { old ->
            old.copy(
                stage = stage,
                sttState = sttState ?: old.sttState,
                intentState = intentState ?: old.intentState,
                agentSessionId = agentSessionId ?: old.agentSessionId,
                agentState = agentState ?: old.agentState,
                agentModel = agentModel ?: old.agentModel,
                terminal = terminal ?: old.terminal,
                events = (old.events + "$stage · $detail").takeLast(MAX_EVENTS),
            )
        }
    }

    fun setTranscript(runId: String?, transcript: String) {
        if (runId.isNullOrBlank()) return
        mutate(runId) { it.copy(transcript = transcript.take(500)) }
    }

    fun setIntent(runId: String?, intent: String) {
        if (runId.isNullOrBlank()) return
        mutate(runId) { it.copy(intent = intent.take(500)) }
    }

    fun attachAgent(runId: String?, sessionId: String, model: String) {
        update(
            runId = runId,
            stage = "AGENT_OPEN",
            detail = "session=${sessionId.take(8)} model=$model",
            agentSessionId = sessionId,
            agentState = "OPEN",
            agentModel = model,
        )
    }

    fun fail(runId: String?, detail: String) {
        update(
            runId = runId,
            stage = "ERROR",
            detail = detail,
            sttState = "CLOSED",
            intentState = "IDLE",
            agentState = current(runId)?.agentState ?: "NONE",
            terminal = true,
        )
    }

    fun close(runId: String?, detail: String) {
        update(
            runId = runId,
            stage = "CLOSED",
            detail = detail,
            sttState = "CLOSED",
            intentState = "IDLE",
            agentState = "CLOSED",
            terminal = true,
        )
    }

    fun current(runId: String?): HandsFreeRunSnapshot? =
        if (runId == null) null else _runs.value.firstOrNull { it.runId == runId }

    private fun mutateNew(snapshot: HandsFreeRunSnapshot) = synchronized(lock) {
        _runs.value = (listOf(snapshot) + _runs.value).take(MAX_RUNS)
    }

    private fun mutate(runId: String, block: (HandsFreeRunSnapshot) -> HandsFreeRunSnapshot) = synchronized(lock) {
        val old = _runs.value
        val index = old.indexOfFirst { it.runId == runId }
        if (index < 0) return@synchronized
        val next = old.toMutableList()
        next[index] = block(next[index])
        _runs.value = next
    }
}
''', encoding='utf-8')


# ---------------------------------------------------------------------------
# 3. Voice state machine feeds the run ledger and pre-agent capsule.
# ---------------------------------------------------------------------------
voice = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
v = voice.read_text(encoding='utf-8')

# Current audio/intent run is separate from the later AgentSession lifecycle.
anchor = '    @Volatile private var commandStartedAt: Long = 0L\n'
if anchor not in v:
    raise SystemExit('HandsFreeVoiceService commandStartedAt anchor missing')
v = v.replace(anchor, anchor + '    @Volatile private var currentRunId: String? = null\n', 1)

# Start a ledger entry as soon as wake is accepted.
old = '''        val serial = commandSerial.incrementAndGet()
        commandStartedAt = SystemClock.elapsedRealtime()
        _liveTranscript.value = "Слушаю…"
'''
new = '''        val serial = commandSerial.incrementAndGet()
        val runId = HandsFreeRunTracker.begin()
        currentRunId = runId
        commandStartedAt = SystemClock.elapsedRealtime()
        HandsFreeRunTracker.update(runId, "STT_OPENING", "opening live transcription", sttState = "OPENING")
        AgentService.instance?.showHandsFreeStage(runId, "Jarvis · wake accepted · opening STT")
        _liveTranscript.value = "Слушаю…"
'''
if old not in v:
    raise SystemExit('HandsFree beginCommand anchor missing')
v = v.replace(old, new, 1)

# Socket lifecycle + visible phases.
v = v.replace(
    '''                override fun onConnected() {
                    if (!isCurrent(serial)) return
                    updateNotification("Алёша • слушаю команду…")
                }
''',
    '''                override fun onConnected() {
                    if (!isCurrent(serial)) return
                    HandsFreeRunTracker.update(currentRunId, "STT_OPEN", "socket connected", sttState = "OPEN")
                    AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · STT connected · listening")
                    updateNotification("Алёша • слушаю команду…")
                }
''',
    1,
)
v = v.replace(
    '''                override fun onSpeechStarted(itemId: String) {
                    if (!isCurrent(serial)) return
                    speechGeneration.incrementAndGet()
                    gateJob?.cancel()
                    updateNotification("Алёша • слушаю…")
                }
''',
    '''                override fun onSpeechStarted(itemId: String) {
                    if (!isCurrent(serial)) return
                    speechGeneration.incrementAndGet()
                    gateJob?.cancel()
                    HandsFreeRunTracker.update(currentRunId, "LISTENING", "speech detected", intentState = "IDLE")
                    AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · listening…")
                    updateNotification("Алёша • слушаю…")
                }
''',
    1,
)
v = v.replace(
    '''                override fun onSpeechStopped(itemId: String) {
                    if (!isCurrent(serial)) return
                    stoppedGeneration[itemId] = speechGeneration.get()
                    endBeep()
                    updateNotification("Алёша • пауза, проверяю intent…")
                }
''',
    '''                override fun onSpeechStopped(itemId: String) {
                    if (!isCurrent(serial)) return
                    stoppedGeneration[itemId] = speechGeneration.get()
                    endBeep()
                    HandsFreeRunTracker.update(currentRunId, "VAD_STOP", "speech ended; waiting for final transcript")
                    AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · speech ended · finalizing transcript")
                    updateNotification("Алёша • пауза, проверяю intent…")
                }
''',
    1,
)
v = v.replace(
    '''                override fun onLiveTranscript(text: String) {
                    if (!isCurrent(serial)) return
                    _liveTranscript.value = text
                }
''',
    '''                override fun onLiveTranscript(text: String) {
                    if (!isCurrent(serial)) return
                    _liveTranscript.value = text
                    HandsFreeRunTracker.setTranscript(currentRunId, text)
                }
''',
    1,
)

# The observability patch already inserts stt-final; add the local ledger next to it.
v = v.replace(
    '''                    HandsFreeDebugRelay.publish("stt-final", cumulativeTranscript)
                    val stopped = stoppedGeneration.remove(itemId)
''',
    '''                    HandsFreeDebugRelay.publish("stt-final", cumulativeTranscript)
                    HandsFreeRunTracker.setTranscript(currentRunId, cumulativeTranscript)
                    HandsFreeRunTracker.update(currentRunId, "TRANSCRIPT", "final transcript ready")
                    AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · transcript ready · checking intent")
                    val stopped = stoppedGeneration.remove(itemId)
''',
    1,
)

# Gate state is explicit on both first and final pass.
v = v.replace(
    '''            updateNotification("Hands-free • intent gate: checking…")
            val first = gate.classify(transcript)
''',
    '''            HandsFreeRunTracker.update(currentRunId, "INTENT_CHECK", "request active", intentState = "ACTIVE")
            AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · intent check…")
            updateNotification("Hands-free • intent gate: checking…")
            val first = gate.classify(transcript)
''',
    1,
)
v = v.replace(
    '''                    updateNotification("Hands-free • intent gate: waiting for completion…")
                    delay(1_400L)
''',
    '''                    HandsFreeRunTracker.update(currentRunId, "INTENT_NOT_READY", "waiting for more speech", intentState = "IDLE")
                    AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · intent not complete · waiting")
                    updateNotification("Hands-free • intent gate: waiting for completion…")
                    delay(1_400L)
''',
    1,
)
v = v.replace(
    '''                    val finalPass = gate.classify(transcript, finalAfterSilence = true)
''',
    '''                    HandsFreeRunTracker.update(currentRunId, "INTENT_RECHECK", "final silence pass active", intentState = "ACTIVE")
                    AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · final intent check…")
                    val finalPass = gate.classify(transcript, finalAfterSilence = true)
''',
    1,
)
v = v.replace(
    '''                            if (finalIntent.isNullOrBlank()) {
                                updateNotification("Hands-free • still listening; continue speaking…")
''',
    '''                            if (finalIntent.isNullOrBlank()) {
                                HandsFreeRunTracker.update(currentRunId, "INTENT_NOT_READY", "still incomplete", intentState = "IDLE")
                                AgentService.instance?.showHandsFreeStage(currentRunId, "Jarvis · still waiting for a complete request")
                                updateNotification("Hands-free • still listening; continue speaking…")
''',
    1,
)

# Accepted intent closes STT first, then starts one fresh AgentSession/chat with this run id.
old_accept = '''    private fun acceptIntent(intent: String) {
        // Avoid self-cancelling the currently executing gate coroutine inside closeCommand().
        gateJob = null
        // Critical ordering: stop cloud audio BEFORE the command can start music/TTS.
        closeCommand(clearTranscript = false)
        _liveTranscript.value = intent
        HandsFreeDebugRelay.publish("intent-accepted", intent)
        updateNotification("Hands-free → ${intent.take(80)}")
        HandsFreeSpeaker.speak(this, "Принял. ${intent.take(180)}")
        val agent = AgentService.instance
        if (agent == null) {
            updateNotification("Hands-free heard you • Accessibility service is not active")
        } else {
            agent.submitHandsFreeCommand(intent)
        }
'''
new_accept = '''    private fun acceptIntent(intent: String) {
        val runId = currentRunId
        HandsFreeRunTracker.setIntent(runId, intent)
        HandsFreeRunTracker.update(runId, "INTENT_ACCEPTED", "normalized intent accepted", intentState = "IDLE")
        AgentService.instance?.showHandsFreeStage(runId, "Jarvis · intent accepted · closing STT")
        // Avoid self-cancelling the currently executing gate coroutine inside closeCommand().
        gateJob = null
        // Critical ordering: stop cloud audio BEFORE the command can start music/TTS.
        closeCommand(clearTranscript = false)
        _liveTranscript.value = intent
        HandsFreeDebugRelay.publish("intent-accepted", intent)
        updateNotification("Hands-free → ${intent.take(80)}")
        HandsFreeSpeaker.speak(this, "Принял. ${intent.take(180)}")
        val agent = AgentService.instance
        if (agent == null) {
            HandsFreeRunTracker.fail(runId, "Accessibility AgentService is not active")
            updateNotification("Hands-free heard you • Accessibility service is not active")
        } else {
            HandsFreeRunTracker.update(runId, "AGENT_QUEUED", "creating a fresh AgentSession", agentState = "STARTING")
            agent.showHandsFreeStage(runId, "Jarvis · starting a fresh agent chat…")
            agent.submitHandsFreeCommand(intent, runId)
        }
        currentRunId = null
'''
if old_accept not in v:
    raise SystemExit('HandsFree acceptIntent final generated anchor missing')
v = v.replace(old_accept, new_accept, 1)

# closeCommand must always make network closure visible, but must not mark an accepted run terminal.
v = v.replace(
    '''        val old = realtime
        realtime = null
        commandStartedAt = 0L
''',
    '''        val old = realtime
        realtime = null
        HandsFreeRunTracker.update(currentRunId, "STT_CLOSED", "live transcription socket closed", sttState = "CLOSED", intentState = "IDLE")
        commandStartedAt = 0L
''',
    1,
)

# Abort is terminal before an agent starts.
old_abort = '''    private fun abortCommand(message: String) {
        closeCommand(clearTranscript = false)
        updateNotification("Алёша • $message")
'''
new_abort = '''    private fun abortCommand(message: String) {
        val runId = currentRunId
        closeCommand(clearTranscript = false)
        HandsFreeRunTracker.fail(runId, message)
        AgentService.instance?.showHandsFreeError(runId, "Jarvis · $message")
        currentRunId = null
        updateNotification("Алёша • $message")
'''
if old_abort not in v:
    raise SystemExit('HandsFree abortCommand anchor missing')
v = v.replace(old_abort, new_abort, 1)

voice.write_text(v, encoding='utf-8')


# ---------------------------------------------------------------------------
# 4. One accepted Jarvis call = one fresh AgentSession/chat. Never reuse or overlap.
#    Hands-free sessions shut down after one TaskCompleted or SessionError.
# ---------------------------------------------------------------------------
agent = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
a = agent.read_text(encoding='utf-8')
if 'import java.util.concurrent.ConcurrentHashMap\n' not in a:
    # Put java import before kotlinx imports.
    marker = 'import kotlinx.coroutines.CoroutineScope\n'
    if marker not in a:
        raise SystemExit('AgentService import anchor missing')
    a = a.replace(marker, 'import java.util.concurrent.ConcurrentHashMap\n' + marker, 1)

field_anchor = '    private var session: AgentSession? = null\n'
if field_anchor not in a:
    raise SystemExit('AgentService session field anchor missing')
a = a.replace(
    field_anchor,
    field_anchor + '    private val handsFreeRunBySession = ConcurrentHashMap<String, String>()\n',
    1,
)

# Pre-agent overlay uses the existing capsule state instead of inventing a second overlay system.
method_anchor = '    fun getActiveSession(): AgentSession? = session\n\n'
if method_anchor not in a:
    raise SystemExit('AgentService getActiveSession anchor missing')
a = a.replace(
    method_anchor,
    method_anchor + '''    fun showHandsFreeStage(runId: String?, text: String) {
        if (runId.isNullOrBlank()) return
        serviceScope.launch {
            if (session != null) return@launch
            val controller = overlayController ?: return@launch
            if (!controller.stateHolder.hasActiveTask) {
                controller.onTaskStarted("jarvis-$runId", text)
            } else {
                controller.stateHolder.onThoughtUpdate(text)
            }
        }
    }

    fun showHandsFreeError(runId: String?, text: String) {
        if (runId.isNullOrBlank()) return
        serviceScope.launch {
            if (session == null) overlayController?.stateHolder?.onError(text)
        }
    }

''',
    1,
)

# Replace reusable-hands-free behavior with strict one-run-one-session behavior.
start = a.find('    fun submitHandsFreeCommand(text: String) {')
end = a.find('\n    fun runAgent(', start)
if start < 0 or end < 0:
    raise SystemExit('Could not bound submitHandsFreeCommand')
a = a[:start] + '''    fun submitHandsFreeCommand(text: String, runId: String? = null) {
        val command = text.trim()
        if (command.isEmpty()) return
        val current = session
        if (current != null && current.state.value != ai.closepaw.protocol.SessionState.Shutdown) {
            val id = current.sessionId
            ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
                "agent-busy",
                "Jarvis run refused because AgentSession ${id.take(8)} is still ${current.state.value}",
            )
            ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.fail(
                runId,
                "Another AgentSession ${id.take(8)} is still ${current.state.value}; no second session was started",
            )
            showHandsFreeError(runId, "Jarvis · agent busy · no second session started")
            return
        }

        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
            "agent",
            "starting fresh Jarvis AgentSession run=${runId?.take(8) ?: "unknown"}",
        )
        runAgent(command, handsFree = true, handsFreeRunId = runId)
    }
''' + a[end:]

# Add run id to runAgent without changing ordinary callers.
a = a.replace(
    '''            platformMode: PlatformMode = PlatformMode.ACCESSIBILITY,
            handsFree: Boolean = false,
    ) {
''',
    '''            platformMode: PlatformMode = PlatformMode.ACCESSIBILITY,
            handsFree: Boolean = false,
            handsFreeRunId: String? = null,
    ) {
''',
    1,
)

# Attach exact AgentSession id/model to the Jarvis run.
attach_anchor = '''                session = newSession

                observeSession(newSession)
'''
if attach_anchor not in a:
    raise SystemExit('AgentService newSession attach anchor missing')
a = a.replace(
    attach_anchor,
    '''                session = newSession
                if (handsFree && !handsFreeRunId.isNullOrBlank()) {
                    handsFreeRunBySession[newSession.sessionId] = handsFreeRunId
                    ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.attachAgent(
                        handsFreeRunId,
                        newSession.sessionId,
                        newSession.effectiveMainModel(),
                    )
                    ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
                        "agent-session-open",
                        "Jarvis AgentSession ${newSession.sessionId.take(8)} opened model=${newSession.effectiveMainModel()}",
                    )
                }

                observeSession(newSession)
''',
    1,
)

# If session creation itself fails, close the Jarvis ledger entry too.
a = a.replace(
    '''            } catch (e: Exception) {
                Log.e(TAG, "Failed to create session", e)
                updateStatus("❌ Failed to start: ${e.message}")
                overlayController?.hideAll()
''',
    '''            } catch (e: Exception) {
                Log.e(TAG, "Failed to create session", e)
                if (handsFree) {
                    ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.fail(
                        handsFreeRunId,
                        "AgentSession creation failed: ${e.message ?: e::class.java.simpleName}",
                    )
                }
                updateStatus("❌ Failed to start: ${e.message}")
                overlayController?.hideAll()
''',
    1,
)

# Observe actual agent lifecycle and force one-task hands-free chats closed.
observe_anchor = '''                            } catch (e: Exception) {
                                Log.e(
                                        TAG,
                                        "Failed to handle event: ${event::class.simpleName}",
                                        e
                                )
                            }
'''
if observe_anchor not in a:
    raise SystemExit('AgentService observeSession event anchor missing')
a = a.replace(
    observe_anchor,
    observe_anchor + '''                            handleHandsFreeRunEvent(agentSession, event)
''',
    1,
)

helper_anchor = '    fun runAgent(\n'
helper_pos = a.find(helper_anchor)
if helper_pos < 0:
    raise SystemExit('AgentService runAgent helper insertion anchor missing')
helper = '''    private fun handleHandsFreeRunEvent(
        agentSession: AgentSession,
        event: ai.closepaw.protocol.AgentEvent,
    ) {
        val runId = handsFreeRunBySession[agentSession.sessionId] ?: return
        when (event) {
            is ai.closepaw.protocol.TaskStarted -> {
                ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.update(
                    runId, "AGENT_RUNNING", "task started", agentState = "RUNNING"
                )
            }
            is ai.closepaw.protocol.TurnPhaseChanged -> {
                ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.update(
                    runId, "AGENT_${event.phase.name}", "turn phase ${event.phase}", agentState = event.phase.name
                )
            }
            is ai.closepaw.protocol.TaskCompleted -> {
                ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.update(
                    runId,
                    "AGENT_TASK_DONE",
                    "outcome=${event.outcome}; shutting down one-shot Jarvis chat",
                    agentState = "CLOSING",
                )
                serviceScope.launch { agentSession.submit(Op.Shutdown) }
            }
            is ai.closepaw.protocol.SessionError -> {
                ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.update(
                    runId,
                    "AGENT_ERROR",
                    event.message,
                    agentState = "CLOSING",
                )
                serviceScope.launch { agentSession.submit(Op.Shutdown) }
            }
            is ai.closepaw.protocol.SessionCompleted -> {
                handsFreeRunBySession.remove(agentSession.sessionId)
                ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.close(
                    runId,
                    "AgentSession ${agentSession.sessionId.take(8)} closed reason=${event.reason}",
                )
                ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
                    "agent-session-closed",
                    "Jarvis AgentSession ${agentSession.sessionId.take(8)} closed reason=${event.reason}",
                )
            }
            else -> Unit
        }
    }

'''
a = a[:helper_pos] + helper + a[helper_pos:]

# Service destruction cannot leave the UI claiming an unknown live Jarvis session.
destroy_anchor = '''    override fun onDestroy() {
        isServiceActive = false
        instance = null
'''
if destroy_anchor not in a:
    raise SystemExit('AgentService onDestroy anchor missing')
a = a.replace(
    destroy_anchor,
    '''    override fun onDestroy() {
        isServiceActive = false
        instance = null
        handsFreeRunBySession.forEach { (_, runId) ->
            ai.closepaw.ui.capsule.voice.HandsFreeRunTracker.fail(runId, "AgentService destroyed before terminal session event")
        }
        handsFreeRunBySession.clear()
''',
    1,
)

agent.write_text(a, encoding='utf-8')


# ---------------------------------------------------------------------------
# 5. Voice & Runtime becomes the owner-facing runtime board.
# ---------------------------------------------------------------------------
panel = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/VoiceRuntimeSettingsPage.kt'
p = panel.read_text(encoding='utf-8')
if 'import ai.closepaw.ui.capsule.voice.HandsFreeRunTracker\n' not in p:
    p = p.replace(
        'import ai.closepaw.ui.capsule.voice.HandsFreeRealtimeContract\n',
        'import ai.closepaw.ui.capsule.voice.HandsFreeRealtimeContract\nimport ai.closepaw.ui.capsule.voice.HandsFreeRunTracker\n',
        1,
    )

state_anchor = '    val handsFreeEnabled = HandsFreeVoiceService.isEnabled(context)\n'
if state_anchor not in p:
    raise SystemExit('Voice runtime handsFreeEnabled anchor missing')
p = p.replace(
    state_anchor,
    state_anchor + '''    val jarvisRuns by HandsFreeRunTracker.runs.collectAsState()
    val agentRuntimeStatus by AgentService.statusFlow.collectAsState()
    val sttOpenCount = jarvisRuns.count { !it.terminal && it.sttState in setOf("OPEN", "OPENING") }
    val intentActiveCount = jarvisRuns.count { !it.terminal && it.intentState == "ACTIVE" }
    val agentOpenCount = jarvisRuns.count { !it.terminal && it.agentState !in setOf("NONE", "CLOSED") }
''',
    1,
)

# Add resource truth to the hands-free card.
p = p.replace(
    '''                        "Execution: normal AgentSession pipeline · same Agent selector above",
                        "Answer voice: Android TTS · $ttsEngine · language auto RU/EN",
''',
    '''                        "Execution: fresh one-shot AgentSession/chat per accepted Jarvis call",
                        "Cloud resources NOW: STT=$sttOpenCount · intent=$intentActiveCount · agent=$agentOpenCount",
                        if (sttOpenCount > 1 || intentActiveCount > 1 || agentOpenCount > 1) "BUG: more than one same-stage Jarvis resource is active" else "Resource guard: no duplicate Jarvis cloud resources",
                        "AgentService: ${agentRuntimeStatus.ifBlank { "idle / no status" }}",
                        "Answer voice: Android TTS · $ttsEngine · language auto RU/EN",
''',
    1,
)

# Insert per-wake cards immediately before the decorative footer.
footer = '''            Fleuron()
            Spacer(modifier = Modifier.height(24.dp))
'''
if footer not in p:
    raise SystemExit('Voice runtime footer anchor missing')
run_section = '''            SettingsSection(title = "Jarvis calls · this app process") {
                if (jarvisRuns.isEmpty()) {
                    RuntimeCard(
                        title = "No Jarvis calls yet",
                        lines = listOf(
                            "Idle wake detector may still be listening locally when Hands-free is ON.",
                            "Cloud STT/intent/agent counters above must all be 0 while idle.",
                        ),
                    )
                } else {
                    jarvisRuns.forEach { run ->
                        val title = "#${run.runId.take(8)} · ${if (run.terminal) "CLOSED" else run.stage}"
                        RuntimeCard(
                            title = title,
                            lines = buildList {
                                add("STT: ${run.sttState} · Intent: ${run.intentState}")
                                add("Agent: ${run.agentState} · session=${run.agentSessionId?.take(8) ?: "none"} · model=${run.agentModel ?: "none"}")
                                run.transcript?.takeIf { it.isNotBlank() }?.let { add("Transcript: $it") }
                                run.intent?.takeIf { it.isNotBlank() }?.let { add("Intent: $it") }
                                addAll(run.events)
                            },
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                    }
                }
            }

''' + footer
p = p.replace(footer, run_section, 1)
panel.write_text(p, encoding='utf-8')


# ---------------------------------------------------------------------------
# 6. Small regression tests: catalog key must never be sent as the Codex wire model.
# ---------------------------------------------------------------------------
test_dir = root / 'app/src/test/kotlin/ai/closepaw/ui/capsule/voice'
test_dir.mkdir(parents=True, exist_ok=True)
(test_dir / 'HandsFreeIntentWireModelTest.kt').write_text(r'''package ai.closepaw.ui.capsule.voice

import ai.closepaw.llm.ModelCatalog
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

class HandsFreeIntentWireModelTest {
    @Test
    fun codexCatalogAliasResolvesToUnderlyingWireModel() {
        val catalog = ModelCatalog.fromJson(
            """{"gpt-5.5-codex":{"display_name":"GPT-5.5 ChatGPT","provider":"OPENAI_CODEX","api":"response","model_id":"gpt-5.5","context_window":400000}}"""
        )
        val entry = catalog.resolve("gpt-5.5-codex")
        assertEquals("gpt-5.5", entry.modelId)
        assertNotEquals(entry.name, entry.modelId)
    }
}
''', encoding='utf-8')

print('Jarvis wire-model fix + visible one-run/one-session lifecycle applied')
