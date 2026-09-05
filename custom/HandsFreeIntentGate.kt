package ai.closepaw.ui.capsule.voice

import android.content.Context
import ai.closepaw.app.AppSettingsStore
import ai.closepaw.app.AuthStoreHolder
import ai.closepaw.llm.LLMClient
import ai.closepaw.llm.LLMClientFactory
import ai.closepaw.llm.LLMProvider
import ai.closepaw.llm.ModelCatalog
import ai.closepaw.llm.ModelCatalogRepositoryHolder
import ai.closepaw.llm.RateLimitException
import com.openai.models.responses.EasyInputMessage
import com.openai.models.responses.ResponseInputItem

/**
 * Turns a cumulative live transcript into either NOT_READY or one normalized intent.
 *
 * If the configured agent model uses ChatGPT/Codex OAuth, the gate tries the subscription route
 * first and falls back only on a real rate/usage limit to the mirrored OpenAI API-key model.
 * If the configured agent model already uses OpenAI API, the gate uses that API model directly.
 */
internal class HandsFreeIntentGate(
    context: Context,
) : AutoCloseable {
    private val appContext = context.applicationContext
    private var factory: LLMClientFactory? = null
    private val clients = mutableMapOf<String, LLMClient>()
    private var catalogIdentity: ModelCatalog? = null

    suspend fun classify(
        cumulativeTranscript: String,
        finalAfterSilence: Boolean = false,
    ): Result<String?> = runCatching {
        val transcript = cumulativeTranscript.trim()
        if (transcript.isBlank()) return@runCatching null

        val settings = AppSettingsStore(appContext).load()
        val selected = settings.selectedModel
        val catalog = ModelCatalogRepositoryHolder.get(appContext).catalog.value
        val selectedEntry = catalog.resolve(selected)
        require(
            selectedEntry.provider == LLMProvider.OPENAI_CODEX ||
                selectedEntry.provider == LLMProvider.OPENAI_API
        ) {
            "Hands-free intent gate requires an OpenAI ChatGPT/API model; selected model '$selected' uses ${selectedEntry.provider}."
        }

        val input = listOf(
            ResponseInputItem.ofEasyInputMessage(
                EasyInputMessage.builder()
                    .role(EasyInputMessage.Role.USER)
                    .content(transcript)
                    .build()
            )
        )
        val systemPrompt = if (finalAfterSilence) "$PROMPT\n\n$FINAL_SILENCE_HINT" else PROMPT

        val result = when (selectedEntry.provider) {
            LLMProvider.OPENAI_API -> {
                val auth = AuthStoreHolder.get(appContext)
                require(auth.has(LLMProvider.OPENAI_API)) {
                    "OpenAI API key is required for the hands-free intent gate"
                }
                // Direct API selection is not an OAuth fallback; execution should follow settings.
                activeFallbackModel = null
                clientFor(catalog, selected).chatWithTools(
                    systemPrompt = systemPrompt,
                    inputItems = input,
                    tools = emptyList(),
                    model = selected,
                )
            }

            LLMProvider.OPENAI_CODEX -> {
                val primary = clientFor(catalog, selected)
                try {
                    primary.chatWithTools(
                        systemPrompt = systemPrompt,
                        inputItems = input,
                        tools = emptyList(),
                        model = selected,
                    ).also {
                        // OAuth works again: stop forcing API execution for subsequent hands-free tasks.
                        activeFallbackModel = null
                    }
                } catch (limited: RateLimitException) {
                    val apiEntry = catalog.modelsFor(LLMProvider.OPENAI_API)
                        .firstOrNull { it.modelId == selectedEntry.modelId }
                        ?: throw IllegalStateException(
                            "ChatGPT usage limit reached and no API mirror exists for ${selectedEntry.modelId}",
                            limited,
                        )

                    val auth = AuthStoreHolder.get(appContext)
                    require(auth.has(LLMProvider.OPENAI_API)) {
                        "ChatGPT usage limit reached and OpenAI API key fallback is not configured"
                    }

                    activeFallbackModel = apiEntry.name
                    HandsFreeDebugRelay.publish(
                        "intent-gate-fallback",
                        "ChatGPT usage limit reached; retrying intent gate via OpenAI API model ${apiEntry.name}",
                    )

                    clientFor(catalog, apiEntry.name).chatWithTools(
                        systemPrompt = systemPrompt,
                        inputItems = input,
                        tools = emptyList(),
                        model = apiEntry.name,
                    )
                }
            }

            else -> error("Unsupported hands-free intent provider ${selectedEntry.provider}")
        }

        parse(result.textContent.orEmpty())
    }

    private suspend fun clientFor(catalog: ModelCatalog, model: String): LLMClient {
        if (factory == null || catalogIdentity !== catalog) {
            factory?.cleanupAll()
            clients.clear()
            factory = LLMClientFactory(catalog, AuthStoreHolder.get(appContext))
            catalogIdentity = catalog
        }
        return clients.getOrPut(model) { factory!!.create(model) }
    }

    private fun parse(raw: String): String? {
        var text = raw.trim()
        if (text.isBlank()) return null
        if (text.equals("NOT_READY", ignoreCase = true)) return null
        if (text.startsWith("INTENT:", ignoreCase = true)) text = text.substringAfter(':').trim()
        text = text.trim('`', '"', '\'', ' ', '\n', '\r', '\t')
        if (text.equals("NOT_READY", ignoreCase = true) || text.isBlank()) return null
        return text
    }

    override fun close() {
        factory = null
        clients.clear()
        catalogIdentity = null
    }

    suspend fun cleanup() {
        factory?.cleanupAll()
        factory = null
        clients.clear()
        catalogIdentity = null
    }

    companion object {
        @Volatile private var activeFallbackModel: String? = null

        /**
         * API model selected by the most recent OAuth rate-limit fallback. Agent execution uses
         * the same route so the intent gate cannot succeed and then immediately die on OAuth.
         */
        fun activeApiFallbackModel(): String? = activeFallbackModel

        private val PROMPT = """
            You are the turn-completion and intent gate for a hands-free driving assistant.
            The input is the cumulative live transcript after the wake word.

            Decide whether the user has completed a turn that the main assistant can act on or
            respond to. A complete turn may be a command, request, question, conversational
            statement, correction, or request for explanation. It does NOT need to be phrased as
            an imperative. Speech-to-text may omit punctuation, so infer question/statement intent
            from meaning rather than punctuation alone.

            If the utterance is genuinely unfinished, trailing off, still being corrected, or has
            a reference that cannot yet be interpreted, output exactly:
            NOT_READY

            Otherwise output ONLY the normalized user intent that the main agent should receive.
            No label, explanation, markdown, quotation marks, or commentary.

            Preserve important names, app names, song titles, numbers, and Russian/English mixing.
            Apply explicit self-corrections. Example: “поставь X... нет, лучше Y” becomes
            “поставь Y”. Remove the wake word and meaningless filler, but do not invent details.
            A short pause by itself is not proof of completion, but do not reject a semantically
            complete question or statement merely because it is informal.
            Do not execute tools and do not answer the request yourself.
        """.trimIndent()

        private val FINAL_SILENCE_HINT = """
            Additional signal: no new speech has arrived for a further grace period after the VAD
            turn ended. Prefer accepting any transcript that is interpretable enough for the main
            assistant to answer or act on. Return NOT_READY only if meaningful missing words are
            still required to understand what the user wants.
        """.trimIndent()
    }
}
