package ai.closepaw.ui.capsule.voice

import android.content.Context
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
 * Zero-account remote debug relay for the hands-free prototype.
 *
 * The topic is intentionally pinned in source control so the development assistant can inspect the
 * same stream after every install/update without asking the driver to copy anything from the phone.
 * This is a development-only observability choice; anyone who knows the topic can read cached events.
 * Credentials are still redacted before publishing.
 */
internal object HandsFreeDebugRelay {
    private const val BASE = "https://ntfy.sh"
    private const val TOPIC = "closepaw-hf-7ff9c7fb0ec9b03ae896c1af451e26826e2eff8fa63824fd"
    private const val MAX_MESSAGE_CHARS = 3_500

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = OkHttpClient.Builder()
        .callTimeout(5, TimeUnit.SECONDS)
        .build()

    @Volatile private var enabled = false

    fun configure(context: Context) {
        // Keep Context in the API because callers are Android lifecycle owners and this lets us add
        // device/build metadata later without changing every call site.
        @Suppress("UNUSED_VARIABLE") val appContext = context.applicationContext
        enabled = true
        publish("relay", "debug relay online")
    }

    fun disable() {
        enabled = false
    }

    fun readUrl(context: Context): String {
        @Suppress("UNUSED_VARIABLE") val appContext = context.applicationContext
        return "$BASE/$TOPIC/json?poll=1&since=12h"
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
        scope.launch {
            runCatching {
                val body = payload.take(MAX_MESSAGE_CHARS)
                    .toRequestBody("text/plain; charset=utf-8".toMediaType())
                val request = Request.Builder()
                    .url("$BASE/$TOPIC")
                    .header("Title", "ClosePaw hands-free debug")
                    .post(body)
                    .build()
                client.newCall(request).execute().use { response ->
                    if (!response.isSuccessful) {
                        throw IllegalStateException("ntfy HTTP ${response.code}")
                    }
                }
            }
        }
    }

    private fun sanitize(raw: String): String = raw
        .replace(Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/-]+=*"), "Bearer <redacted>")
        .replace(Regex("sk-[A-Za-z0-9_-]{12,}"), "sk-<redacted>")
        .replace(Regex("(?i)api[_ -]?key\\s*[:=]\\s*[^, }]+"), "api_key=<redacted>")
        .take(MAX_MESSAGE_CHARS)
}
