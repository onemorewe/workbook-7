from pathlib import Path

root = Path(".")
voice_dir = root / "app/src/main/kotlin/ai/closepaw/ui/capsule/voice"
voice_dir.mkdir(parents=True, exist_ok=True)

(voice_dir / "VoiceTranscriptionSettings.kt").write_text(r'''package ai.closepaw.ui.capsule.voice

import android.content.Context

object VoiceTranscriptionSettings {
    private const val PREFS_NAME = "voice_transcription_prefs"
    private const val KEY_MODEL = "voice_transcription_model"

    const val SYSTEM = "system"
    const val GPT_TRANSCRIBE = "gpt-transcribe"
    const val GPT_4O_TRANSCRIBE = "gpt-4o-transcribe"
    const val GPT_4O_MINI_TRANSCRIBE = "gpt-4o-mini-transcribe"
    const val DEFAULT_MODEL = GPT_TRANSCRIBE

    val modelOptions: List<Pair<String, String>> = listOf(
        GPT_TRANSCRIBE to "GPT Transcribe (recommended)",
        GPT_4O_TRANSCRIBE to "GPT-4o Transcribe",
        GPT_4O_MINI_TRANSCRIBE to "GPT-4o Mini Transcribe",
        SYSTEM to "Android system speech",
    )

    private val allowed = modelOptions.map { it.first }.toSet()

    fun load(context: Context): String {
        val value = context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .getString(KEY_MODEL, DEFAULT_MODEL)
            .orEmpty()
        return value.takeIf { it in allowed } ?: DEFAULT_MODEL
    }

    fun save(context: Context, model: String) {
        val safeModel = model.takeIf { it in allowed } ?: DEFAULT_MODEL
        context.applicationContext
            .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY_MODEL, safeModel)
            .apply()
    }
}
''', encoding="utf-8")

(voice_dir / "ConfigurableRecognizerFactory.kt").write_text(r'''package ai.closepaw.ui.capsule.voice

import android.content.Context
import ai.closepaw.app.AuthStoreHolder
import ai.closepaw.llm.LLMProvider

class ConfigurableRecognizerFactory(context: Context) : RecognizerFactory {
    private val appContext = context.applicationContext
    private val systemFactory = AndroidRecognizerFactory(appContext)

    override fun isAvailable(): Boolean {
        val model = VoiceTranscriptionSettings.load(appContext)
        if (model == VoiceTranscriptionSettings.SYSTEM) return systemFactory.isAvailable()
        return openAiApiKeyOrNull() != null || systemFactory.isAvailable()
    }

    override fun create(): Recognizer? {
        val model = VoiceTranscriptionSettings.load(appContext)
        if (model == VoiceTranscriptionSettings.SYSTEM) return systemFactory.create()

        val apiKey = openAiApiKeyOrNull() ?: return systemFactory.create()
        return OpenAIRecognizer(appContext, apiKey, model)
    }

    private fun openAiApiKeyOrNull(): String? = runCatching {
        AuthStoreHolder.get(appContext).requireApiKey(LLMProvider.OPENAI_API)
    }.getOrNull()?.takeIf { it.isNotBlank() }
}
''', encoding="utf-8")

