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
import android.media.AudioAttributes
import android.media.AudioFocusRequest
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
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicLong
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Opt-in driving mode.
 *
 * Idle path is fully local: 24 kHz microphone frames are fed only to [LocalWakeWordDetector].
 * Nothing is uploaded before “Алёша” is recognized.
 *
 * After wake, one OpenAI Realtime transcription socket is opened. Server VAD supplies pause
 * events; at each completed pause the cumulative transcript is checked by the selected
 * ChatGPT/Codex subscription model. The gate returns either NOT_READY or the normalized intent.
 * The Realtime socket is closed before that intent is handed to the normal ClosePaw agent, so
 * music or other audio produced by the action is never left streaming to transcription.
 */
class HandsFreeVoiceService : Service() {
    companion object {
        private const val CHANNEL_ID = "closepaw_hands_free"
        private const val NOTIFICATION_ID = 8042
        private const val ACTION_START = "ai.closepaw.voice.START_HANDS_FREE"
        private const val ACTION_STOP = "ai.closepaw.voice.STOP_HANDS_FREE"
        private const val SAMPLE_RATE = 24_000
        private const val FRAME_SAMPLES = 480 // 20 ms
        private const val PREFS = "voice_transcription_prefs"
        private const val KEY_ENABLED = "hands_free_enabled"
        private const val COMMAND_SAFETY_TIMEOUT_MS = 5 * 60_000L

        private val _liveTranscript = MutableStateFlow("")
        val liveTranscript: StateFlow<String> = _liveTranscript.asStateFlow()

        private val _commandSessionActive = MutableStateFlow(false)
        val commandSessionActive: StateFlow<Boolean> = _commandSessionActive.asStateFlow()

        fun isEnabled(context: Context): Boolean =
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getBoolean(KEY_ENABLED, false)

        fun setEnabled(context: Context, enabled: Boolean) {
            context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit().putBoolean(KEY_ENABLED, enabled).apply()
            if (!enabled) {
                _commandSessionActive.value = false
                _liveTranscript.value = ""
            }
            val intent = Intent(context, HandsFreeVoiceService::class.java).apply {
                action = if (enabled) ACTION_START else ACTION_STOP
            }
            if (enabled) ContextCompat.startForegroundService(context, intent)
            else context.stopService(intent)
        }
    }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var listenJob: Job? = null
    private var gateJob: Job? = null
    private var recorder: AudioRecord? = null
    private var wakeDetector: LocalWakeWordDetector? = null
    private var intentGate: HandsFreeIntentGate? = null

    @Volatile private var realtime: RealtimeCommandTranscriber? = null
    @Volatile private var commandStartedAt: Long = 0L
    private val commandSerial = AtomicLong(0L)
    private val speechGeneration = AtomicLong(0L)
    private val stoppedGeneration = ConcurrentHashMap<String, Long>()

