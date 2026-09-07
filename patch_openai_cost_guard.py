from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Cost-guard anchor not found in {path}: {old[:160]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# 1) New ordinary sessions prefer a matching ChatGPT/Codex OAuth model. Keep this routing decision
# at session creation rather than in LLMClientFactory: hands-free intentionally selects an API mirror
# after a real OAuth usage/rate limit, and the factory must not silently route that fallback back to
# OAuth. Reloaded legacy API sessions are protected by the hard API fuse below.
main = root / 'app/src/main/kotlin/ai/closepaw/app/MainActivity.kt'
replace_once(
    main,
    '''                        mainModel = settingsState.selectedModel,
''',
    '''                        mainModel = resolveCostSafeMainModel(),
''',
)
replace_once(
    main,
    '''    private suspend fun createFreshSession(
''',
    '''    private fun resolveCostSafeMainModel(): String {
        val selected = settingsState.selectedModel
        if (settingsState.llmBackend != LLMBackendType.CLOUD) return selected
        val entry = runCatching { modelCatalog.resolve(selected) }.getOrNull() ?: return selected
        if (entry.provider != LLMProvider.OPENAI_API) return selected
        val oauthReady = runCatching { authStore.has(LLMProvider.OPENAI_CODEX) }.getOrDefault(false)
        if (!oauthReady) return selected
        val oauthMirror = modelCatalog.modelsFor(LLMProvider.OPENAI_CODEX)
            .firstOrNull { it.modelId == entry.modelId }
            ?: return selected
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
            stage = "llm-route",
            message = "Ordinary session routed to ChatGPT OAuth instead of paid API mirror",
            metadata = mapOf(
                "configured_model" to selected,
                "effective_model" to oauthMirror.name,
                "model_id" to entry.modelId,
            ),
        )
        return oauthMirror.name
    }

    private suspend fun createFreshSession(
''',
)

# 2) Every direct OpenAI API client gets a hard pre-network request-size fuse. This also protects
# resumed old sessions and intentional hands-free API fallback.
factory = root / 'app/src/main/kotlin/ai/closepaw/llm/LLMClientFactory.kt'
replace_once(
    factory,
    '''                        ApiType.RESPONSE ->
                                OpenAIResponseClient(store.requireApiKey(LLMProvider.OPENAI_API), baseUrl)
                        ApiType.CHAT ->
                                ChatCompletionClient(store.requireApiKey(LLMProvider.OPENAI_API), baseUrl)
''',
    '''                        ApiType.RESPONSE ->
                                OpenAIResponseClient(
                                    store.requireApiKey(LLMProvider.OPENAI_API),
                                    baseUrl,
                                    maxEstimatedInputTokens = OPENAI_DIRECT_MAX_ESTIMATED_INPUT_TOKENS,
                                )
                        ApiType.CHAT ->
                                ChatCompletionClient(
                                    store.requireApiKey(LLMProvider.OPENAI_API),
                                    baseUrl,
                                    maxEstimatedInputTokens = OPENAI_DIRECT_MAX_ESTIMATED_INPUT_TOKENS,
                                )
''',
)

# 3) Hard pre-network fuse for direct OpenAI Chat Completions calls.
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
                "api" to "chat_completions",
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

# 4) Pure JVM regression tests for the fuse — no emulator, audio, or network.
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

print('Ordinary OAuth-first routing + direct OpenAI API cost fuse applied')
