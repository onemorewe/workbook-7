package ai.closepaw.ui.capsule.voice

import android.Manifest
import android.annotation.SuppressLint
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.ToneGenerator
import android.os.IBinder
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat
import ai.closepaw.R
import ai.closepaw.app.AgentService
import ai.closepaw.app.AuthStoreHolder
import ai.closepaw.app.MainActivity
import ai.closepaw.llm.LLMProvider
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.charset.StandardCharsets
import java.util.ArrayDeque
import java.util.UUID
import kotlin.math.sqrt
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

/**
 * Opt-in driving mode. Audio stays local until VAD finds a speech-sized segment; that segment is
 * sent to the configured OpenAI transcription model. Only transcripts beginning with “Алёша” are
 * routed to the agent. Saying just “Алёша” arms the next utterance for eight seconds.
 */
class HandsFreeVoiceService : Service() {
    companion object {
        private const val CHANNEL_ID = "closepaw_hands_free"
        private const val NOTIFICATION_ID = 8042
        private const val ACTION_START = "ai.closepaw.voice.START_HANDS_FREE"
        private const val ACTION_STOP = "ai.closepaw.voice.STOP_HANDS_FREE"
        private const val SAMPLE_RATE = 16_000
        private const val FRAME_SAMPLES = 320
        private const val SILENCE_MS = 1_100L
        private const val MAX_UTTERANCE_MS = 15_000L
        private const val ARMED_MS = 8_000L
        private const val PREFS = "voice_transcription_prefs"
        private const val KEY_ENABLED = "hands_free_enabled"

        fun isEnabled(context: Context): Boolean =
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(KEY_ENABLED, false)

        fun setEnabled(context: Context, enabled: Boolean) {
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putBoolean(KEY_ENABLED, enabled).apply()
            val intent = Intent(context, HandsFreeVoiceService::class.java).apply {
                action = if (enabled) ACTION_START else ACTION_STOP
            }
            if (enabled) ContextCompat.startForegroundService(context, intent)
            else context.stopService(intent)
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val segments = Channel<ShortArray>(
        capacity = 2,
        onBufferOverflow = BufferOverflow.DROP_OLDEST,
    )
    private var listenJob: Job? = null
    private var workerJob: Job? = null
    private var recorder: AudioRecord? = null
    @Volatile private var armedUntil: Long = 0L

    override fun onCreate() {
        super.onCreate()
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL_ID, "ClosePaw hands-free", NotificationManager.IMPORTANCE_LOW)
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP || !isEnabled(this)) {
            stopSelf()
            return START_NOT_STICKY
        }
        startForeground(NOTIFICATION_ID, notification("Алёша • слушаю"))
        if (listenJob == null) startListening()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        listenJob?.cancel()
        workerJob?.cancel()
        runCatching { recorder?.stop() }
        recorder?.release()
        recorder = null
        segments.close()
        scope.cancel()
        super.onDestroy()
    }

