package ai.closepaw.ui.settings

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import ai.closepaw.app.AgentService
import ai.closepaw.app.AuthStoreHolder
import ai.closepaw.llm.AuthMode
import ai.closepaw.llm.LLMProvider
import ai.closepaw.llm.ModelCatalog
import ai.closepaw.ui.capsule.voice.HandsFreeVoiceService
import ai.closepaw.ui.capsule.voice.VoiceTranscriptionSettings
import ai.closepaw.ui.theme.Fleuron
import ai.closepaw.ui.theme.PageMastheadDrillDown
import ai.closepaw.ui.theme.closePaw
import org.json.JSONObject

@Composable
internal fun VoiceRuntimeSettingsPage(
    selectedModel: String,
    modelCatalog: ModelCatalog,
    onBack: () -> Unit,
    onClose: () -> Unit,
) {
    val context = LocalContext.current
    var voiceModel by remember { mutableStateOf(VoiceTranscriptionSettings.load(context)) }
    val runtimeStatus by HandsFreeVoiceService.runtimeStatus.collectAsState()
    val lastError by HandsFreeVoiceService.lastError.collectAsState()
    val handsFreeEnabled = HandsFreeVoiceService.isEnabled(context)
    val authStore = remember(context) { runCatching { AuthStoreHolder.get(context.applicationContext) }.getOrNull() }

    val openAiKeyConnected = remember(context, runtimeStatus, voiceModel) {
        runCatching { authStore?.has(LLMProvider.OPENAI_API) == true }.getOrDefault(false)
    }
    val microphoneGranted = ContextCompat.checkSelfPermission(
        context,
        Manifest.permission.RECORD_AUDIO,
    ) == PackageManager.PERMISSION_GRANTED

    val activeSessionModel = AgentService.instance
        ?.getActiveSession()
        ?.effectiveMainModel()
    val effectiveAgentModel = activeSessionModel ?: selectedModel
    val agentEntry = modelCatalog.resolveOrNull(effectiveAgentModel)
    val agentProvider = agentEntry?.provider
    val agentCredentialPresent = remember(agentProvider, runtimeStatus) {
        when (agentProvider?.mode) {
            AuthMode.Local -> true
            null -> false
            else -> runCatching { authStore?.has(agentProvider) == true }.getOrDefault(false)
        }
    }
    val oauthMirror = when (agentProvider) {
        LLMProvider.OPENAI_CODEX -> agentEntry
        LLMProvider.OPENAI_API -> agentEntry?.let { entry ->
            modelCatalog.modelsFor(LLMProvider.OPENAI_CODEX)
                .firstOrNull { it.modelId == entry.modelId }
        }
        else -> null
    }
    val oauthConnected = remember(oauthMirror?.name, runtimeStatus) {
        oauthMirror != null && runCatching {
            authStore?.has(LLMProvider.OPENAI_CODEX) == true
        }.getOrDefault(false)
    }

    val normalMicEffective = when {
        voiceModel == VoiceTranscriptionSettings.SYSTEM -> "Android system speech"
        openAiKeyConnected -> "$voiceModel · OpenAI API"
        else -> "Android system speech · fallback (OpenAI key missing)"
    }

    val wakeWord = remember(context) { readWakeWordLabel(context) }
    val ttsEngine = remember(context) {
        Settings.Secure.getString(context.contentResolver, "tts_default_synth")
            ?.takeIf { it.isNotBlank() }
            ?: "Android default TTS"
    }

    var localStartError by remember { mutableStateOf<String?>(null) }
    val micPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        localStartError = if (granted) {
            HandsFreeVoiceService.setEnabled(context, true)
        } else {
            "Microphone permission denied"
        }
    }

    Column(modifier = Modifier.fillMaxWidth()) {
        PageMastheadDrillDown(title = "Voice & Runtime", onBack = onBack, onClose = onClose)
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = MaterialTheme.closePaw.spacing.lg),
            verticalArrangement = Arrangement.spacedBy(MaterialTheme.closePaw.spacing.md),
        ) {
            SettingsSection(title = "Agent reasoning") {
                RuntimeCard(
                    title = effectiveAgentModel,
                    lines = listOf(
                        if (activeSessionModel != null) "Active session model" else "Configured model (no active session)",
                        authDescription(agentProvider, agentCredentialPresent),
                    ),
                )
            }

            SettingsSection(title = "Normal microphone") {
                RuntimeCard(
                    title = normalMicEffective,
                    lines = listOf(
                        "Configured: $voiceModel",
                        "Microphone permission: ${if (microphoneGranted) "granted" else "missing"}",
                    ),
                )
                Spacer(modifier = Modifier.height(10.dp))
                CloudModelDropdown(
                    selectedModel = voiceModel,
                    modelOptions = VoiceTranscriptionSettings.modelOptions,
                    onModelChange = { selected ->
                        voiceModel = selected
                        VoiceTranscriptionSettings.save(context, selected)
                    },
                )
            }

            SettingsSection(title = "Hands-free") {
                val gateReady = when (agentProvider) {
                    LLMProvider.OPENAI_CODEX -> oauthConnected && openAiKeyConnected
                    LLMProvider.OPENAI_API -> openAiKeyConnected
                    else -> false
                }
                val gateDescription = when {
                    !gateReady -> "unavailable with current agent auth"
                    agentProvider == LLMProvider.OPENAI_API && oauthConnected && oauthMirror != null ->
                        "${oauthMirror.name} · ChatGPT subscription → $effectiveAgentModel · API fallback on usage limit"
                    agentProvider == LLMProvider.OPENAI_API -> "$effectiveAgentModel · OpenAI API"
                    else -> "$effectiveAgentModel · ChatGPT subscription · API fallback on usage limit"
                }
                RuntimeCard(
                    title = if (handsFreeEnabled) "ON" else "OFF",
                    lines = listOf(
                        "Runtime: $runtimeStatus",
                        "Wake: microWakeWord · $wakeWord · local only",
                        "Live STT: gpt-live-transcribe · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",
                        "Intent gate: $gateDescription",
                        "Answer voice: Android TTS · $ttsEngine · language auto RU/EN",
                    ),
                )
                val error = localStartError ?: lastError
                if (!error.isNullOrBlank()) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Last error: $error",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
                Spacer(modifier = Modifier.height(10.dp))
                Button(
                    onClick = {
                        localStartError = null
                        if (HandsFreeVoiceService.isEnabled(context)) {
                            HandsFreeVoiceService.setEnabled(context, false)
                        } else if (!microphoneGranted) {
                            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                        } else {
                            localStartError = HandsFreeVoiceService.setEnabled(context, true)
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(if (handsFreeEnabled) "Turn off hands-free" else "Turn on hands-free")
                }
            }

            Fleuron()
            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@Composable
private fun RuntimeCard(title: String, lines: List<String>) {
    Surface(
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = MaterialTheme.shapes.medium,
    ) {
        Column(
            modifier = Modifier.padding(MaterialTheme.closePaw.spacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            lines.forEach { line ->
                Text(
                    text = line,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
}

private fun authDescription(provider: LLMProvider?, credentialPresent: Boolean): String = when (provider?.mode) {
    AuthMode.OAuth -> if (credentialPresent) "ChatGPT subscription · OAuth connected" else "ChatGPT subscription · signed out"
    AuthMode.ApiKey -> if (credentialPresent) "API billing · key connected" else "API billing · key missing"
    AuthMode.Local -> "On-device model"
    null -> "Unknown provider"
}

private fun readWakeWordLabel(context: Context): String = runCatching {
    val raw = context.assets.open("wake_word.json").bufferedReader().use { it.readText() }
    JSONObject(raw).optString("wake_word").takeIf { it.isNotBlank() }
}.getOrNull() ?: "unknown wake word"
