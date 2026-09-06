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

# Assistant cues must follow the user's media volume, not notification/DND volume. The wake cue is
# defined in the service itself; the end cue is injected later by the wake-diagnostics patch, so
# update that patch before it is executed too.
s = p.read_text(encoding='utf-8')
wake_cue = 'ToneGenerator(AudioManager.STREAM_NOTIFICATION, 55)'
if wake_cue not in s:
    raise SystemExit('Wake audio cue anchor not found')
p.write_text(s.replace(wake_cue, 'ToneGenerator(AudioManager.STREAM_MUSIC, 65)', 1), encoding='utf-8')

wake_patch = Path('patch_handsfree_wake_diagnostics.py')
wd = wake_patch.read_text(encoding='utf-8')
end_cue = 'ToneGenerator(AudioManager.STREAM_NOTIFICATION, 45)'
if end_cue not in wd:
    raise SystemExit('End audio cue patch anchor not found')
wake_patch.write_text(wd.replace(end_cue, 'ToneGenerator(AudioManager.STREAM_MUSIC, 55)', 1), encoding='utf-8')

# gpt-live-transcribe currently rejects server_vad in transcription-only Realtime sessions on the
# live API. Keep the existing server-VAD turn semantics, but use the VAD-compatible transcription
# model until a proper client-side VAD + manual input_audio_buffer.commit path is implemented and
# covered by a live OpenAI contract test.
realtime = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/RealtimeCommandTranscriber.kt')
r = realtime.read_text(encoding='utf-8')
old_transcription = '''        val transcription = JSONObject()
            .put("model", "gpt-live-transcribe")
            .put("prompt", "Driving voice command. The speaker may mix Russian and English. Preserve app names, artist names, song titles, technical terms, and proper nouns. Wake word may be Алёша/Alyosha.")
            .put("keywords", JSONArray(listOf("Алёша", "Alyosha", "Yandex Music", "ChatGPT")))
            .put("languages", JSONArray(listOf("ru", "en")))
            .put("delay", "low")
'''
new_transcription = '''        val transcription = JSONObject()
            .put("model", "gpt-4o-transcribe")
            .put("prompt", "Driving voice command. The speaker may mix Russian and English. Preserve app names, artist names, song titles, technical terms, and proper nouns. Wake word may be Алёша/Alyosha.")
'''
if old_transcription not in r:
    raise SystemExit('Realtime transcription model anchor not found')
r = r.replace(old_transcription, new_transcription, 1)
realtime.write_text(r, encoding='utf-8')

settings = Path('app/src/main/kotlin/ai/closepaw/ui/settings/VoiceRuntimeSettingsPage.kt')
v = settings.read_text(encoding='utf-8')
old_label = '"Live STT: gpt-live-transcribe · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",'
new_label = '"Live STT: gpt-4o-transcribe · server VAD · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",'
if old_label not in v:
    raise SystemExit('Voice runtime STT label anchor not found')
settings.write_text(v.replace(old_label, new_label, 1), encoding='utf-8')

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