(voice_dir / "OpenAIRecognizer.kt").write_text(r'''package ai.closepaw.ui.capsule.voice

import android.content.Context
import android.media.MediaRecorder
import android.os.Handler
import android.os.Looper
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
import kotlinx.coroutines.launch
import org.json.JSONObject

internal class OpenAIRecognizer(
    context: Context,
    private val apiKey: String,
    private val model: String,
) : Recognizer {
    private val appContext = context.applicationContext
    private val mainHandler = Handler(Looper.getMainLooper())
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private var callbacks: RecognizerCallbacks? = null
    private var recorder: MediaRecorder? = null
    private var audioFile: File? = null
    private var transcribeJob: Job? = null
    private var cancelled = false
    private var terminalDelivered = false

    override fun start(languageTag: String, callbacks: RecognizerCallbacks) {
        this.callbacks = callbacks
        cancelled = false
        terminalDelivered = false
        try {
            val file = File.createTempFile("closepaw_voice_", ".m4a", appContext.cacheDir)
            audioFile = file
            @Suppress("DEPRECATION")
            val newRecorder = if (android.os.Build.VERSION.SDK_INT >= 31) {
                MediaRecorder(appContext)
            } else {
                MediaRecorder()
            }
            recorder = newRecorder.apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioSamplingRate(16_000)
                setAudioEncodingBitRate(64_000)
                setOutputFile(file.absolutePath)
                prepare()
                start()
            }
        } catch (_: Throwable) {
            releaseRecorder(stopFirst = false)
            deliverError(VoiceError.Unknown)
        }
    }

    override fun stop() {
        if (cancelled || terminalDelivered) return
        val file = audioFile ?: run {
            deliverError(VoiceError.Unknown)
            return
        }
        try {
            releaseRecorder(stopFirst = true)
        } catch (_: Throwable) {
            deleteAudioFile()
            deliverError(VoiceError.NoMatch)
            return
        }

        transcribeJob = scope.launch {
            try {
                deliverFinal(transcribe(file).trim())
            } catch (_: IOException) {
                deliverError(VoiceError.Network)
            } catch (_: Throwable) {
                deliverError(VoiceError.Unknown)
            } finally {
                deleteAudioFile()
            }
        }
    }

    override fun cancel() {
        cancelled = true
        transcribeJob?.cancel()
        transcribeJob = null
        runCatching { releaseRecorder(stopFirst = true) }
        deleteAudioFile()
    }

    override fun destroy() {
        cancelled = true
        transcribeJob?.cancel()
        transcribeJob = null
        runCatching { releaseRecorder(stopFirst = false) }
        deleteAudioFile()
        callbacks = null
        scope.cancel()
    }

    private fun releaseRecorder(stopFirst: Boolean) {
        val current = recorder ?: return
        recorder = null
        try {
            if (stopFirst) current.stop()
        } finally {
            runCatching { current.reset() }
            current.release()
        }
    }

    private fun deleteAudioFile() {
        audioFile?.let { runCatching { it.delete() } }
        audioFile = null
    }

    private fun deliverFinal(text: String) {
        mainHandler.post {
            if (cancelled || terminalDelivered) return@post
            terminalDelivered = true
            callbacks?.onFinal(text)
        }
    }

    private fun deliverError(error: VoiceError) {
        mainHandler.post {
            if (cancelled || terminalDelivered) return@post
            terminalDelivered = true
            callbacks?.onError(error)
        }
    }

    private fun transcribe(file: File): String {
        val boundary = "----ClosePaw-${UUID.randomUUID()}"
        val connection = (URL("https://api.openai.com/v1/audio/transcriptions").openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 15_000
            readTimeout = 60_000
            doOutput = true
            setRequestProperty("Authorization", "Bearer $apiKey")
            setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")
            setRequestProperty("Accept", "application/json")
        }

        try {
            DataOutputStream(BufferedOutputStream(connection.outputStream)).use { out ->
                writeTextPart(out, boundary, "model", model)
                writeTextPart(
                    out,
                    boundary,
                    "prompt",
                    "The speaker may use Russian, English, or switch between them. Preserve the original spoken language, technical terms, app names, song titles, and code identifiers.",
                )
                out.write("--$boundary\r\n".toByteArray(StandardCharsets.UTF_8))
                out.write("Content-Disposition: form-data; name=\"file\"; filename=\"speech.m4a\"\r\n".toByteArray(StandardCharsets.UTF_8))
                out.write("Content-Type: audio/mp4\r\n\r\n".toByteArray(StandardCharsets.UTF_8))
                file.inputStream().use { input -> input.copyTo(out) }
                out.write("\r\n--$boundary--\r\n".toByteArray(StandardCharsets.UTF_8))
                out.flush()
            }

            val status = connection.responseCode
            val body = (if (status in 200..299) connection.inputStream else connection.errorStream)
                ?.bufferedReader(StandardCharsets.UTF_8)
                ?.use { it.readText() }
                .orEmpty()
            if (status !in 200..299) throw IOException("OpenAI transcription failed: HTTP $status")
            return JSONObject(body).optString("text", "")
        } finally {
            connection.disconnect()
        }
    }

    private fun writeTextPart(out: DataOutputStream, boundary: String, name: String, value: String) {
        out.write("--$boundary\r\n".toByteArray(StandardCharsets.UTF_8))
        out.write("Content-Disposition: form-data; name=\"$name\"\r\n".toByteArray(StandardCharsets.UTF_8))
        out.write("Content-Type: text/plain; charset=utf-8\r\n\r\n".toByteArray(StandardCharsets.UTF_8))
        out.write(value.toByteArray(StandardCharsets.UTF_8))
        out.write("\r\n".toByteArray(StandardCharsets.UTF_8))
    }
}
''', encoding="utf-8")