    private var audioFocusRequest: AudioFocusRequest? = null

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
        startForeground(NOTIFICATION_ID, notification("Алёша • запускаю локальное распознавание…"))
        if (listenJob == null) startListening()
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        gateJob?.cancel()
        listenJob?.cancel()
        closeCommand(clearTranscript = true)
        runCatching { recorder?.stop() }
        recorder?.release()
        recorder = null
        wakeDetector?.close()
        wakeDetector = null
        val gate = intentGate
        intentGate = null
        if (gate != null) {
            scope.launch { runCatching { gate.cleanup() } }
        }
        _commandSessionActive.value = false
        _liveTranscript.value = ""
        scope.cancel()
        super.onDestroy()
    }

    private fun startListening() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            failAndDisable("Нужен доступ к микрофону")
            return
        }
        val apiKey = apiKeyOrNull()
        if (apiKey == null) {
            failAndDisable("Добавь OpenAI API key для live transcription")
            return
        }

        val detector = LocalWakeWordDetector(this)
        wakeDetector = detector
        intentGate = HandsFreeIntentGate(this)

        listenJob = scope.launch {
            updateNotification("Алёша • готовлю локальную wake-модель…")
            val wakeInit = detector.initialize()
            if (wakeInit.isFailure) {
                failAndDisable("Не удалось загрузить локальную wake-модель")
                return@launch
            }

            val audio = createRecorder() ?: run {
                failAndDisable("Микрофон недоступен")
                return@launch
            }
            recorder = audio
            audio.startRecording()
            updateNotification("Алёша • локально слушаю")

            val frame = ShortArray(FRAME_SAMPLES)
            while (isActive) {
                val read = audio.read(frame, 0, frame.size, AudioRecord.READ_BLOCKING)
                if (read <= 0) continue

                val command = realtime
                if (command == null) {
                    if (detector.accept24k(frame, read)) {
                        beginCommand(apiKey)
                    }
                } else {
                    command.appendPcm24k(frame, read)
                    val started = commandStartedAt
                    if (started > 0L && SystemClock.elapsedRealtime() - started > COMMAND_SAFETY_TIMEOUT_MS) {
                        abortCommand("Сессия слишком долго открыта • скажи «Алёша» ещё раз")
                    }
                }
            }
        }
    }

    private fun beginCommand(apiKey: String) {
        if (realtime != null) return
        gateJob?.cancel()
        stoppedGeneration.clear()
        speechGeneration.incrementAndGet()
        val serial = commandSerial.incrementAndGet()
        commandStartedAt = SystemClock.elapsedRealtime()
        _liveTranscript.value = ""
        _commandSessionActive.value = true
        requestTransientAudioFocus()
        beep()
        updateNotification("Алёша • подключаю live transcription…")

        val session = RealtimeCommandTranscriber(
            apiKey = apiKey,
            listener = object : RealtimeCommandTranscriber.Listener {
                override fun onConnected() {
                    if (!isCurrent(serial)) return
                    updateNotification("Алёша • слушаю команду…")
                }

                override fun onSpeechStarted(itemId: String) {
                    if (!isCurrent(serial)) return
                    speechGeneration.incrementAndGet()
                    gateJob?.cancel()
                    updateNotification("Алёша • слушаю…")
                }

                override fun onSpeechStopped(itemId: String) {
                    if (!isCurrent(serial)) return
                    stoppedGeneration[itemId] = speechGeneration.get()
                    updateNotification("Алёша • пауза, проверяю intent…")
                }

                override fun onLiveTranscript(text: String) {
                    if (!isCurrent(serial)) return
                    _liveTranscript.value = text
                }

                override fun onTurnReady(itemId: String, cumulativeTranscript: String) {
                    if (!isCurrent(serial)) return
                    val generation = stoppedGeneration.remove(itemId) ?: speechGeneration.get()
                    if (generation != speechGeneration.get()) return
                    evaluateIntent(serial, generation, cumulativeTranscript)
                }

                override fun onError(message: String) {
                    if (!isCurrent(serial)) return
                    abortCommand("Live transcription error • ${message.take(80)}")
                }
            },
        )
        realtime = session
        session.start()
    }

    private fun evaluateIntent(serial: Long, generation: Long, transcript: String) {
        gateJob?.cancel()
        val gate = intentGate ?: return
        gateJob = scope.launch {
            val result = gate.classify(transcript)
            if (!isCurrent(serial) || generation != speechGeneration.get()) return@launch

            result.fold(
                onSuccess = { intent ->
                    if (intent.isNullOrBlank()) {
                        updateNotification("Алёша • intent ещё не готов, слушаю дальше…")
                    } else {
                        // Critical ordering: stop cloud audio BEFORE the command can start music/TTS.
                        closeCommand(clearTranscript = false)
                        _liveTranscript.value = intent
                        updateNotification("Алёша → ${intent.take(80)}")
                        val agent = AgentService.instance
                        if (agent == null) {
                            updateNotification("Алёша услышала • включи Accessibility")
                        } else {
                            agent.submitHandsFreeCommand(intent)
                        }
                        scope.launch {
                            delay(2_500L)
                            if (realtime == null) _liveTranscript.value = ""
                        }
                    }
                },
                onFailure = { error ->
                    // Do not silently fall back to API billing: this gate is intentionally OAuth-only.
                    abortCommand("Intent gate error • ${error.message?.take(80) ?: "проверь ChatGPT sign-in"}")
                },
            )
        }
    }

    private fun isCurrent(serial: Long): Boolean =
        serial == commandSerial.get() && realtime != null

    private fun abortCommand(message: String) {
        closeCommand(clearTranscript = false)
        updateNotification("Алёша • $message")
        scope.launch {
            delay(2_500L)
            if (realtime == null) {
                _liveTranscript.value = ""
                updateNotification("Алёша • локально слушаю")
            }
        }
    }

    private fun closeCommand(clearTranscript: Boolean) {
        gateJob?.cancel()
        gateJob = null
        val old = realtime
        realtime = null
        commandStartedAt = 0L
        stoppedGeneration.clear()
        _commandSessionActive.value = false
        old?.close()
        abandonTransientAudioFocus()
        wakeDetector?.reset()
        if (clearTranscript) _liveTranscript.value = ""
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
            .setBufferSizeInBytes(maxOf(min.coerceAtLeast(0), FRAME_SAMPLES * 2 * 8))
            .build()
        return if (r.state == AudioRecord.STATE_INITIALIZED) r else {
            r.release()
            null
        }
    }

    private fun apiKeyOrNull(): String? = runCatching {
        AuthStoreHolder.get(this).requireApiKey(LLMProvider.OPENAI_API)
    }.getOrNull()?.takeIf { it.isNotBlank() }

    private fun requestTransientAudioFocus() {
        runCatching {
            val manager = getSystemService(AudioManager::class.java)
            val request = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT)
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANCE_ACCESSIBILITY)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setOnAudioFocusChangeListener { }
                .build()
            audioFocusRequest = request
            manager.requestAudioFocus(request)
        }
    }

    private fun abandonTransientAudioFocus() {
        val request = audioFocusRequest ?: return
        audioFocusRequest = null
        runCatching { getSystemService(AudioManager::class.java).abandonAudioFocusRequest(request) }
    }

    private fun beep() {
        scope.launch {
            runCatching {
                val tone = ToneGenerator(AudioManager.STREAM_NOTIFICATION, 55)
                tone.startTone(ToneGenerator.TONE_PROP_BEEP, 120)
                delay(140L)
                tone.release()
            }
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
        _commandSessionActive.value = false
        _liveTranscript.value = ""
        updateNotification("Алёша выключена • $message")
        stopSelf()
    }
}
