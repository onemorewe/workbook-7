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
    '''    // One configured STT choice for both normal mic and Jarvis after the local wake word.
    // Android speech remains an automatic normal-mic fallback when the API key is unavailable,
    // but is not a configured shared mode because Jarvis Realtime needs a cloud transcription
    // session after wake.
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
# 2. Intent gate remains, but it is only Jarvis input preprocessing.
#    It must use the configured Agent model/provider and must never auto-fallback providers.
# ---------------------------------------------------------------------------
gate = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeIntentGate.kt'
g = gate.read_text(encoding='utf-8')
for forbidden in (
    'apiFallbackModel',
    'activeExecutionModel',
    'intent-gate-fallback',
    'catch (limited: RateLimitException)',
):
    if forbidden in g:
        raise SystemExit(f'Jarvis intent gate still contains forbidden automatic fallback coupling: {forbidden}')
if 'val selected = AppSettingsStore(appContext).load().selectedModel' not in g:
    raise SystemExit('Jarvis intent gate must read the configured Agent model')
if 'clientFor(catalog, selected).chatWithTools' not in g:
    raise SystemExit('Jarvis intent gate must call the configured Agent model directly')

agent_service = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
a = agent_service.read_text(encoding='utf-8')
if 'HandsFreeIntentGate.activeExecutionModel' in a:
    raise SystemExit('AgentService still couples hands-free execution to intent-gate routing')
if 'fun submitHandsFreeCommand(text: String)' not in a:
    raise SystemExit('Hands-free command adapter missing from AgentService')

# ---------------------------------------------------------------------------
# 3. Dedicated Voice & Runtime board: separate Transcription and Agent selectors.
#    Selecting API billing requires explicit confirmation. Selection is truthful: no hidden reroute.
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
p = p.replace(
    '''    val authStore = remember(context) { runCatching { AuthStoreHolder.get(context.applicationContext) }.getOrNull() }
''',
    '''    val authStore = remember(context) { runCatching { AuthStoreHolder.get(context.applicationContext) }.getOrNull() }
    var pendingPaidAgentModel by remember { mutableStateOf<String?>(null) }
    val configuredAgentEntry = modelCatalog.resolveOrNull(selectedModel)
    val agentOptions = remember(modelCatalog) {
        modelCatalog.all().map { entry ->
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
                } else if (configuredAgentEntry?.provider?.mode == AuthMode.OAuth) {
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Subscription route only. If the ChatGPT usage limit is reached, the task stops — there is no automatic API fallback.",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
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

old_gate_block = '''                val gateReady = when (agentProvider) {
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
'''
new_gate_block = '''                val gateReady = agentEntry != null && agentProvider != LLMProvider.LOCAL_LFM && agentCredentialPresent
                val gateDescription = when {
                    agentEntry == null -> "unavailable · configured Agent model not found"
                    agentProvider == LLMProvider.LOCAL_LFM -> "unavailable · local Agent gate not wired yet"
                    !agentCredentialPresent -> "unavailable · configured Agent provider is not authenticated"
                    else -> "$effectiveAgentModel · same provider as Agent · no automatic provider fallback"
                }
'''
if old_gate_block not in p:
    raise SystemExit('Old hands-free gate routing block missing')
p = p.replace(old_gate_block, new_gate_block, 1)
p = p.replace(
    '''                        "Live STT: ${HandsFreeRealtimeContract.TRANSCRIPTION_MODEL} · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",
                        "Intent gate: $gateDescription",
''',
    '''                        "STT: $voiceModel · shared with normal microphone · ${if (openAiKeyConnected) "OpenAI API key connected" else "OpenAI API key missing"}",
                        "Intent gate: $gateDescription · input normalization only",
                        "Execution: normal AgentSession pipeline · same Agent selector above",
''',
    1,
)

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
# 4. Hands-free preflight checks the exact configured Agent provider. No hidden OpenAI gate route.
# ---------------------------------------------------------------------------
service = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt'
s = service.read_text(encoding='utf-8')
start = s.find('            val selected = runCatching { AppSettingsStore(context).load().selectedModel }')
end = s.find('            return null\n        }', start)
if start < 0 or end < 0:
    raise SystemExit('Could not bound hands-free preflight agent-auth block')
end += len('            return null\n')
replacement = '''            val selected = runCatching { AppSettingsStore(context).load().selectedModel }.getOrNull()
                ?: return "Could not read the configured Agent model"
            val entry = runCatching {
                ModelCatalogRepositoryHolder.get(context).catalog.value.resolveOrNull(selected)
            }.getOrNull() ?: return "Configured Agent model '$selected' is not available"
            if (entry.provider == LLMProvider.LOCAL_LFM) {
                return "Jarvis intent gate currently requires a cloud Agent model"
            }
            if (!runCatching { auth.has(entry.provider) }.getOrDefault(false)) {
                return "Jarvis intent gate is not authenticated for ${entry.provider}"
            }
            return null
'''
s = s[:start] + replacement + s[end:]
service.write_text(s, encoding='utf-8')

test_dir = root / 'app/src/test/kotlin/ai/closepaw/ui/capsule/voice'
test_dir.mkdir(parents=True, exist_ok=True)
(test_dir / 'UnifiedVoiceFlowContractTest.kt').write_text(r'''package ai.closepaw.ui.capsule.voice

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class UnifiedVoiceFlowContractTest {
    @Test
    fun configuredTranscriptionChoicesAreSharedCloudModels() {
        val ids = VoiceTranscriptionSettings.modelOptions.map { it.first }
        assertTrue(VoiceTranscriptionSettings.GPT_TRANSCRIBE in ids)
        assertFalse(VoiceTranscriptionSettings.SYSTEM in ids)
    }

    @Test
    fun realtimeDefaultIsOneOfSharedConfiguredModels() {
        val ids = VoiceTranscriptionSettings.modelOptions.map { it.first }
        assertTrue(HandsFreeRealtimeContract.TRANSCRIPTION_MODEL in ids)
    }
}
''', encoding='utf-8')

print('Unified Jarvis input + explicit Agent routing applied; automatic Plus-to-API fallback removed')
