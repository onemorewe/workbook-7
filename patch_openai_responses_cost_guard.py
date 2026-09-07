from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Responses cost-guard anchor not found in {path}: {old[:160]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# LLMClientFactory constructor wiring is applied by patch_openai_cost_guard.py. This patch only
# protects the Responses transport itself, avoiding a duplicate/fragile factory rewrite.
responses = root / 'app/src/main/kotlin/ai/closepaw/llm/OpenAIResponseClient.kt'
replace_once(
    responses,
    'import android.util.Log\n',
    'import android.util.Log\nimport ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay\n',
)
replace_once(
    responses,
    '''class OpenAIResponseClient(
    apiKey: String,
    baseUrl: String? = null
) : LLMClient() {
''',
    '''class OpenAIResponseClient(
    apiKey: String,
    baseUrl: String? = null,
    private val maxEstimatedInputTokens: Long? = null,
) : LLMClient() {
''',
)
replace_once(
    responses,
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
    responses,
    '''    ): ResponsesResult {
        Log.d(TAG, "Calling Responses API with ${inputItems.size} input items, ${tools.size} tools")
''',
    '''    ): ResponsesResult {
        enforceApiCostGuard(systemPrompt, inputItems, tools, model)
        Log.d(TAG, "Calling Responses API with ${inputItems.size} input items, ${tools.size} tools")
''',
)
replace_once(
    responses,
    '''    private fun buildResponseParams(
''',
    '''    private fun enforceApiCostGuard(
        systemPrompt: String,
        inputItems: List<ResponseInputItem>,
        tools: List<FunctionTool>,
        model: String,
    ) {
        val limit = maxEstimatedInputTokens ?: return
        val estimated = estimateOpenAiRequestInputTokens(systemPrompt, inputItems, tools)
        HandsFreeDebugRelay.publish(
            stage = "llm-api-preflight",
            message = "OpenAI Responses request preflight model=$model estimated_input=$estimated limit=$limit",
            metadata = mapOf(
                "provider" to "OPENAI_API",
                "api" to "responses",
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
                message = "Blocked oversized paid OpenAI Responses request before network",
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

    private fun buildResponseParams(
''',
)

print('Direct OpenAI Responses API cost fuse applied')
