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

    suspend fun classify(cumulativeTranscript: String): Result<String?> = runCatching {
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
            systemPrompt = PROMPT,
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
        // Be tolerant of a model adding the requested label despite the prompt.
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
        // cleanupAll is suspend; the owning service does final async cleanup. Individual Codex
        // clients hold no microphone resource, so dropping references here is safe.
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
            You are the intent gate for a hands-free driving assistant.
            The user input is the cumulative live transcript since the wake word “Алёша”.

            Your only job is to decide whether the user has already expressed one actionable,
            sufficiently specific intent that can be handed to the main agent now.

            If the thought is unfinished, trailing off, still being corrected, has an unresolved
            target/reference, or clearly needs more words from the user, output exactly:
            NOT_READY

            Otherwise output ONLY the normalized user intent that the main agent should execute.
            No label, explanation, markdown, quotation marks, or commentary.

            Preserve important names, app names, song titles, numbers, and Russian/English mixing.
            Apply explicit self-corrections. Example: “поставь X... нет, лучше Y” becomes
            “поставь Y”. Remove the wake word and meaningless filler, but do not invent details.
            A pause by itself is never evidence that the intent is ready.
            Do not execute tools and do not answer the request yourself.
        """.trimIndent()
    }
}
