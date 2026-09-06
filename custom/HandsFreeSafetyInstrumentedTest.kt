package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.content.pm.PackageManager
import androidx.core.content.ContextCompat
import androidx.test.platform.app.InstrumentationRegistry
import junit.framework.TestCase

/**
 * Android-only safety/Realtime parser checks.
 *
 * Wake-word sensitivity itself is covered by fast JVM unit tests. We intentionally do not
 * synthesize speech or replay a "Hey Jarvis" audio fixture here: the real-device trace already
 * proves the pinned model detects the phrase, while generating speech in every CI run was slow and
 * did not validate the cloud/API contract that actually caused recent failures.
 */
class HandsFreeSafetyInstrumentedTest : TestCase() {

    fun testEnablingWithoutMicrophonePermissionIsBlockedWithoutStartingService() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val permission = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO)
        if (permission == PackageManager.PERMISSION_GRANTED) return

        val error = HandsFreeVoiceService.setEnabled(context, true)

        assertNotNull(error)
        assertFalse(HandsFreeVoiceService.isEnabled(context))
    }

    /** A completed transcription must be sufficient to enter the intent gate exactly once. */
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
