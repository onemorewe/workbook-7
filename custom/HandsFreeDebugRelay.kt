package ai.closepaw.ui.capsule.voice

import android.content.Context
import java.util.UUID
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/**
 * Tiny zero-account debug relay for hands-free development.
 *
 * It publishes compact text/JSON events to a random ntfy.sh topic generated locally on the
 * device. The topic is intentionally not committed to source control. Anyone who knows the topic
 * URL can read it until ntfy cache expiry, so never send credentials, screenshots or prompt
 * artifacts through this relay.
 */
internal object HandsFreeDebugRelay {
    private const val PREFS = "voice_transcription_prefs"
    private const val KEY_TOPIC = "hands_free_debug_topic"
    private const val BASE = "https://ntfy.sh"
    private const val MAX_MESSAGE_CHARS = 3_500

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = OkHttpClient.Builder()
        .callTimeout(5, TimeUnit.SECONDS)
        .build()

    @Volatile private var topic: String? = null
    @Volatile private var enabled = false

    fun configure(context: Context) {
        topic = ensureTopic(context.applicationContext)
        enabled = true
        publish("relay", "debug relay online")
    }

    fun disable() {
        enabled = false
    }

    fun readUrl(context: Context): String {
        val t = topic ?: ensureTopic(context.applicationContext).also { topic = it }
        return "$BASE/$t/json?poll=1&since=12h"
    }

    fun publish(stage: String, message: String) {
        if (!enabled) return
        val payload = JSONObject()
            .put("ts", System.currentTimeMillis())
            .put("stage", stage.take(80))
            .put("message", sanitize(message))
            .toString()
        post(payload)
    }

    fun publishTraceLine(line: String) {
        if (!enabled) return
        val payload = JSONObject()
            .put("ts", System.currentTimeMillis())
            .put("stage", "trace")
            .put("message", sanitize(line))
            .toString()
        post(payload)
    }

    private fun post(payload: String) {
        val t = topic ?: return
        scope.launch {
            runCatching {
                val body = payload.take(MAX_MESSAGE_CHARS)
                    .toRequestBody("text/plain; charset=utf-8".toMediaType())
                val request = Request.Builder()
                    .url("$BASE/$t")
                    .header("Title", "ClosePaw hands-free debug")
                    .post(body)
                    .build()
                client.newCall(request).execute().use { }
            }
        }
    }

    private fun ensureTopic(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val existing = prefs.getString(KEY_TOPIC, null)?.takeIf { it.length >= 20 }
        if (existing != null) return existing
        val generated = "closepaw-${UUID.randomUUID().toString().replace("-", "")}".take(60)
        prefs.edit().putString(KEY_TOPIC, generated).apply()
        return generated
    }

    private fun sanitize(raw: String): String = raw
        .replace(Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/-]+=*"), "Bearer <redacted>")
        .replace(Regex("sk-[A-Za-z0-9_-]{12,}"), "sk-<redacted>")
        .replace(Regex("(?i)api[_ -]?key\\s*[:=]\\s*[^, }]+"), "api_key=<redacted>")
        .take(MAX_MESSAGE_CHARS)
}
