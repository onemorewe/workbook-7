package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.test.platform.app.InstrumentationRegistry
import java.nio.ByteBuffer
import java.nio.ByteOrder
import junit.framework.TestCase
import kotlinx.coroutines.runBlocking

class HandsFreeSafetyInstrumentedTest : TestCase() {

    fun testEnablingWithoutMicrophonePermissionIsBlockedWithoutStartingService() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val permission = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
        if (permission == PackageManager.PERMISSION_GRANTED) return

        val error = HandsFreeVoiceService.setEnabled(context, true)

        assertNotNull(error)
        assertFalse(HandsFreeVoiceService.isEnabled(context))
    }

    fun testMicroWakeWordNativeRuntimeLoadsAndAcceptsAudio() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val detector = LocalWakeWordDetector(context)
        try {
            val initialized = detector.initialize()
            if (initialized.isFailure) throw initialized.exceptionOrNull()!!
            detector.accept24k(ShortArray(480), 480)
        } finally {
            detector.close()
        }
    }

    /**
     * Feed synthetic spoken "Hey Jarvis" through the exact production microWakeWord frontend/model.
     * The PCM fixture is generated in CI, not hand-crafted silence or a mocked detector.
     */
    fun testSyntheticHeyJarvisTriggersProductionWakeModel() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        val raw = instrumentation.context.assets.open("hey_jarvis_test.pcm").use { it.readBytes() }
        assertTrue("Synthetic wake fixture is empty", raw.isNotEmpty())

        val shorts = ShortArray(raw.size / 2)
        ByteBuffer.wrap(raw).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(shorts)

        val detector = LocalWakeWordDetector(context)
        try {
            val initialized = detector.initialize()
            if (initialized.isFailure) throw initialized.exceptionOrNull()!!

            var fired = false
            var offset = 0
            while (offset < shorts.size && !fired) {
                val count = minOf(480, shorts.size - offset)
                val frame = ShortArray(480)
                System.arraycopy(shorts, offset, frame, 0, count)
                fired = detector.accept24k(frame, count)
                offset += count
            }
            assertTrue("Production Hey Jarvis wake model did not trigger on the synthetic speech fixture", fired)
        } finally {
            detector.close()
        }
    }

    /**
     * Replay the documented Realtime server event sequence into the real production event parser.
     * Intentionally omit speech_stopped: a completed transcription is already a committed VAD turn
     * and must be enough to reach the intent gate. This covers the stall seen on-device where live
     * text appeared but no action followed.
     */
    fun testCompletedRealtimeTranscriptAlwaysBecomesTurnReady() {
        val ready = mutableListOf<String>()
        val live = mutableListOf<String>()
        val errors = mutableListOf<String>()
        val transcriber = RealtimeCommandTranscriber(
            apiKey = "test-key-not-used",
            listener = object : RealtimeCommandTranscriber.Listener {
                override fun onConnected() = Unit
                override fun onSpeechStarted(itemId: String) = Unit
                override fun onSpeechStopped(itemId: String) = Unit
                override fun onLiveTranscript(text: String) { live += text }
                override fun onTurnReady(itemId: String, cumulativeTranscript: String) {
                    ready += cumulativeTranscript
                }
                override fun onError(message: String) { errors += message }
            },
        )
        try {
            transcriber.handleServerEventForTest(
                """{"type":"input_audio_buffer.speech_started","item_id":"msg_1","audio_start_ms":0}"""
            )
            transcriber.handleServerEventForTest(
                """{"type":"conversation.item.input_audio_transcription.delta","item_id":"msg_1","delta":"открой "}"""
            )
            transcriber.handleServerEventForTest(
                """{"type":"conversation.item.input_audio_transcription.completed","item_id":"msg_1","transcript":"открой Яндекс Музыку"}"""
            )

            assertTrue("Realtime parser emitted an unexpected error: $errors", errors.isEmpty())
            assertTrue("Live transcript was never emitted", live.isNotEmpty())
            assertEquals(listOf("открой Яндекс Музыку"), ready)
        } finally {
            transcriber.close()
        }
    }

    fun testRealtimeCompletedTurnIsDeliveredOnlyOnce() {
        var count = 0
        val transcriber = RealtimeCommandTranscriber(
            apiKey = "test-key-not-used",
            listener = object : RealtimeCommandTranscriber.Listener {
                override fun onConnected() = Unit
                override fun onSpeechStarted(itemId: String) = Unit
                override fun onSpeechStopped(itemId: String) = Unit
                override fun onLiveTranscript(text: String) = Unit
                override fun onTurnReady(itemId: String, cumulativeTranscript: String) { count++ }
                override fun onError(message: String) = Unit
            },
        )
        try {
            val completed = """{"type":"conversation.item.input_audio_transcription.completed","item_id":"msg_2","transcript":"what time is it"}"""
            transcriber.handleServerEventForTest(completed)
            transcriber.handleServerEventForTest(completed)
            transcriber.handleServerEventForTest(
                """{"type":"input_audio_buffer.speech_stopped","item_id":"msg_2","audio_end_ms":1000}"""
            )
            assertEquals(1, count)
        } finally {
            transcriber.close()
        }
    }
}
