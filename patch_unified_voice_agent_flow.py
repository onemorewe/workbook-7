from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Unified-flow anchor not found in {path}: {old[:180]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# ---------------------------------------------------------------------------
# 1. One transcription selection for normal mic + Jarvis.
# ---------------------------------------------------------------------------
voice_settings = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/VoiceTranscriptionSettings.kt'
replace_once(
    voice_settings,
    '''    val modelOptions: List<Pair<String, String>> = listOf(
        GPT_TRANSCRIBE to "GPT Transcribe (recommended)",
        GPT_4O_TRANSCRIBE to "GPT-4o Transcribe",
        GPT_4O_MINI_TRANSCRIBE to "GPT-4o Mini Transcribe",
        SYSTEM to "Android system speech",
    )
''',
    '''    // This is the single user-facing transcription selector for both the normal mic button
    // and Jarvis after the local wake word. Android speech remains an automatic normal-mic
    // fallback when the API key is unavailable, but it is not a separate configured mode because
    // Jarvis Realtime cannot consume Android SpeechRecognizer's private audio stream.
    val modelOptions: List<Pair<String, String>> = listOf(
        GPT_TRANSCRIBE to "GPT Transcribe (recommended)",
        GPT_4O_TRANSCRIBE to "GPT-4o Transcribe",
        GPT_4O_MINI_TRANSCRIBE to "GPT-4o Mini Transcribe",
    )
''',
)

realtime = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/RealtimeCommandTranscriber.kt'
replace_once(
    realtime,
    '''internal class RealtimeCommandTranscriber(
    private val apiKey: String,
    private val listener: Listener,
) : AutoCloseable {
''',
    '''internal class RealtimeCommandTranscriber(
    private val apiKey: String,
    private val listener: Listener,
    private val transcriptionModel: String = HandsFreeRealtimeContract.TRANSCRIPTION_MODEL,
) : AutoCloseable {
''',
)
replace_once(
    realtime,
    '''        val transcription = JSONObject()
            .put("model", HandsFreeRealtimeContract.TRANSCRIPTION_MODEL)
''',
    '''        val transcription = JSONObject()
            .put("model", transcriptionModel)
''',
)

service = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
replace_once(
    service,
    '''        val session = RealtimeCommandTranscriber(
            apiKey = apiKey,
            listener = object : RealtimeCommandTranscriber.Listener {
''',
    '''        val session = RealtimeCommandTranscriber(
            apiKey = apiKey,
            listener = object : RealtimeCommandTranscriber.Listener {
''',
)
# Named trailing argument is inserted after the listener object closes so existing listener body is untouched.
replace_once(
    service,
    '''            },
        )
        realtime = session
''',
    '''            },
            transcriptionModel = VoiceTranscriptionSettings.load(this@HandsFreeVoiceService),
        )
        realtime = session
''',
)

# ---------------------------------------------------------------------------
# 2. Intent gate stays. It belongs to the Jarvis input adapter, but it no longer controls which
#    model executes the accepted command. Agent execution always follows normal app settings.
# ---------------------------------------------------------------------------
gate = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeIntentGate.kt'
g = gate.read_text(encoding='utf-8')
g = g.replace(
    ''' * Hands-free routing is intentionally independent from the ordinary agent auth selector:
 * - if a ChatGPT/Codex OAuth mirror exists and OAuth is connected, use it first;
 * - fall back to the matching OpenAI API model only on a real rate/usage limit;
 * - if the user explicitly selected an OpenAI API model and no usable OAuth mirror exists,
 *   use that API model directly.
 *
 * The model used by the gate is also exposed to AgentService so execution follows the same route.
''',
    ''' * This gate is part of the Jarvis INPUT adapter only. It decides NOT_READY vs a normalized
 * user intent. Once accepted, execution is handed to the exact same AgentSession path/settings as
 * keyboard or normal-microphone input. The gate prefers ChatGPT OAuth and may use OpenAI API only
 * as its own small fallback; that routing never changes the configured agent provider/model.
''',
    1,
)
# Remove stale coupling assignments. They are intentionally not replaced with another execution route.
g = '\n'.join(line for line in g.split('\n') if 'activeExecutionModel =' not in line)
g = g.replace(
    '''        @Volatile private var activeExecutionModel: String? = null

        /** Model the next hands-free AgentSession must use to match the successful intent route. */
        fun activeExecutionModel(): String? = activeExecutionModel

''',
    '',
    1,
)
# If the line-filter removed the declaration before the exact block, clean the remaining comment/method too.
g = g.replace(
    '''        /** Model the next hands-free AgentSession must use to match the successful intent route. */
        fun activeExecutionModel(): String? = activeExecutionModel

''',
    '',
    1,
)
gate.write_text(g, encoding='utf-8')

# Make gate model resolution independent from the configured execution provider. Prefer a connected
# OAuth reasoning route; use the selected model's OpenAI mirror when possible, otherwise the first
# available OpenAI gate model. This allows e.g. an OpenRouter/local agent without changing Jarvis UX.
g = gate.read_text(encoding='utf-8')
start = g.find('    private fun resolveRoute(catalog: ModelCatalog, selected: String): Route {')
end = g.find('\n    private suspend fun clientFor', start)
if start < 0 or end < 0:
    raise SystemExit('Could not bound HandsFreeIntentGate.resolveRoute')
new_resolver = '''    private fun resolveRoute(catalog: ModelCatalog, selected: String): Route {
        val selectedEntry = catalog.resolveOrNull(selected)
        val auth = AuthStoreHolder.get(appContext)

        val selectedOpenAi = selectedEntry?.takeIf {
            it.provider == LLMProvider.OPENAI_CODEX || it.provider == LLMProvider.OPENAI_API
        }
        val oauthEntry = when (selectedOpenAi?.provider) {
            LLMProvider.OPENAI_CODEX -> selectedOpenAi
            LLMProvider.OPENAI_API -> catalog.modelsFor(LLMProvider.OPENAI_CODEX)
                .firstOrNull { it.modelId == selectedOpenAi.modelId }
            else -> catalog.modelsFor(LLMProvider.OPENAI_CODEX).firstOrNull()
        }
        val apiEntry = when (selectedOpenAi?.provider) {
            LLMProvider.OPENAI_API -> selectedOpenAi
            LLMProvider.OPENAI_CODEX -> catalog.modelsFor(LLMProvider.OPENAI_API)
                .firstOrNull { it.modelId == selectedOpenAi.modelId }
                ?: catalog.modelsFor(LLMProvider.OPENAI_API).firstOrNull()
            else -> {
                val matching = oauthEntry?.let { oauth ->
                    catalog.modelsFor(LLMProvider.OPENAI_API).firstOrNull { it.modelId == oauth.modelId }
                }
                matching ?: catalog.modelsFor(LLMProvider.OPENAI_API).firstOrNull()
            }
        }

        val oauthReady = oauthEntry != null && runCatching {
            auth.has(LLMProvider.OPENAI_CODEX)
        }.getOrDefault(false)
        val apiReady = apiEntry != null && runCatching {
            auth.has(LLMProvider.OPENAI_API)
        }.getOrDefault(false)

        if (oauthReady) {
            return Route(
                primaryModel = oauthEntry!!.name,
                primaryProvider = LLMProvider.OPENAI_CODEX,
                apiFallbackModel = apiEntry?.takeIf { apiReady }?.name,
            )
        }
        if (apiReady) {
            return Route(
                primaryModel = apiEntry!!.name,
                primaryProvider = LLMProvider.OPENAI_API,
                apiFallbackModel = null,
            )
        }
        throw IllegalStateException(
            "Jarvis intent gate needs ChatGPT sign-in or an OpenAI API key; agent execution settings are separate."
        )
    }
'''
gate.write_text(g[:start] + new_resolver + g[end:], encoding='utf-8')

# Assert AgentService is not secretly coupled to the intent-gate model. Jarvis may normalize input,
# but accepted text must enter the ordinary AgentService path exactly like any other user command.
agent_service = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
a = agent_service.read_text(encoding='utf-8')
if 'HandsFreeIntentGate.activeExecutionModel' in a:
    raise SystemExit('AgentService still couples hands-free execution to intent-gate model')
if 'fun submitHandsFreeCommand(text: String)' not in a:
    raise SystemExit('Hands-free command adapter missing from AgentService')

# ---------------------------------------------------------------------------
# 3. Dedicated board: separate Transcription and Agent selectors. API agent choice is explicit and
#    requires a cost confirmation. No hidden OAuth rerouting after the user chooses API.
# ---------------------------------------------------------------------------
panel = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/VoiceRuntimeSettingsPage.kt'
p = panel.read_text(encoding='utf-8')
p = p.replace('import androidx.compose.material3.Button\n', 'import androidx.compose.material3.AlertDialog\nimport androidx.compose.material3.Button\n', 1)
p = p.replace('import androidx.compose.material3.Text\n', 'import androidx.compose.material3.Text\nimport androidx.compose.material3.TextButton\n', 1)
p = p.replace(
    '''    selectedModel: String,
    modelCatalog: ModelCatalog,
    onBack: () -> Unit,
''',
    '''    selectedModel: String,
    modelCatalog: ModelCatalog,
    onAgentModelChange: (String) -> Unit,
    onBack: () -> Unit,
''',
    1,
)
# Insert configured selector state after authStore.
p = p.replace(
    '''    val authStore = remember(context) { runCatching { AuthStoreHolder.get(context.applicationContext) }.getOrNull() }
''',
    '''    val authStore = remember(context) { runCatching { AuthStoreHolder.get(context.applicationContext) }.getOrNull() }
    var pendingPaidAgentModel by remember { mutableStateOf<String?>(null) }
    val configuredAgentEntry = modelCatalog.resolveOrNull(selectedModel)
    val agentOptions = remember(modelCatalog) {
        modelCatalog.all()
            .filter { it.provider != LLMProvider.LOCAL_LFM }
            .map { entry ->
                val route = when (entry.provider.mode) {
                    AuthMode.OAuth -> "ChatGPT subscription"
                    AuthMode.ApiKey -> "API billing"
                    AuthMode.Local -> "On-device"
                }
                entry.name to "${entry.displayName} · $route"
            }
    }
''',
    1,
)
# Replace Agent reasoning section with selector + explicit cost state.
old_agent = '''            SettingsSection(title = "Agent reasoning") {
                RuntimeCard(
                    title = effectiveAgentModel,
                    lines = listOf(
                        if (activeSessionModel != null) "Active session model" else "Configured model (no active session)",
                        authDescription(agentProvider, agentCredentialPresent),
                    ),
                )
            }
'''
new_agent = '''            SettingsSection(title = "Agent") {
                RuntimeCard(
                    title = effectiveAgentModel,
                    lines = listOf(
                        if (activeSessionModel != null) "Active session model · current session stays pinned" else "No active session",
                        "Configured for new sessions: $selectedModel",
                        authDescription(agentProvider, agentCredentialPresent),
                    ),
                )
                Spacer(modifier = Modifier.height(10.dp))
                CloudModelDropdown(
                    selectedModel = selectedModel,
                    modelOptions = agentOptions,
                    onModelChange = { candidate ->
                        val candidateEntry = modelCatalog.resolveOrNull(candidate)
                        if (candidateEntry?.provider?.mode == AuthMode.ApiKey && candidate != selectedModel) {
                            pendingPaidAgentModel = candidate
                        } else {
                            onAgentModelChange(candidate)
                        }
                    },
                )
                if (configuredAgentEntry?.provider?.mode == AuthMode.ApiKey) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "PAID API AGENT: separate from ChatGPT Plus. GUI-agent turns can resend screen state, tools and history repeatedly; costs can grow quickly.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
'''
if old_agent not in p:
    raise SystemExit('Agent reasoning section anchor missing')
p = p.replace(old_agent, new_agent, 1)

p = p.replace('SettingsSection(title = "Normal microphone") {', 'SettingsSection(title = "Transcription · normal mic + Jarvis") {', 1)
p = p.replace(
    '''                        "Configured: $voiceModel",
                        "Microphone permission: ${if (microphoneGranted) "granted" else "missing"}",
''',
    '''                        "Shared STT model: $voiceModel",
                        "Microphone permission: ${if (microphoneGranted) "granted" else "missing"}",
                        "Normal mic falls back to Android speech if the OpenAI key is unavailable",
''',
    1,
)
p = p.replace(
    '''                        "Live STT: ${HandsFreeRealtimeContract.TRANSCRIPTION_MODEL} · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",
''',
    '''                        "STT: $voiceModel · shared with normal microphone · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",
''',
    1,
)
p = p.replace(
    '''                        "Intent gate: $gateDescription",
''',
    '''                        "Intent gate: $gateDescription · input normalization only",
                        "Execution: normal Agent pipeline · configured Agent selector above",
''',
    1,
)

# Add paid-provider confirmation dialog after the main panel content.
end_anchor = '''        }
    }
}

@Composable
private fun RuntimeCard'''
if end_anchor not in p:
    raise SystemExit('VoiceRuntimeSettingsPage end anchor missing')
dialog = '''        }
    }

    pendingPaidAgentModel?.let { candidate ->
        val candidateEntry = modelCatalog.resolveOrNull(candidate)
        val isOpenAiApi = candidateEntry?.provider == LLMProvider.OPENAI_API
        AlertDialog(
            onDismissRequest = { pendingPaidAgentModel = null },
            title = { Text("Use a paid API for the agent?") },
            text = {
                Text(
                    if (isOpenAiApi) {
                        "This is billed separately from ChatGPT Plus. A GUI agent may make multiple reasoning turns and repeatedly send screen state, tool schemas and history. That can become expensive. A safety fuse blocks direct OpenAI API prompts above ~32k estimated input tokens, but smaller repeated calls are still billable."
                    } else {
                        "This provider uses separate API billing. Agent tasks can make multiple model calls and resend context, so usage may cost substantially more than transcription."
                    }
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    pendingPaidAgentModel = null
                    onAgentModelChange(candidate)
                }) { Text("Use paid API") }
            },
            dismissButton = {
                TextButton(onClick = { pendingPaidAgentModel = null }) { Text("Cancel") }
            },
        )
    }
}

@Composable
private fun RuntimeCard'''
p = p.replace(end_anchor, dialog, 1)
panel.write_text(p, encoding='utf-8')

# SettingsSheet already owns the canonical onModelChange callback; wire it into this dedicated page.
sheet = root / 'app/src/main/kotlin/ai/closepaw/ui/settings/SettingsSheet.kt'
replace_once(
    sheet,
    '''                    SettingsPage.VOICE_RUNTIME -> VoiceRuntimeSettingsPage(
                        selectedModel = selectedModel,
                        modelCatalog = modelCatalog,
''',
    '''                    SettingsPage.VOICE_RUNTIME -> VoiceRuntimeSettingsPage(
                        selectedModel = selectedModel,
                        modelCatalog = modelCatalog,
                        onAgentModelChange = onModelChange,
''',
)

# ---------------------------------------------------------------------------
# 4. Hands-free preflight only checks INPUT requirements (mic + STT + intent gate availability).
#    It must never reject Jarvis because the configured execution agent uses another provider.
# ---------------------------------------------------------------------------
service = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
s = service.read_text(encoding='utf-8')
start = s.find('            val selected = runCatching { AppSettingsStore(context).load().selectedModel }')
end = s.find('            return null\n        }', start)
if start < 0 or end < 0:
    raise SystemExit('Could not bound hands-free preflight agent-auth block')
end += len('            return null\n')
replacement = '''            val catalog = runCatching {
                ModelCatalogRepositoryHolder.get(context).catalog.value
            }.getOrNull() ?: return "Could not read the model catalog for the Jarvis intent gate"
            val oauthGateReady = catalog.modelsFor(LLMProvider.OPENAI_CODEX).isNotEmpty() &&
                runCatching { auth.has(LLMProvider.OPENAI_CODEX) }.getOrDefault(false)
            val apiGateReady = catalog.modelsFor(LLMProvider.OPENAI_API).isNotEmpty() &&
                runCatching { auth.has(LLMProvider.OPENAI_API) }.getOrDefault(false)
            if (!oauthGateReady && !apiGateReady) {
                return "Jarvis intent gate needs ChatGPT sign-in or an OpenAI API key"
            }
            return null
'''
s = s[:start] + replacement + s[end:]
service.write_text(s, encoding='utf-8')

# Fast structural tests. No generated voice, emulator or network.
test_dir = root / 'app/src/test/kotlin/ai/closepaw/ui/capsule/voice'
test_dir.mkdir(parents=True, exist_ok=True)
(test_dir / 'UnifiedVoiceFlowContractTest.kt').write_text(r'''package ai.closepaw.ui.capsule.voice

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class UnifiedVoiceFlowContractTest {
    @Test
    fun userFacingTranscriptionChoicesAreCloudModelsSharedByBothInputs() {
        val ids = VoiceTranscriptionSettings.modelOptions.map { it.first }
        assertTrue(VoiceTranscriptionSettings.GPT_TRANSCRIBE in ids)
        assertFalse(VoiceTranscriptionSettings.SYSTEM in ids)
    }

    @Test
    fun realtimeDefaultRemainsAConfiguredTranscriptionModel() {
        val ids = VoiceTranscriptionSettings.modelOptions.map { it.first }
        assertTrue(HandsFreeRealtimeContract.TRANSCRIPTION_MODEL in ids)
    }
}
''', encoding='utf-8')

print('Unified Jarvis input + normal agent/transcription flow applied')
