package ai.closepaw.ui.capsule.voice

import android.content.Context
import ai.closepaw.app.AppSettingsStore
import ai.closepaw.app.AuthStoreHolder
import ai.closepaw.llm.LLMClient
import ai.closepaw.llm.LLMClientFactory
import ai.closepaw.llm.LLMProvider
import ai.closepaw.llm.ModelCatalogRepositoryHolder
import com.openai.models.responses.EasyInputMessage
import com.openai.models.responses.ResponseInputItem

/**
 * Turns a cumulative live transcript into either NOT_READY or one normalized intent.
 *
 * Important: this deliberately uses only the selected ChatGPT/Codex OAuth model. It never falls
 * back to API-key billing. Audio transcription still uses the separate OpenAI API key.
 */
internal class HandsFreeIntentGate(
    context: Context,
) : AutoCloseable {
    private val appContext = context.applicationContext
    private var factory: LLMClientFactory? = null
    private var client: LLMClient? = null
    private var modelName: String? = null

    suspend fun classify(
        cumulativeTranscript: String,
        finalAfterSilence: Boolean = false,
    ): Result<String?> = runCatching {
        val transcript = cumulativeTranscript.trim()
        if (transcript.isBlank()) return@runCatching null

        val settings = AppSettingsStore(appContext).load()
        val selected = settings.selectedModel
        val catalog = ModelCatalogRepositoryHolder.get(appContext).catalog.value
        val entry = catalog.resolve(selected)
        require(entry.provider == LLMProvider.OPENAI_CODEX) {
            "Hands-free intent gate requires ChatGPT sign-in; selected model '$selected' uses ${entry.provider}."
        }

        val llm = if (client == null || modelName != selected) {
            factory?.cleanupAll()
            val builtFactory = LLMClientFactory(catalog, AuthStoreHolder.get(appContext))
            factory = builtFactory
            modelName = selected
            builtFactory.create(selected).also { client = it }
        } else {
            client!!
        }

        val input = listOf(
            ResponseInputItem.ofEasyInputMessage(
                EasyInputMessage.builder()
                    .role(EasyInputMessage.Role.USER)
                    .content(transcript)
                    .build()
            )
        )
        val result = llm.chatWithTools(
            systemPrompt = if (finalAfterSilence) "$PROMPT\n\n$FINAL_SILENCE_HINT" else PROMPT,
            inputItems = input,
            tools = emptyList(),
            model = selected,
        )
        parse(result.textContent.orEmpty())
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
        val old = factory
        factory = null
        client = null
        modelName = null
        @Suppress("UNUSED_VARIABLE") val ignored = old
    }

    suspend fun cleanup() {
        factory?.cleanupAll()
        factory = null
        client = null
        modelName = null
    }

    companion object {
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
