package ai.closepaw.ui.capsule.voice

import androidx.annotation.Keep

/**
 * JNI wrapper around TensorFlow Lite Micro's fixed-point microfrontend used by microWakeWord.
 * It converts 16 kHz mono PCM into one forty-bin feature vector every ten milliseconds.
 */
@Keep
internal class MicroFrontend(
    private val sampleRate: Int = SAMPLE_RATE,
    private val stepSizeMs: Int = STEP_SIZE_MS,
) : AutoCloseable {
    companion object {
        const val SAMPLE_RATE = 16_000
        const val STEP_SIZE_MS = 10
        const val FEATURE_SIZE = 40

        init {
            System.loadLibrary("microfrontend")
        }

        @JvmStatic private external fun nativeCreate(sampleRate: Int, stepSizeMs: Int): Long
        @JvmStatic private external fun nativeDestroy(handle: Long)
        @JvmStatic private external fun nativeProcessSamples(handle: Long, samples: ShortArray): ArrayList<FloatArray>?
        @JvmStatic private external fun nativeReset(handle: Long)
    }

    private var handle: Long = nativeCreate(sampleRate, stepSizeMs)

    val isInitialized: Boolean get() = handle != 0L

    fun processSamples(samples: ShortArray): List<FloatArray> {
        if (handle == 0L || samples.isEmpty()) return emptyList()
        return nativeProcessSamples(handle, samples) ?: emptyList()
    }

    fun reset() {
        if (handle != 0L) nativeReset(handle)
    }

    override fun close() {
        val current = handle
        handle = 0L
        if (current != 0L) nativeDestroy(current)
    }
}
