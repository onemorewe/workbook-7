package ai.closepaw.ui.capsule.voice

import android.content.Context
import java.io.IOException
import kotlin.coroutines.resume
import kotlinx.coroutines.suspendCancellableCoroutine
import org.json.JSONObject
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.StorageService

/**
 * Local-only wake detector used while hands-free mode is idle.
 *
 * Vosk is intentionally constrained to a tiny Russian grammar. It is a practical v1 wake engine:
 * nothing is uploaded before a wake word is detected. The recognizer consumes 16 kHz PCM; the
 * service records at 24 kHz for Realtime transcription, so frames are downsampled here.
 *
 * This is deliberately isolated behind one class so it can later be replaced by a trained
 * microWakeWord model without touching the Realtime/intent pipeline.
 */
internal class LocalWakeWordDetector(
    private val context: Context,
) : AutoCloseable {
    companion object {
        const val ASSET_MODEL = "vosk-model-small-ru-0.22"
        private const val TARGET_DIR = "vosk-wake-ru-0.22"
        private const val VOSK_RATE = 16_000f
        private const val GRAMMAR = "[\"алёша\",\"алеша\",\"лёша\",\"леша\",\"[unk]\"]"
    }

    @Volatile private var model: Model? = null
    @Volatile private var recognizer: Recognizer? = null

    suspend fun initialize(): Result<Unit> = suspendCancellableCoroutine { continuation ->
        StorageService.unpack(
            context.applicationContext,
            ASSET_MODEL,
            TARGET_DIR,
            { loaded ->
                if (!continuation.isActive) {
                    runCatching { loaded.close() }
                    return@unpack
                }
                try {
                    val r = Recognizer(loaded, VOSK_RATE, GRAMMAR)
                    model = loaded
                    recognizer = r
                    continuation.resume(Result.success(Unit))
                } catch (t: Throwable) {
                    runCatching { loaded.close() }
                    continuation.resume(Result.failure(t))
                }
            },
            { error: IOException ->
                if (continuation.isActive) continuation.resume(Result.failure(error))
            },
        )
    }

    /** Feed one 24 kHz mono PCM16 frame. Returns true once the wake word is recognized. */
    fun accept24k(samples: ShortArray, length: Int = samples.size): Boolean {
        val r = recognizer ?: return false
        if (length <= 0) return false
        val sixteen = downsample24To16(samples, length)
        return try {
            val finalized = r.acceptWaveForm(sixteen, sixteen.size)
            val json = if (finalized) r.result else r.partialResult
            val obj = JSONObject(json)
            val text = if (finalized) obj.optString("text", "") else obj.optString("partial", "")
            if (isWake(text)) {
                r.reset()
                true
            } else {
                false
            }
        } catch (_: Throwable) {
            false
        }
    }

    fun reset() {
        runCatching { recognizer?.reset() }
    }

    private fun isWake(raw: String): Boolean {
        val s = raw.lowercase().replace('ё', 'е').trim()
        if (s.isEmpty()) return false
        return s.split(Regex("\\s+")).any { it == "алеша" || it == "леша" }
    }

    /** Exact-ratio resampler for 24 kHz -> 16 kHz wake recognition. */
    private fun downsample24To16(input: ShortArray, length: Int): ShortArray {
        val outSize = (length * 2) / 3
        if (outSize <= 0) return ShortArray(0)
        val out = ShortArray(outSize)
        for (i in 0 until outSize) {
            val src = (i * 3) / 2
            out[i] = input[src.coerceAtMost(length - 1)]
        }
        return out
    }

    override fun close() {
        val r = recognizer
        recognizer = null
        runCatching { r?.close() }
        val m = model
        model = null
        runCatching { m?.close() }
    }
}
