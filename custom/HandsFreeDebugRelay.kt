package ai.closepaw.ui.capsule.voice

import android.content.Context
import java.util.UUID
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong
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
 * Remote structured trace relay for the hands-free prototype.
 *
 * During migration we dual-write to the private Supabase ingest endpoint when a build-time
 * device credential has been provisioned, while retaining the pinned ntfy stream as a temporary
 * fallback. The write credential is intentionally not committed to the public repository.
 */
internal object HandsFreeDebugRelay {
    private const val PRIVATE_INGEST_URL =
        "https://qglsnnnshefwnrzsbeko.supabase.co/functions/v1/trace-ingest"
    private const val PRIVATE_WRITE_TOKEN = "__TRACE_WRITE_TOKEN__"

    private const val NTFY_BASE = "https://ntfy.sh"
    private const val NTFY_TOPIC = "closepaw-hf-7ff9c7fb0ec9b03ae896c1af451e26826e2eff8fa63824fd"
    private const val MAX_MESSAGE_CHARS = 3_500

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val client = OkHttpClient.Builder()
        .callTimeout(5, TimeUnit.SECONDS)
        .build()
    private val sequence = AtomicLong(0)

    @Volatile private var enabled = false
    @Volatile private var appVersion: String? = null
    @Volatile private var relaySessionId: String = UUID.randomUUID().toString()

    fun configure(context: Context) {
        val appContext = context.applicationContext
        appVersion = runCatching {
            appContext.packageManager.getPackageInfo(appContext.packageName, 0).versionName
        }.getOrNull()
        relaySessionId = UUID.randomUUID().toString()
        sequence.set(0)
        enabled = true
        publish("relay", "debug relay online")
    }

    fun disable() {
        enabled = false
    }

    fun readUrl(context: Context): String {
        @Suppress("UNUSED_VARIABLE") val appContext = context.applicationContext
        return "$NTFY_BASE/$NTFY_TOPIC/json?poll=1&since=12h"
    }

    fun publish(stage: String, message: String) {
        if (!enabled) return
        val cleanStage = stage.take(80)
        val cleanMessage = sanitize(message)
        val eventId = UUID.randomUUID().toString()
        val seq = sequence.incrementAndGet()

        val privatePayload = JSONObject()
            .put("event_id", eventId)
            .put("ts", System.currentTimeMillis())
            .put("app_version", appVersion)
            .put("session_id", relaySessionId)
            .put("seq", seq)
            .put("stage", cleanStage)
            .put("level", if (cleanStage == "error") "error" else "info")
            .put("message", cleanMessage)
            .put("metadata", JSONObject().put("source", "hands-free-android"))
            .toString()

        val ntfyPayload = JSONObject()
            .put("event_id", eventId)
            .put("ts", System.currentTimeMillis())
            .put("session_id", relaySessionId)
            .put("seq", seq)
            .put("stage", cleanStage)
            .put("message", cleanMessage)
            .toString()

        post(privatePayload, ntfyPayload)
    }

    fun publishTraceLine(line: String) {
        publish("trace", line)
    }

    private fun post(privatePayload: String, ntfyPayload: String) {
        scope.launch {
            if (privateCredentialProvisioned()) {
                runCatching { postPrivate(privatePayload) }
            }
            // Keep ntfy as a temporary fallback until a real Samsung event is visible in private DB.
            runCatching { postNtfy(ntfyPayload) }
        }
    }

    private fun privateCredentialProvisioned(): Boolean =
        PRIVATE_WRITE_TOKEN.isNotBlank() && !PRIVATE_WRITE_TOKEN.startsWith("__")

    private fun postPrivate(payload: String) {
        val body = payload.toRequestBody("application/json; charset=utf-8".toMediaType())
        val request = Request.Builder()
            .url(PRIVATE_INGEST_URL)
            .header("Authorization", "Bearer $PRIVATE_WRITE_TOKEN")
            .post(body)
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("private trace HTTP ${response.code}")
            }
        }
    }

    private fun postNtfy(payload: String) {
        val body = payload.take(MAX_MESSAGE_CHARS)
            .toRequestBody("text/plain; charset=utf-8".toMediaType())
        val request = Request.Builder()
            .url("$NTFY_BASE/$NTFY_TOPIC")
            .header("Title", "ClosePaw hands-free debug")
            .post(body)
            .build()
        client.newCall(request).execute().use { response ->
            if (!response.isSuccessful) {
                throw IllegalStateException("ntfy HTTP ${response.code}")
            }
        }
    }

    private fun sanitize(raw: String): String = raw
        .replace(Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/-]+=*"), "Bearer <redacted>")
        .replace(Regex("sk-[A-Za-z0-9_-]{12,}"), "sk-<redacted>")
        .replace(Regex("(?i)(?:sb_secret_|sb_publishable_|ghp_|github_pat_)[A-Za-z0-9_-]{8,}"), "<redacted>")
        .replace(Regex("(?i)api[_ -]?key\\s*[:=]\\s*[^, }]+"), "api_key=<redacted>")
        .replace(Regex("(?i)(?:access|refresh|id|device|write|read)[_ -]?token\\s*[:=]\\s*[^, }]+"), "token=<redacted>")
        .take(MAX_MESSAGE_CHARS)
}
