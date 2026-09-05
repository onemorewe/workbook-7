package ai.closepaw.ui.capsule.voice

import android.content.Context
import android.speech.tts.TextToSpeech
import java.util.Locale

/** Speaks agent answers only while hands-free mode is enabled. */
object HandsFreeSpeaker {
    private var tts: TextToSpeech? = null
    private var ready = false
    private var pending: String? = null

    @Synchronized
    fun speak(context: Context, text: String) {
        if (!HandsFreeVoiceService.isEnabled(context)) return
        val cleaned = text.trim().take(3500)
        if (cleaned.isBlank()) return
        pending = cleaned

        val existing = tts
        if (existing != null && ready) {
            speakNow(existing, cleaned)
            pending = null
            return
        }

        if (existing == null) {
            val app = context.applicationContext
            tts = TextToSpeech(app) { status ->
                synchronized(this) {
                    ready = status == TextToSpeech.SUCCESS
                    val engine = tts
                    val queued = pending
                    if (ready && engine != null && !queued.isNullOrBlank()) {
                        speakNow(engine, queued)
                        pending = null
                    }
                }
            }
        }
    }

    private fun speakNow(engine: TextToSpeech, text: String) {
        val hasCyrillic = text.any { it in '\u0400'..'\u04FF' }
        engine.language = if (hasCyrillic) Locale("ru", "RU") else Locale.US
        engine.speak(text, TextToSpeech.QUEUE_FLUSH, null, "closepaw-handsfree-answer")
    }

    @Synchronized
    fun shutdown() {
        tts?.stop()
        tts?.shutdown()
        tts = null
        ready = false
        pending = null
    }
}
