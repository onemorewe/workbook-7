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
 * Hands-free routing is intentionally independent from the ordinary agent auth selector:
 * - if a ChatGPT/Codex OAuth mirror exists and OAuth is connected, use it first;
 * - fall back to the matching OpenAI API model only on a real rate/usage limit;
 * - if the user explicitly selected an OpenAI API model and no usable OAuth mirror exists,
 *   use that API model directly.
 *
 * The model used by the gate is also exposed to AgentService so execution follows the same route.
 */
internal class HandsFreeIntentGate(
    context: Context,
) : AutoCloseable {
    private val appContext = context.applicationContext
    private var factory: LLMClientFactory? = null
    private val clients = mutableMapOf<String, LLMClient>()
    private var catalogIdentity: ModelCatalog? = null

    private data class Route(
        val primaryModel: String,
        val primaryProvider: LLMProvider,
        val apiFallbackModel: String?,
    )

    suspend fun classify(
        cumulativeTranscript: String,
        finalAfterSilence: Boolean = false,
    ): Result<String?> = runCatching {
        val transcript = cumulativeTranscript.trim()
        if (transcript.isBlank()) return@runCatching null

        val settings = AppSettingsStore(appContext).load()
        val selected = settings.selectedModel
        val catalog = ModelCatalogRepositoryHolder.get(appContext).catalog.value
        val route = resolveRoute(catalog, selected)

        val input = listOf(
            ResponseInputItem.ofEasyInputMessage(
                EasyInputMessage.builder()
                    .role(EasyInputMessage.Role.USER)
                    .content(transcript)
                    .build()
            )
        )
        val systemPrompt = if (finalAfterSilence) "$PROMPT\n\n$FINAL_SILENCE_HINT" else PROMPT

        val result = when (route.primaryProvider) {
            LLMProvider.OPENAI_API -> {
                activeExecutionModel = route.primaryModel
                clientFor(catalog, route.primaryModel).chatWithTools(
                    systemPrompt = systemPrompt,
                    inputItems = input,
                    tools = emptyList(),
                    model = route.primaryModel,
                )
            }

            LLMProvider.OPENAI_CODEX -> {
                activeExecutionModel = route.primaryModel
                val primary = clientFor(catalog, route.primaryModel)
                try {
                    primary.chatWithTools(
                        systemPrompt = systemPrompt,
                        inputItems = input,
                        tools = emptyList(),
                        model = route.primaryModel,
                    ).also {
                        // OAuth works: execution should stay on the subscription route.
                        activeExecutionModel = route.primaryModel
                    }
                } catch (limited: RateLimitException) {
                    val fallback = route.apiFallbackModel
                        ?: throw IllegalStateException(
                            "ChatGPT usage limit reached and no API mirror exists for ${route.primaryModel}",
                            limited,
                        )

                    activeExecutionModel = fallback
                    HandsFreeDebugRelay.publish(
                        "intent-gate-fallback",
                        "ChatGPT usage limit reached; retrying intent gate via OpenAI API model $fallback",
                    )

                    clientFor(catalog, fallback).chatWithTools(
                        systemPrompt = systemPrompt,
                        inputItems = input,
                        tools = emptyList(),
                        model = fallback,
                    )
                }
            }

            else -> error("Unsupported hands-free intent provider ${route.primaryProvider}")
        }

        parse(result.textContent.orEmpty())
    }

    private fun resolveRoute(catalog: ModelCatalog, selected: String): Route {
        val selectedEntry = catalog.resolve(selected)
        require(
            selectedEntry.provider == LLMProvider.OPENAI_CODEX ||
                selectedEntry.provider == LLMProvider.OPENAI_API
        ) {
            "Hands-free intent gate requires an OpenAI ChatGPT/API model; selected model '$selected' uses ${selectedEntry.provider}."
        }

        val auth = AuthStoreHolder.get(appContext)
        val oauthEntry = when (selectedEntry.provider) {
            LLMProvider.OPENAI_CODEX -> selectedEntry
            LLMProvider.OPENAI_API -> catalog.modelsFor(LLMProvider.OPENAI_CODEX)
                .firstOrNull { it.modelId == selectedEntry.modelId }
            else -> null
        }
        val apiEntry = when (selectedEntry.provider) {
            LLMProvider.OPENAI_API -> selectedEntry
            LLMProvider.OPENAI_CODEX -> catalog.modelsFor(LLMProvider.OPENAI_API)
                .firstOrNull { it.modelId == selectedEntry.modelId }
            else -> null
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

        if (selectedEntry.provider == LLMProvider.OPENAI_API && apiReady) {
            return Route(
                primaryModel = apiEntry!!.name,
                primaryProvider = LLMProvider.OPENAI_API,
                apiFallbackModel = null,
            )
        }

        if (selectedEntry.provider == LLMProvider.OPENAI_CODEX) {
            throw IllegalStateException("ChatGPT sign-in is required for the hands-free intent gate")
        }

        throw IllegalStateException("OpenAI API key is required for the hands-free intent gate")
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
        @Volatile private var activeExecutionModel: String? = null

        /** Model the next hands-free AgentSession must use to match the successful intent route. */
        fun activeExecutionModel(): String? = activeExecutionModel

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
