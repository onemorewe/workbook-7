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

                    // A single NOT_READY must not deadlock a completed user turn forever. Give the
                    // speaker a grace period; if no new speech arrives, ask the same gate again with
                    // an explicit end-of-turn signal. New speech cancels this job immediately.
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
                    // Do not silently fall back to API billing: this gate is intentionally OAuth-only.
                    abortCommand("Intent gate error • ${error.message?.take(80) ?: "check ChatGPT sign-in"}")
                },
            )
        }
    }

    private fun acceptIntent(intent: String) {
        // Avoid self-cancelling the currently executing gate coroutine inside closeCommand().
        gateJob = null
        // Critical ordering: stop cloud audio BEFORE the command can start music/TTS.
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

print('Hands-free pipeline reliability patch applied')
