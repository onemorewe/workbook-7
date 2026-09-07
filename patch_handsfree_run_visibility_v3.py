from pathlib import Path

# Apply the substantive Jarvis visibility patch against the actual upstream layout and normalize
# ClosePaw's @JvmInline SessionId to its String value everywhere the UI/run ledger needs text keys.
source_path = Path('..') / 'patch_handsfree_run_visibility.py'
source = source_path.read_text(encoding='utf-8')

old_boundary = "end = a.find('\\n    fun runAgent(', start)"
new_boundary = "end = a.find('\\n    fun stopAgent()', start)"
if old_boundary not in source:
    raise SystemExit('Expected submitHandsFreeCommand boundary anchor missing')
source = source.replace(old_boundary, new_boundary, 1)

# AgentSession.sessionId is ai.closepaw.protocol.SessionId, not String.
for old, new in (
    ('current.sessionId', 'current.sessionId.value'),
    ('newSession.sessionId', 'newSession.sessionId.value'),
    ('agentSession.sessionId', 'agentSession.sessionId.value'),
):
    source = source.replace(old, new)

exec(compile(source, str(source_path), 'exec'))

# Refine the overlap guard after generation. A normal Created/Idle chat can be shut down and
# replaced. A Running/Paused agent, or any previous one-shot Jarvis session that has not emitted
# SessionCompleted yet, blocks a second Jarvis AgentSession.
agent = Path('app/src/main/kotlin/ai/closepaw/app/AgentService.kt')
a = agent.read_text(encoding='utf-8')
old_guard = '''        val current = session
        if (current != null && current.state.value != ai.closepaw.protocol.SessionState.Shutdown) {
            val id = current.sessionId.value
'''
new_guard = '''        val current = session
        val currentId = current?.sessionId?.value
        val currentState = current?.state?.value
        val previousJarvisRun = currentId?.let { handsFreeRunBySession[it] }
        val busy = current != null &&
            currentState != ai.closepaw.protocol.SessionState.Shutdown &&
            (previousJarvisRun != null ||
                currentState == ai.closepaw.protocol.SessionState.Running ||
                currentState == ai.closepaw.protocol.SessionState.Paused)
        if (busy && current != null) {
            val id = current.sessionId.value
'''
if old_guard not in a:
    raise SystemExit('Generated Jarvis overlap guard anchor missing')
a = a.replace(old_guard, new_guard, 1)
agent.write_text(a, encoding='utf-8')

# If Android/service lifecycle stops while wake/STT/intent is in progress, make the run terminal
# instead of leaving a UI entry that looks like an open cloud socket forever.
voice = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt')
v = voice.read_text(encoding='utf-8')
old_destroy = '''    override fun onDestroy() {
        gateJob?.cancel()
        listenJob?.cancel()
        closeCommand(clearTranscript = true)
'''
new_destroy = '''    override fun onDestroy() {
        val abandonedRunId = currentRunId
        gateJob?.cancel()
        listenJob?.cancel()
        closeCommand(clearTranscript = true)
        if (abandonedRunId != null) {
            HandsFreeRunTracker.fail(abandonedRunId, "Hands-free service stopped before this run completed")
            AgentService.instance?.showHandsFreeError(abandonedRunId, "Jarvis · service stopped · run closed")
            currentRunId = null
        }
'''
if old_destroy not in v:
    raise SystemExit('HandsFreeVoiceService onDestroy terminal-run anchor missing')
v = v.replace(old_destroy, new_destroy, 1)
voice.write_text(v, encoding='utf-8')

print('Typed SessionId normalized; idle replacement and terminal lifecycle guards applied')