    private fun startListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            failAndDisable("Нужен доступ к микрофону")
            return
        }
        if (apiKeyOrNull() == null) {
            failAndDisable("Добавь OpenAI API key")
            return
        }

        workerJob = scope.launch {
            for (samples in segments) processSegment(samples)
        }
        listenJob = scope.launch {
            val audio = createRecorder() ?: run {
                failAndDisable("Микрофон недоступен")
                return@launch
            }
            recorder = audio
            audio.startRecording()

            val frame = ShortArray(FRAME_SAMPLES)
            val preRoll = ArrayDeque<ShortArray>()
            val utterance = mutableListOf<ShortArray>()
            var speaking = false
            var floor = 250.0
            var hotFrames = 0
            var speechStart = 0L
            var lastVoice = 0L

            while (isActive) {
                val read = audio.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                if (read <= 0) continue
                val copy = frame.copyOf(read)
                val level = rms(copy)
                val now = SystemClock.elapsedRealtime()
                val threshold = maxOf(700.0, floor * 3.2)

                if (!speaking) {
                    preRoll.addLast(copy)
                    while (preRoll.size > 25) preRoll.removeFirst()
                    if (level > threshold) hotFrames++ else hotFrames = 0
                    if (level < threshold) floor = floor * 0.985 + level * 0.015
                    if (hotFrames >= 3) {
                        speaking = true
                        speechStart = now
                        lastVoice = now
                        utterance.clear()
                        preRoll.forEach { utterance.add(it) }
                        preRoll.clear()
                        hotFrames = 0
                    }
                } else {
                    utterance.add(copy)
                    if (level > threshold * 0.82) lastVoice = now
                    if (now - lastVoice >= SILENCE_MS || now - speechStart >= MAX_UTTERANCE_MS) {
                        val joined = join(utterance)
                        if (joined.size >= SAMPLE_RATE / 3) segments.trySend(joined)
                        utterance.clear()
                        preRoll.clear()
                        speaking = false
                    }
                }
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun createRecorder(): AudioRecord? {
        val min = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )
        val r = AudioRecord.Builder()
            .setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                    .setSampleRate(SAMPLE_RATE)
                    .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                    .build()
            )
            .setBufferSizeInBytes(maxOf(min.coerceAtLeast(0), FRAME_SAMPLES * 16))
            .build()
        return if (r.state == AudioRecord.STATE_INITIALIZED) r else {
            r.release()
            null
        }
    }

    private fun processSegment(samples: ShortArray) {
        val key = apiKeyOrNull() ?: return
        val model = selectedSpeechModel()
        val wav = writeWav(samples)
        try {
            val transcript = transcribe(wav, key, model).trim()
            if (transcript.isBlank()) return
            val now = SystemClock.elapsedRealtime()
            val parsed = HandsFreeCommandParser.parse(transcript, armed = now < armedUntil)
            if (!parsed.wakeDetected) return

            val command = parsed.command
            if (command.isNullOrBlank()) {
                armedUntil = now + ARMED_MS
                beep()
                updateNotification("Алёша • слушаю команду…")
                return
            }

            armedUntil = 0L
            beep()
            updateNotification("Алёша → ${command.take(70)}")
            val agent = AgentService.instance
            if (agent == null) updateNotification("Алёша услышала • включи Accessibility")
            else agent.submitHandsFreeCommand(command)
        } catch (_: Throwable) {
            updateNotification("Алёша • ошибка распознавания, продолжаю слушать")
        } finally {
            runCatching { wav.delete() }
        }
    }

    private fun apiKeyOrNull(): String? = runCatching {
        AuthStoreHolder.get(this).requireApiKey(LLMProvider.OPENAI_API)
    }.getOrNull()?.takeIf { it.isNotBlank() }

    private fun selectedSpeechModel(): String {
        val model = getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getString("voice_transcription_model", "gpt-transcribe")
            .orEmpty()
        return if (model == "system" || model.isBlank()) "gpt-transcribe" else model
    }

    private fun transcribe(file: File, apiKey: String, model: String): String {
        val boundary = "----ClosePaw-${UUID.randomUUID()}"
        val c = (URL("https://api.openai.com/v1/audio/transcriptions").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
        }
        try {
            DataOutputStream(BufferedOutputStream(c.outputStream)).use { out ->
                writePart(out, boundary, "model", model)
                writePart(out, boundary, "prompt", "Wake word is Алёша (Алеша/Alyosha). Speaker may mix Russian and English. Preserve app names and song titles.")
                out.write("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.wav\"\r\nContent-Type: audio/wav\r\n\r\n".toByteArray(StandardCharsets.UTF_8))
                file.inputStream().use { it.copyTo(out) }
                out.write("\r\n--$boundary--\r\n".toByteArray(StandardCharsets.UTF_8))
            }
            val status = c.responseCode
            val body = (if (status in 200..299) c.inputStream else c.errorStream)
                ?.bufferedReader(StandardCharsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (status !in 200..299) error("HTTP $status")
            return JSONObject(body).optString("text", "")
        } finally {
            c.disconnect()
        }
    }

    private fun writePart(out: DataOutputStream, boundary: String, name: String, value: String) {
        out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray(StandardCharsets.UTF_8))
    }

    private fun writeWav(samples: ShortArray): File {
        val file = File.createTempFile("closepaw_handsfree_", ".wav", cacheDir)
        val dataSize = samples.size * 2
        FileOutputStream(file).use { out ->
            out.write("RIFF".toByteArray())
            out.write(leInt(36 + dataSize))
            out.write("WAVEfmt ".toByteArray())
            out.write(leInt(16)); out.write(leShort(1)); out.write(leShort(1))
            out.write(leInt(SAMPLE_RATE)); out.write(leInt(SAMPLE_RATE * 2))
            out.write(leShort(2)); out.write(leShort(16))
            out.write("data".toByteArray()); out.write(leInt(dataSize))
            val data = ByteBuffer.allocate(dataSize).order(ByteOrder.LITTLE_ENDIAN)
            samples.forEach { data.putShort(it) }
            out.write(data.array())
        }
        return file
    }

    private fun rms(samples: ShortArray): Double {
        if (samples.isEmpty()) return 0.0
        var sum = 0.0
        samples.forEach { val v = it.toDouble(); sum += v * v }
        return sqrt(sum / samples.size)
    }

    private fun join(frames: List<ShortArray>): ShortArray {
        val out = ShortArray(frames.sumOf { it.size })
        var offset = 0
        frames.forEach { frame -> frame.copyInto(out, offset); offset += frame.size }
        return out
    }

    private fun leInt(v: Int): ByteArray = ByteBuffer.allocate(4).order(ByteOrder.LITTLE_ENDIAN).putInt(v).array()
    private fun leShort(v: Int): ByteArray = ByteBuffer.allocate(2).order(ByteOrder.LITTLE_ENDIAN).putShort(v.toShort()).array()

    private fun beep() {
        runCatching {
            val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 55)
            tone.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
            Thread.sleep(140)
            tone.release()
        }
    }

    private fun notification(text: String): android.app.Notification {
        val pending = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("ClosePaw hands-free")
            .setContentText(text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setContentIntent(pending)
            .build()
    }

    private fun updateNotification(text: String) {
        getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification(text))
    }

    private fun failAndDisable(message: String) {
        getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(KEY_ENABLED, false).apply()
        updateNotification("Алёша выключена • $message")
        stopSelf()
    }
}
