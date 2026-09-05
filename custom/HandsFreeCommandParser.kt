package ai.closepaw.ui.capsule.voice

internal data class HandsFreeParseResult(
    val wakeDetected: Boolean,
    val command: String?,
)

internal object HandsFreeCommandParser {
    private val wakeRegex = Regex(
        pattern = "^(?:эй[\\s,!.:-]+)?(?:ал[её]ша|алиша|л[её]ша|alyosha|alesha)(?=\\s|[,!.?:;-]|$)[\\s,!.?:;-]*(.*)$",
        option = RegexOption.IGNORE_CASE,
    )

    fun parse(transcript: String, armed: Boolean): HandsFreeParseResult {
        val text = transcript.trim()
        if (text.isBlank()) return HandsFreeParseResult(false, null)
        if (armed) return HandsFreeParseResult(true, text)

        val match = wakeRegex.find(text) ?: return HandsFreeParseResult(false, null)
        val command = match.groupValues.getOrNull(1)?.trim()?.takeIf { it.isNotBlank() }
        return HandsFreeParseResult(true, command)
    }
}