replacements = {
    "app/src/main/kotlin/ai/closepaw/ui/chat/ChatScreen.kt": [
        ("import ai.closepaw.ui.capsule.voice.AndroidRecognizerFactory", "import ai.closepaw.ui.capsule.voice.ConfigurableRecognizerFactory"),
        ("override val factory = AndroidRecognizerFactory(ctx.applicationContext)", "override val factory = ConfigurableRecognizerFactory(ctx.applicationContext)"),
    ],
    "app/src/main/kotlin/ai/closepaw/ui/overlay/compose/CapsuleOverlayHost.kt": [
        ("import ai.closepaw.ui.capsule.voice.AndroidRecognizerFactory", "import ai.closepaw.ui.capsule.voice.ConfigurableRecognizerFactory"),
        ("override val factory = AndroidRecognizerFactory(appCtx)", "override val factory = ConfigurableRecognizerFactory(appCtx)"),
    ],
    "app/src/main/kotlin/ai/closepaw/ui/settings/LlmAuthSettingsPage.kt": [
        ("import ai.closepaw.ui.theme.Fleuron", "import ai.closepaw.ui.capsule.voice.VoiceTranscriptionSettings\nimport ai.closepaw.ui.theme.Fleuron"),
    ],
}

for rel, reps in replacements.items():
    p = root / rel
    text = p.read_text(encoding="utf-8")
    for old, new in reps:
        if old not in text:
            raise SystemExit(f"Patch anchor not found in {rel}: {old!r}")
        text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")

settings = root / "app/src/main/kotlin/ai/closepaw/ui/settings/LlmAuthSettingsPage.kt"
text = settings.read_text(encoding="utf-8")
anchor = '''    // Auto-flip rule: when the user is in the OTHER sub-tab and all three fields
'''
insert = '''    if (selectedProvider == LLMProvider.OPENAI_API) {
        Spacer(modifier = Modifier.height(20.dp))
        val voiceContext = LocalContext.current
        var voiceModel by remember { mutableStateOf(VoiceTranscriptionSettings.load(voiceContext)) }
        SettingsSection(title = "Voice Recognition") {
            CloudModelDropdown(
                selectedModel = voiceModel,
                modelOptions = VoiceTranscriptionSettings.modelOptions,
                onModelChange = { selected ->
                    voiceModel = selected
                    VoiceTranscriptionSettings.save(voiceContext, selected)
                },
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = if (voiceModel == VoiceTranscriptionSettings.SYSTEM) {
                    "Uses Android's built-in speech recognizer."
                } else {
                    "Language: Auto — Russian, English, and mixed speech. Uses the OpenAI API key above; without an API key ClosePaw falls back to Android speech."
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Spacer(modifier = Modifier.height(20.dp))
    }

'''
if anchor not in text:
    raise SystemExit("Settings insertion anchor not found")
text = text.replace(anchor, insert + anchor, 1)
settings.write_text(text, encoding="utf-8")
print("GPT voice patch applied")
