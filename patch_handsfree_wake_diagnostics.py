from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Wake diagnostics anchor not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# Expose only numeric detector diagnostics. No microphone audio leaves the detector.
# Anchor before the cutoff declaration so user-tunable/default threshold changes do not break this
# build-time diagnostics patch.
detector = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/LocalWakeWordDetector.kt'
replace_once(
    detector,
    '''    private var outputScale = 1f
    private var outputZeroPoint = 0
    private var inputFrames = 0
''',
    '''    private var outputScale = 1f
    private var outputZeroPoint = 0
    private var inputFrames = 0
    private var latestProbabilityValue = 0f
    private var peakProbabilityValue = 0f

    val latestProbability: Float get() = latestProbabilityValue
    val probabilityCutoff: Float get() = cutoff

    fun consumePeakProbability(): Float {
        val peak = peakProbabilityValue
        peakProbabilityValue = latestProbabilityValue
        return peak
    }
''',
)
replace_once(
    detector,
    '''            val probability = ((raw - outputZeroPoint) * outputScale).coerceIn(0f, 1f)
            recentProbabilities.addLast(probability)
''',
    '''            val probability = ((raw - outputZeroPoint) * outputScale).coerceIn(0f, 1f)
            latestProbabilityValue = probability
            if (probability > peakProbabilityValue) peakProbabilityValue = probability
            recentProbabilities.addLast(probability)
''',
)
replace_once(
    detector,
    '''        pendingFrames.clear()
        recentProbabilities.clear()
    }
''',
    '''        pendingFrames.clear()
        recentProbabilities.clear()
        latestProbabilityValue = 0f
        peakProbabilityValue = 0f
    }
''',
)

# Make wake/listening/end-of-utterance obvious to both the user and remote diagnostics.
voice = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
replace_once(
    voice,
    '''            val frame = ShortArray(FRAME_SAMPLES)
            while (isActive) {
                val read = audio.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                if (read <= 0) continue

                val command = realtime
                if (command == null) {
                    if (detector.accept24k(frame, read)) {
                        beginCommand(apiKey)
                    }
                } else {
''',
    '''            val frame = ShortArray(FRAME_SAMPLES)
            var heartbeatAt = SystemClock.elapsedRealtime()
            var framesSinceHeartbeat = 0L
            var pcmPeakSinceHeartbeat = 0
            while (isActive) {
                val read = audio.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                if (read <= 0) continue

                framesSinceHeartbeat++
                for (i in 0 until read) {
                    val amplitude = kotlin.math.abs(frame[i].toInt())
                    if (amplitude > pcmPeakSinceHeartbeat) pcmPeakSinceHeartbeat = amplitude
                }

                val command = realtime
                if (command == null) {
                    val fired = detector.accept24k(frame, read)
                    val now = SystemClock.elapsedRealtime()
                    if (now - heartbeatAt >= 15_000L) {
                        val wakePeak = detector.consumePeakProbability()
                        HandsFreeDebugRelay.publish(
                            "heartbeat",
                            "wake-listening frames=$framesSinceHeartbeat pcm_peak=$pcmPeakSinceHeartbeat " +
                                "wake_peak=$wakePeak wake_last=${detector.latestProbability} cutoff=${detector.probabilityCutoff}",
                        )
                        heartbeatAt = now
                        framesSinceHeartbeat = 0L
                        pcmPeakSinceHeartbeat = 0
                    }
                    if (fired) {
                        HandsFreeDebugRelay.publish(
                            "wake-detected",
                            "Hey Jarvis accepted probability=${detector.latestProbability} cutoff=${detector.probabilityCutoff}",
                        )
                        beginCommand(apiKey)
                    }
                } else {
''',
)
replace_once(
    voice,
    '''        commandStartedAt = SystemClock.elapsedRealtime()
        _liveTranscript.value = ""
        _commandSessionActive.value = true
        requestTransientAudioFocus()
        beep()
''',
    '''        commandStartedAt = SystemClock.elapsedRealtime()
        _liveTranscript.value = "Слушаю…"
        _commandSessionActive.value = true
        requestTransientAudioFocus()
        beep()
''',
)
replace_once(
    voice,
    '''                override fun onSpeechStopped(itemId: String) {
                    if (!isCurrent(serial)) return
                    stoppedGeneration[itemId] = speechGeneration.get()
                    updateNotification("Алёша • пауза, проверяю intent…")
                }
''',
    '''                override fun onSpeechStopped(itemId: String) {
                    if (!isCurrent(serial)) return
                    stoppedGeneration[itemId] = speechGeneration.get()
                    endBeep()
                    updateNotification("Алёша • пауза, проверяю intent…")
                }
''',
)
replace_once(
    voice,
    '''                    HandsFreeDebugRelay.publish("stt-final", cumulativeTranscript)
                    val generation = stoppedGeneration.remove(itemId) ?: speechGeneration.get()
''',
    '''                    HandsFreeDebugRelay.publish("stt-final", cumulativeTranscript)
                    val stopped = stoppedGeneration.remove(itemId)
                    if (stopped == null) endBeep()
                    val generation = stopped ?: speechGeneration.get()
''',
)
replace_once(
    voice,
    '''    private fun notification(text: String): android.app.Notification {
''',
    '''    private fun endBeep() {
        scope.launch {
            runCatching {
                val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 45)
                tone.startTone(ToneGenerator.TONE_PROP_ACK, 110)
                delay(130L)
                tone.release()
            }
        }
    }

    private fun notification(text: String): android.app.Notification {
''',
)

# Deliberately do NOT touch AgentService model routing here. Jarvis wake/STT/intent diagnostics are
# input concerns only. Accepted intents must execute through the exact same configured Agent model
# as keyboard and normal-microphone input. In particular, diagnostics must never reintroduce an
# automatic ChatGPT-subscription -> paid-API execution fallback.
agent = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
agent_text = agent.read_text(encoding='utf-8')
for forbidden in (
    'HandsFreeIntentGate.activeExecutionModel',
    'desiredHandsFreeModel',
):
    if forbidden in agent_text:
        raise SystemExit(f'Stale hands-free execution routing still present in AgentService: {forbidden}')

print('Hands-free wake diagnostics + audio cues applied; Agent routing left unified')
