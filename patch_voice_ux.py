from pathlib import Path

root = Path('.')
voice_dir = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice'


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:90]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')

# Replace OpenAI manual push-to-stop recognizer with one-tap silence auto-stop.
(voice_dir / 'OpenAIRecognizer.kt').write_text(r'''package ai.closepaw.ui.capsule.voice

import android.content.Context
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import java.io.BufferedOutputStream
import java.io.DataOutputStream
import java.io.File
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL
import java.nio.charset.StandardCharsets
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import org.json.JSONObject

internal class OpenAIRecognizer(
    context: Context,
    private val apiKey: String,
    private val model: String,
) : Recognizer {
    private val appContext = context.applicationContext
    private val main = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var callbacks: RecognizerCallbacks? = null
    private var recorder: MediaRecorder? = null
    private var file: File? = null
    private var job: Job? = null
    private var silenceJob: Job? = null
    @Volatile private var cancelled = false
    @Volatile private var done = false
    @Volatile private var stopping = false

    override fun start(languageTag: String, callbacks: RecognizerCallbacks) {
        this.callbacks = callbacks
        cancelled = false; done = false; stopping = false
        try {
            val out = File.createTempFile("closepaw_voice_", ".m4a", appContext.cacheDir)
            file = out
            @Suppress("DEPRECATION")
            val r = if (android.os.Build.VERSION.SDK_INT >= 31) MediaRecorder(appContext) else MediaRecorder()
            recorder = r.apply {
                setAudioSource(MediaRecorder.AudioSource.VOICE_RECOGNITION)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioSamplingRate(16_000)
                setAudioEncodingBitRate(64_000)
                setOutputFile(out.absolutePath)
                prepare(); start()
            }
            monitorSilence()
        } catch (_: Throwable) {
            release(false); error(VoiceError.Unknown)
        }
    }

    private fun monitorSilence() {
        silenceJob = scope.launch(Dispatchers.Default) {
            delay(250)
            val began = SystemClock.elapsedRealtime()
            var floor = 500.0
            var heardSpeech = false
            var silenceSince = 0L
            while (isActive && !cancelled && !stopping) {
                delay(80)
                val now = SystemClock.elapsedRealtime()
                val amp = runCatching { recorder?.maxAmplitude ?: 0 }.getOrDefault(0).toDouble()
                val threshold = maxOf(1000.0, floor * 2.8)
                if (!heardSpeech) {
                    if (amp > threshold) heardSpeech = true else floor = floor * 0.92 + amp * 0.08
                    if (now - began > 10_000L) { main.post { stop() }; break }
                } else if (amp > threshold * 0.85) {
                    silenceSince = 0L
                } else if (silenceSince == 0L) {
                    silenceSince = now
                } else if (now - silenceSince >= 1100L) {
                    main.post { stop() }; break
                }
            }
        }
    }

    override fun stop() {
        if (cancelled || done || stopping) return
        stopping = true
        silenceJob?.cancel(); silenceJob = null
        val audio = file ?: run { error(VoiceError.Unknown); return }
        try { release(true) } catch (_: Throwable) { delete(); error(VoiceError.NoMatch); return }
        job = scope.launch {
            try { finish(transcribe(audio).trim()) }
            catch (e: OpenAIVoiceHttpException) {
                val mapped = mapOpenAiVoiceHttpStatus(e.status)
                HandsFreeDebugRelay.publish(
                    stage = "voice-http-error",
                    level = "error",
                    message = "OpenAI voice HTTP ${e.status}",
                    metadata = mapOf("http_status" to e.status, "mapped_error" to mapped.name),
                )
                error(mapped)
            }
            catch (_: IOException) {
                HandsFreeDebugRelay.publish(
                    stage = "voice-network-error",
                    level = "error",
                    message = "OpenAI voice network I/O failure",
                )
                error(VoiceError.Network)
            }
            catch (_: Throwable) {
                HandsFreeDebugRelay.publish(
                    stage = "voice-runtime-error",
                    level = "error",
                    message = "OpenAI voice unexpected runtime failure",
                )
                error(VoiceError.Unknown)
            }
            finally { delete() }
        }
    }

    override fun cancel() {
        cancelled = true; stopping = true
        silenceJob?.cancel(); job?.cancel(); runCatching { release(true) }; delete()
    }
    override fun destroy() {
        cancelled = true; stopping = true
        silenceJob?.cancel(); job?.cancel(); runCatching { release(false) }; delete(); callbacks = null; scope.cancel()
    }
    private fun release(stop: Boolean) {
        val r = recorder ?: return; recorder = null
        try { if (stop) r.stop() } finally { runCatching { r.reset() }; r.release() }
    }
    private fun delete() { file?.let { runCatching { it.delete() } }; file = null }
    private fun finish(text: String) = main.post { if (!cancelled && !done) { done = true; callbacks?.onFinal(text) } }
    private fun error(e: VoiceError) = main.post { if (!cancelled && !done) { done = true; callbacks?.onError(e) } }

    private fun transcribe(audio: File): String {
        val boundary = "----ClosePaw-${UUID.randomUUID()}"
        val c = (URL("https://api.openai.com/v1/audio/transcriptions").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"; connectTimeout = 15_000; readTimeout = 60_000; doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            setRequestProperty("Accept", "application/json")
        }
        try {
            DataOutputStream(BufferedOutputStream(c.outputStream)).use { out ->
                fun part(name: String, value: String) {
                    out.write("--$boundary\r\nContent-Disposition: form-data; name=\"$name\"\r\n\r\n$value\r\n".toByteArray(StandardCharsets.UTF_8))
                }
                part("model", model)
                part("prompt", "Speaker may use Russian, English, or mix them. Preserve app names, song titles, names, and technical terms.")
                out.write("--$boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"speech.m4a\"\r\nContent-Type: audio/mp4\r\n\r\n".toByteArray(StandardCharsets.UTF_8))
                audio.inputStream().use { it.copyTo(out) }
                out.write("\r\n--$boundary--\r\n".toByteArray(StandardCharsets.UTF_8)); out.flush()
            }
            val status = c.responseCode
            val body = (if (status in 200..299) c.inputStream else c.errorStream)?.bufferedReader()?.use { it.readText() }.orEmpty()
            if (status !in 200..299) throw OpenAIVoiceHttpException(status)
            return JSONObject(body).optString("text", "")
        } finally { c.disconnect() }
    }
}

internal class OpenAIVoiceHttpException(val status: Int) : IOException("HTTP $status")

internal fun mapOpenAiVoiceHttpStatus(status: Int): VoiceError = when (status) {
    401, 403 -> VoiceError.ApiAuth
    429 -> VoiceError.ApiRateLimit
    else -> VoiceError.ApiRequest
}
''', encoding='utf-8')

