package ai.closepaw.ui.capsule.voice

import android.content.Context

/** Persistent, user-tunable microWakeWord sensitivity. Lower threshold means easier wake-up. */
internal object HandsFreeWakeSettings {
    private const val PREFS = "voice_transcription_prefs"
    private const val KEY_THRESHOLD = "hands_free_wake_threshold"

    const val DEFAULT_THRESHOLD = 0.85f
    const val MIN_THRESHOLD = 0.50f
    const val MAX_THRESHOLD = 0.99f

    @Volatile private var cachedThreshold: Float? = null

    fun load(context: Context): Float {
        cachedThreshold?.let { return it }
        val stored = context.applicationContext
            .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getFloat(KEY_THRESHOLD, DEFAULT_THRESHOLD)
            .coerceIn(MIN_THRESHOLD, MAX_THRESHOLD)
        cachedThreshold = stored
        return stored
    }

    fun save(context: Context, value: Float): Float {
        val normalized = value.coerceIn(MIN_THRESHOLD, MAX_THRESHOLD)
        cachedThreshold = normalized
        context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putFloat(KEY_THRESHOLD, normalized)
            .apply()
        return normalized
    }
}
