"""Guard AgentService startup after the existing ClosePaw patchchain."""
from pathlib import Path
import sys

root = Path(sys.argv[1]) if len(sys.argv) == 2 else Path('.')
path = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
text = path.read_text(encoding='utf-8')


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise SystemExit(f'Pending-start Stop anchor mismatch: {old.splitlines()[0]}')
    return source.replace(old, new, 1)


text = replace_once(text,
    'import kotlinx.coroutines.CancellationException\n',
    'import kotlinx.coroutines.CancellationException\n'
    'import kotlinx.coroutines.NonCancellable\n'
    'import java.util.concurrent.atomic.AtomicLong\n')
text = replace_once(text,
    '    private var session: AgentSession? = null\n',
    '    private var session: AgentSession? = null\n'
    '    private val startupGeneration = AtomicLong()\n'
    '    private var pendingStartupGeneration: Long? = null\n')

start = text.index('    private fun submitOps(vararg ops: Op) {')
end = text.index('\n    private fun updateStatus(', start)
submit = text[start:end]
submit = replace_once(submit,
    '        val currentSession = session\n',
    '''        val isShutdown = ops.any { it == Op.Shutdown }
        val stoppingPendingStart = isShutdown && pendingStartupGeneration != null
        if (isShutdown) {
            startupGeneration.incrementAndGet()
            pendingStartupGeneration = null
        }
        val currentSession = session
''')
submit = replace_once(submit,
    '        if (currentSession == null) {\n',
    '''        if (currentSession == null) {
            if (stoppingPendingStart) {
                // No observed session will emit SessionCompleted for this startup.
                overlayController?.onSessionCompleted(ai.closepaw.protocol.SessionEndReason.USER_STOPPED)
                updateStatus("🛑 Agent stopped")
            }
''')
text = text[:start] + submit + text[end:]

start = text.index('    fun runAgent(\n')
end = text.index('\n    fun submitHandsFreeCommand(', start)
run = text[start:end]
run = replace_once(run,
    '        if (session != null) {\n',
    '''        val generation = startupGeneration.incrementAndGet()
        pendingStartupGeneration = generation
        if (session != null) {
''')
run = replace_once(run,
    '        serviceScope.launch {\n            try {\n',
    '''        serviceScope.launch {
            var unpublishedSession: AgentSession? = null
            try {
                if (!isServiceActive || startupGeneration.get() != generation) return@launch
''')
run = replace_once(run,
    '''                                    overlayTouchGate = touchGate,
                            )
                        }

                session = newSession
''',
    '''                                    overlayTouchGate = touchGate,
                            ).also { unpublishedSession = it }
                        }

                if (!isServiceActive || startupGeneration.get() != generation) return@launch
                session = newSession
                unpublishedSession = null // Ownership transferred to the service.
''')
run = replace_once(run,
    '''            } catch (e: Exception) {
                Log.e(TAG, "Failed to create session", e)
''',
    '''            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (!isServiceActive || startupGeneration.get() != generation) return@launch
                Log.e(TAG, "Failed to create session", e)
''')
run = replace_once(run,
    '''                overlayController?.hideAll()
            }
        }
    }
''',
    '''                overlayController?.hideAll()
            } finally {
                if (pendingStartupGeneration == generation) pendingStartupGeneration = null
                // withContext may discard a factory result when its caller is cancelled.
                // Capture it inside the factory context so that orphan still gets closed.
                unpublishedSession?.let { orphan ->
                    withContext(NonCancellable) {
                        try {
                            val closed = withTimeoutOrNull(SHUTDOWN_TIMEOUT_MS) {
                                orphan.submit(Op.Shutdown)
                                true
                            }
                            if (closed != true) Log.w(TAG, "Timed out closing unpublished session")
                        } catch (e: Exception) {
                            Log.w(TAG, "Failed to close unpublished session", e)
                        }
                    }
                }
            }
        }
    }
''')
text = text[:start] + run + text[end:]
path.write_text(text, encoding='utf-8')
print('AgentService pending-start Stop guard applied')