# Distinguish actual connectivity from HTTP/auth/rate/model failures. Previously every non-2xx
# response became VoiceError.Network and the UI incorrectly told the user that internet was needed.
recognizer = voice_dir / 'Recognizer.kt'
replace_once(
    recognizer,
    '    NetworkTimeout,\n    LanguageUnavailable,\n',
    '    NetworkTimeout,\n    ApiAuth,\n    ApiRateLimit,\n    ApiRequest,\n    LanguageUnavailable,\n',
)
controller = voice_dir / 'VoiceInputController.kt'
replace_once(
    controller,
    '''        VoiceError.Network, VoiceError.NetworkTimeout -> {
            onText(baseText)
            onToast("Voice needs network for this language")
            VoiceState.Idle
        }
''',
    '''        VoiceError.Network, VoiceError.NetworkTimeout -> {
            onText(baseText)
            onToast("Voice network connection failed")
            VoiceState.Idle
        }
        VoiceError.ApiAuth -> {
            onText(baseText)
            onToast("OpenAI voice authentication failed — check API key")
            VoiceState.Idle
        }
        VoiceError.ApiRateLimit -> {
            onText(baseText)
            onToast("OpenAI voice limit reached (HTTP 429)")
            VoiceState.Idle
        }
        VoiceError.ApiRequest -> {
            onText(baseText)
            onToast("OpenAI voice request failed")
            VoiceState.Idle
        }
''',
)

test_dir = root / 'app/src/test/kotlin/ai/closepaw/ui/capsule/voice'
test_dir.mkdir(parents=True, exist_ok=True)
(test_dir / 'VoiceHttpErrorMappingTest.kt').write_text(r'''package ai.closepaw.ui.capsule.voice

import kotlin.test.Test
import kotlin.test.assertEquals

class VoiceHttpErrorMappingTest {
    @Test fun authErrorsAreAuth() {
        assertEquals(VoiceError.ApiAuth, mapOpenAiVoiceHttpStatus(401))
        assertEquals(VoiceError.ApiAuth, mapOpenAiVoiceHttpStatus(403))
    }

    @Test fun rateLimitIsRateLimit() {
        assertEquals(VoiceError.ApiRateLimit, mapOpenAiVoiceHttpStatus(429))
    }

    @Test fun modelAndServerErrorsAreApiRequests() {
        assertEquals(VoiceError.ApiRequest, mapOpenAiVoiceHttpStatus(400))
        assertEquals(VoiceError.ApiRequest, mapOpenAiVoiceHttpStatus(500))
    }
}
''', encoding='utf-8')

# When voice final text arrives and controller returns Idle, submit it automatically.
bar = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/surface/CapsuleInputBar.kt'
replace_once(bar, '    val controllerLastText = remember { mutableStateOf("") }\n', '    val controllerLastText = remember { mutableStateOf("") }\n    var voiceAutoSubmitArmed by remember { mutableStateOf(false) }\n    var voiceProducedText by remember { mutableStateOf(false) }\n')
replace_once(bar, '                inputText = newText\n            },\n', '                inputText = newText\n                voiceProducedText = newText.isNotBlank()\n            },\n')
replace_once(bar, '    val reducedMotion = ClosePawMotion.reducedMotion()\n', '''    LaunchedEffect(voiceState, voiceAutoSubmitArmed, voiceProducedText) {
        if (voiceState == VoiceState.Idle && voiceAutoSubmitArmed) {
            voiceAutoSubmitArmed = false
            if (voiceProducedText) {
                val finalText = inputText.trim()
                if (finalText.isNotEmpty()) {
                    onSubmit(finalText)
                    inputText = ""
                }
            }
            voiceProducedText = false
        }
    }

    val reducedMotion = ClosePawMotion.reducedMotion()
''')
replace_once(bar, '        val v = voice ?: return@mic\n', '        val v = voice ?: return@mic\n        voiceAutoSubmitArmed = true\n        voiceProducedText = false\n')

print('Voice UX patch applied')
