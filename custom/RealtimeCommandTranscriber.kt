package ai.closepaw.ui.capsule.voice

import android.util.Base64
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.ArrayDeque
import java.util.LinkedHashMap
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/** Pure constants shared by production code and fast JVM contract tests. */
internal object HandsFreeRealtimeContract {
    const val TRANSCRIPTION_MODEL = "gpt-transcribe"
    const val TURN_DETECTION_TYPE = "server_vad"
    const val SAMPLE_RATE = 24_000
    const val VAD_THRESHOLD = 0.5
    const val PREFIX_PADDING_MS = 300
    const val SILENCE_DURATION_MS = 600
}

/**
 * One Realtime transcription socket for one wake-word command session.
 *
 * Audio is 24 kHz mono PCM16. OpenAI server VAD chunks speech and commits a user item. A completed
 * transcription is itself proof that the VAD turn was committed, so delivery does not depend on a
 * second speech_stopped event arriving in a particular order.
 */
internal class RealtimeCommandTranscriber(
    private val apiKey: String,
    private val listener: Listener,
) : AutoCloseable {
    interface Listener {
        fun onConnected()
        fun onSpeechStarted(itemId: String)
        fun onSpeechStopped(itemId: String)
        fun onLiveTranscript(text: String)
        fun onTurnReady(itemId: String, cumulativeTranscript: String)
        fun onError(message: String)
    }

    companion object {
        private const val URL = "wss://api.openai.com/v1/realtime?intent=transcription"
        private const val MAX_PENDING_FRAMES = 125 // roughly 2.5 s at 20 ms/frame
    }

    private val client = OkHttpClient.Builder().build()
    private val lock = Any()
    private val pending = ArrayDeque<ByteArray>()
    private val turnOrder = mutableListOf<String>()
    private val partials = LinkedHashMap<String, StringBuilder>()
    private val finals = LinkedHashMap<String, String>()
    private val delivered = mutableSetOf<String>()

    @Volatile private var socket: WebSocket? = null
    @Volatile private var opened = false
    @Volatile private var closed = false

    fun start() {
        if (socket != null || closed) return
        val request = Request.Builder()
            .url(URL)
            .header("Authorization", "Bearer $apiKey")
            .build()
        socket = client.newWebSocket(request, WsListener())
    }

    fun appendPcm24k(samples: ShortArray, length: Int = samples.size) {
        if (closed || length <= 0) return
        val bytes = ByteBuffer.allocate(length * 2).order(ByteOrder.LITTLE_ENDIAN).apply {
            for (i in 0 until length) putShort(samples[i])
        }.array()
        val ws = socket
        if (opened && ws != null) {
            sendAudio(ws, bytes)
        } else {
            synchronized(lock) {
                if (pending.size >= MAX_PENDING_FRAMES) pending.removeFirst()
                pending.addLast(bytes)
            }
        }
    }

    private fun configure(ws: WebSocket) {
        // gpt-live-transcribe rejects turn detection on the deployed API. Hands-free needs
        // automatic speech boundaries, so use gpt-transcribe: it supports Realtime transcription
        // over WebSocket and pairs with server_vad for automatic commit boundaries.
        val transcription = JSONObject()
            .put("model", HandsFreeRealtimeContract.TRANSCRIPTION_MODEL)
        val turnDetection = JSONObject()
            .put("type", HandsFreeRealtimeContract.TURN_DETECTION_TYPE)
            .put("threshold", HandsFreeRealtimeContract.VAD_THRESHOLD)
            .put("prefix_padding_ms", HandsFreeRealtimeContract.PREFIX_PADDING_MS)
            .put("silence_duration_ms", HandsFreeRealtimeContract.SILENCE_DURATION_MS)
        val input = JSONObject()
            .put(
                "format",
                JSONObject()
                    .put("type", "audio/pcm")
                    .put("rate", HandsFreeRealtimeContract.SAMPLE_RATE),
            )
            .put("transcription", transcription)
            .put("turn_detection", turnDetection)
        val session = JSONObject()
            .put("type", "transcription")
            .put("audio", JSONObject().put("input", input))
        ws.send(JSONObject().put("type", "session.update").put("session", session).toString())
    }

    private fun sendAudio(ws: WebSocket, bytes: ByteArray) {
        val b64 = Base64.encodeToString(bytes, Base64.NO_WRAP)
        ws.send(JSONObject().put("type", "input_audio_buffer.append").put("audio", b64).toString())
    }

    private fun flushPending(ws: WebSocket) {
        val frames = synchronized(lock) {
            buildList {
                while (pending.isNotEmpty()) add(pending.removeFirst())
            }
        }
        frames.forEach { sendAudio(ws, it) }
    }

    private inner class WsListener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (closed) {
                webSocket.close(1000, "closed")
                return
            }
            configure(webSocket)
            opened = true
            flushPending(webSocket)
            listener.onConnected()
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            handleServerEvent(text)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            if (!closed) listener.onError(t.message ?: "Realtime connection failed")
        }
    }

    /** Shared parser used by the live socket and Android instrumentation tests. */
    internal fun handleServerEventForTest(text: String) {
        handleServerEvent(text)
    }

    private fun handleServerEvent(text: String) {
        if (closed) return
        val event = runCatching { JSONObject(text) }.getOrNull() ?: return
        when (event.optString("type")) {
            "input_audio_buffer.speech_started" -> {
                val id = event.optString("item_id")
                if (id.isNotBlank()) {
                    synchronized(lock) { ensureTurn(id) }
                    listener.onSpeechStarted(id)
                }
            }
            "input_audio_buffer.speech_stopped" -> {
                val id = event.optString("item_id")
                if (id.isNotBlank()) {
                    synchronized(lock) { ensureTurn(id) }
                    listener.onSpeechStopped(id)
                }
            }
            "input_audio_buffer.committed" -> {
                val id = event.optString("item_id")
                if (id.isNotBlank()) synchronized(lock) { ensureTurn(id) }
            }
            "conversation.item.input_audio_transcription.delta" -> {
                val id = event.optString("item_id")
                val delta = event.optString("delta")
                if (id.isNotBlank() && delta.isNotEmpty()) {
                    val live = synchronized(lock) {
                        ensureTurn(id)
                        partials.getOrPut(id) { StringBuilder() }.append(delta)
                        composeTranscriptLocked()
                    }
                    listener.onLiveTranscript(live)
                }
            }
            "conversation.item.input_audio_transcription.completed" -> {
                val id = event.optString("item_id")
                val transcript = event.optString("transcript").trim()
                if (id.isNotBlank()) {
                    val live = synchronized(lock) {
                        ensureTurn(id)
                        finals[id] = transcript
                        partials.remove(id)
                        composeTranscriptLocked()
                    }
                    listener.onLiveTranscript(live)
                    maybeDeliver(id)
                }
            }
            "conversation.item.input_audio_transcription.failed" -> {
                val error = event.optJSONObject("error")
                val msg = error?.optString("message")?.takeIf { it.isNotBlank() }
                    ?: "Realtime transcription failed"
                listener.onError(msg)
            }
            "error" -> {
                val error = event.optJSONObject("error")
                val msg = error?.optString("message")?.takeIf { it.isNotBlank() }
                    ?: event.toString().take(300)
                listener.onError(msg)
            }
        }
    }

    private fun maybeDeliver(itemId: String) {
        val payload = synchronized(lock) {
            if (itemId !in finals || itemId in delivered) return@synchronized null
            delivered.add(itemId)
            composeTranscriptLocked()
        }
        if (!payload.isNullOrBlank()) listener.onTurnReady(itemId, payload)
    }

    private fun ensureTurn(id: String) {
        if (id !in turnOrder) turnOrder.add(id)
    }

    private fun composeTranscriptLocked(): String = buildString {
        turnOrder.forEach { id ->
            val text = finals[id] ?: partials[id]?.toString().orEmpty()
            if (text.isNotBlank()) {
                if (isNotEmpty()) append(' ')
                append(text.trim())
            }
        }
    }.trim()

    override fun close() {
        if (closed) return
        closed = true
        opened = false
        synchronized(lock) { pending.clear() }
        socket?.close(1000, "command complete")
        socket = null
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }
}
