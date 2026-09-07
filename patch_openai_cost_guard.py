from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Cost-guard anchor not found in {path}: {old[:160]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# 1) Global OpenAI routing safety: if the user is signed into ChatGPT and the selected
# OPENAI_API entry has an identical Codex/OAuth modelId, use the subscription route.
# This also protects reloaded sessions whose stored config still points at OPENAI_API.
factory = root / 'app/src/main/kotlin/ai/closepaw/llm/LLMClientFactory.kt'
replace_once(
    factory,
    '''            val currentGen = if (store != null && provider != LLMProvider.LOCAL_LFM) {
                store.generation(provider)
            } else 0L
''',
    '''            val currentGen = if (store != null && provider != LLMProvider.LOCAL_LFM) {
                val providerGen = store.generation(provider)
                // OPENAI_API entries may be transparently routed through matching ChatGPT OAuth.
                // Include the OAuth generation so sign-in/sign-out invalidates this cache entry.
                if (provider == LLMProvider.OPENAI_API) {
                    providerGen * 31L + store.generation(LLMProvider.OPENAI_CODEX)
                } else providerGen
            } else 0L
''',
)
replace_once(
    factory,
    '''            LLMProvider.OPENAI_API ->
                    when (entry.api) {
                        ApiType.RESPONSE ->
                                OpenAIResponseClient(store.requireApiKey(LLMProvider.OPENAI_API), baseUrl)
                        ApiType.CHAT ->
                                ChatCompletionClient(store.requireApiKey(LLMProvider.OPENAI_API), baseUrl)
                    }
''',
    '''            LLMProvider.OPENAI_API -> {
                val oauthMirror = catalog.modelsFor(LLMProvider.OPENAI_CODEX)
                    .firstOrNull { it.modelId == entry.modelId }
                val explicitApiBaseOverride = baseUrlOverrides.containsKey(LLMProvider.OPENAI_API)
                if (!explicitApiBaseOverride && oauthMirror != null && store.has(LLMProvider.OPENAI_CODEX)) {
                    // Subscription first. A selected API mirror must not silently burn API credit
                    // while the same model is already available through the user's ChatGPT login.
                    CodexResponseClient(
                        headerSupplier = { store.codexHeaders(LLMProvider.OPENAI_CODEX) }
                    )
                } else {
                    when (entry.api) {
                        ApiType.RESPONSE ->
                            OpenAIResponseClient(store.requireApiKey(LLMProvider.OPENAI_API), baseUrl)
                        ApiType.CHAT ->
                            ChatCompletionClient(
                                store.requireApiKey(LLMProvider.OPENAI_API),
                                baseUrl,
                                maxEstimatedInputTokens = OPENAI_DIRECT_MAX_ESTIMATED_INPUT_TOKENS,
                            )
                    }
                }
            }
''',
)

# 2) Hard pre-network fuse for direct OpenAI Chat Completions calls.
chat = root / 'app/src/main/kotlin/ai/closepaw/llm/ChatCompletionClient.kt'
replace_once(
    chat,
    '''import android.util.Log
''',
    '''import android.util.Log
import ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay
''',
)
replace_once(
    chat,
    '''class ChatCompletionClient(
    apiKey: String,
    baseUrl: String? = null
) : LLMClient() {
''',
    '''internal const val OPENAI_DIRECT_MAX_ESTIMATED_INPUT_TOKENS = 32_000L

/**
 * Conservative request-size estimate used only as a billing fuse. It intentionally overestimates
 * ordinary UTF-8 English text (~3 chars/token rather than ~4) and includes SDK object renderings so
 * tool schemas, function output and multimodal data URLs contribute to the guard.
 */
internal fun estimateOpenAiRequestInputTokens(
    systemPrompt: String,
    inputItems: List<ResponseInputItem>,
    tools: List<FunctionTool>,
): Long {
    val chars = systemPrompt.length.toLong() +
        inputItems.sumOf { it.toString().length.toLong() } +
        tools.sumOf { it.toString().length.toLong() }
    return (chars + 2L) / 3L
}

class ChatCompletionClient(
    apiKey: String,
    baseUrl: String? = null,
    private val maxEstimatedInputTokens: Long? = null,
) : LLMClient() {
''',
)
replace_once(
    chat,
    '''    private fun executeChatWithTools(
        systemPrompt: String,
        inputItems: List<ResponseInputItem>,
        tools: List<FunctionTool>,
        model: String,
        maxOutputTokens: Long?,
    ): ResponsesResult {
        Log.d(TAG, "Calling Chat Completions API with ${inputItems.size} input items, ${tools.size} tools")
''',
    '''    private fun executeChatWithTools(
        systemPrompt: String,
        inputItems: List<ResponseInputItem>,
        tools: List<FunctionTool>,
        model: String,
        maxOutputTokens: Long?,
    ): ResponsesResult {
        enforceApiCostGuard(systemPrompt, inputItems, tools, model)
        Log.d(TAG, "Calling Chat Completions API with ${inputItems.size} input items, ${tools.size} tools")
''',
)
replace_once(
    chat,
    '''        val job = launch {
            val retryResult =
''',
    '''        val job = launch {
            val costGuardError = runCatching {
                enforceApiCostGuard(systemPrompt, inputItems, tools, model)
            }.exceptionOrNull()
            if (costGuardError != null) {
                trySend(LLMStreamEvent.Failed(costGuardError.message ?: "OpenAI API cost guard blocked request"))
                close()
                return@launch
            }
            val retryResult =
''',
)
replace_once(
    chat,
    '''    // ── Helpers ──────────────────────────────────────────────────────────

    private fun buildParams(
''',
    '''    // ── Helpers ──────────────────────────────────────────────────────────

    private fun enforceApiCostGuard(
        systemPrompt: String,
        inputItems: List<ResponseInputItem>,
        tools: List<FunctionTool>,
        model: String,
    ) {
        val limit = maxEstimatedInputTokens ?: return
        val estimated = estimateOpenAiRequestInputTokens(systemPrompt, inputItems, tools)
        HandsFreeDebugRelay.publish(
            stage = "llm-api-preflight",
            message = "OpenAI API request preflight model=$model estimated_input=$estimated limit=$limit",
            metadata = mapOf(
                "provider" to "OPENAI_API",
                "model" to model,
                "estimated_input_tokens" to estimated,
                "limit_tokens" to limit,
                "input_items" to inputItems.size,
                "tools" to tools.size,
            ),
        )
        if (estimated > limit) {
            HandsFreeDebugRelay.publish(
                stage = "llm-api-cost-guard",
                level = "error",
                message = "Blocked oversized paid OpenAI API request before network",
                metadata = mapOf(
                    "model" to model,
                    "estimated_input_tokens" to estimated,
                    "limit_tokens" to limit,
                ),
            )
            throw IllegalStateException(
                "OpenAI API cost guard blocked ~$estimated input tokens (limit $limit). " +
                    "Use ChatGPT OAuth or start/compact the session before paid API fallback."
            )
        }
    }

    private fun buildParams(
''',
)

# 3) Pure JVM regression tests for the fuse — no emulator, audio, or network.
test_dir = root / 'app/src/test/kotlin/ai/closepaw/llm'
test_dir.mkdir(parents=True, exist_ok=True)
(test_dir / 'OpenAiApiCostGuardTest.kt').write_text(r'''package ai.closepaw.llm

import kotlin.test.Test
import kotlin.test.assertTrue

class OpenAiApiCostGuardTest {
    @Test
    fun smallPromptStaysBelowDirectApiFuse() {
        val estimated = estimateOpenAiRequestInputTokens(
            systemPrompt = "You are a mobile assistant.",
            inputItems = emptyList(),
            tools = emptyList(),
        )
        assertTrue(estimated < OPENAI_DIRECT_MAX_ESTIMATED_INPUT_TOKENS)
    }

    @Test
    fun giantPromptIsBlockedByDirectApiFuse() {
        val estimated = estimateOpenAiRequestInputTokens(
            systemPrompt = "x".repeat(100_000),
            inputItems = emptyList(),
            tools = emptyList(),
        )
        assertTrue(estimated > OPENAI_DIRECT_MAX_ESTIMATED_INPUT_TOKENS)
    }
}
''', encoding='utf-8')

print('Global OAuth-first OpenAI routing + direct API cost fuse applied')
