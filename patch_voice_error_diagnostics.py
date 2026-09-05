from pathlib import Path

root = Path('.')
voice = root / 'app/src/main/kotlin/ai/closepaw/ui/capsule/voice'


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:140]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


recognizer = voice / 'Recognizer.kt'
replace_once(
    recognizer,
    '''    NetworkTimeout,
    LanguageUnavailable,
''',
    '''    NetworkTimeout,
    ApiAuth,
    ApiRateLimit,
    ApiRequest,
    LanguageUnavailable,
''',
)

controller = voice / 'VoiceInputController.kt'
replace_once(
    controller,
    '''        VoiceError.Network, VoiceError.NetworkTimeout -> {
            onText(baseText)
            onToast("Voice needs network for this language")
            VoiceState.Idle
        }
''',
    '''        VoiceError.Network, VoiceError.NetworkTimeout -> {
            onText(baseText)
            onToast("Voice network connection failed")
            VoiceState.Idle
        }
        VoiceError.ApiAuth -> {
            onText(baseText)
            onToast("OpenAI voice authentication failed — check API key")
            VoiceState.Idle
        }
        VoiceError.ApiRateLimit -> {
            onText(baseText)
            onToast("OpenAI voice limit reached (HTTP 429)")
            VoiceState.Idle
        }
        VoiceError.ApiRequest -> {
            onText(baseText)
            onToast("OpenAI voice request failed")
            VoiceState.Idle
        }
''',
)

openai = voice / 'OpenAIRecognizer.kt'
replace_once(
    openai,
    '''            try { finish(transcribe(audio).trim()) }
            catch (_: IOException) { error(VoiceError.Network) }
            catch (_: Throwable) { error(VoiceError.Unknown) }
''',
    '''            try { finish(transcribe(audio).trim()) }
            catch (e: OpenAIVoiceHttpException) {
                val mapped = mapOpenAiVoiceHttpStatus(e.status)
                HandsFreeDebugRelay.publish(
                    stage = "voice-http-error",
                    level = "error",
                    message = "OpenAI voice HTTP ${e.status}",
                    metadata = mapOf("http_status" to e.status, "mapped_error" to mapped.name),
                )
                error(mapped)
            }
            catch (_: IOException) {
                HandsFreeDebugRelay.publish(
                    stage = "voice-network-error",
                    level = "error",
                    message = "OpenAI voice network I/O failure",
                )
                error(VoiceError.Network)
            }
            catch (_: Throwable) {
                HandsFreeDebugRelay.publish(
                    stage = "voice-runtime-error",
                    level = "error",
                    message = "OpenAI voice unexpected runtime failure",
                )
                error(VoiceError.Unknown)
            }
''',
)
replace_once(
    openai,
    '''            if (status !in 200..299) throw IOException("HTTP $status")
            return JSONObject(body).optString("text", "")
''',
    '''            if (status !in 200..299) throw OpenAIVoiceHttpException(status)
            return JSONObject(body).optString("text", "")
''',
)
openai_text = openai.read_text(encoding='utf-8')
openai_text += r'''

internal class OpenAIVoiceHttpException(val status: Int) : IOException("HTTP $status")

internal fun mapOpenAiVoiceHttpStatus(status: Int): VoiceError = when (status) {
    401, 403 -> VoiceError.ApiAuth
    429 -> VoiceError.ApiRateLimit
    else -> VoiceError.ApiRequest
}
'''
openai.write_text(openai_text, encoding='utf-8')

# Pure JVM regression test: a real HTTP/API failure must never be mislabeled as networking.
test_dir = root / 'app/src/test/kotlin/ai/closepaw/ui/capsule/voice'
test_dir.mkdir(parents=True, exist_ok=True)
(test_dir / 'VoiceHttpErrorMappingTest.kt').write_text(r'''package ai.closepaw.ui.capsule.voice

import kotlin.test.Test
import kotlin.test.assertEquals

class VoiceHttpErrorMappingTest {
    @Test fun authErrorsAreAuth() {
        assertEquals(VoiceError.ApiAuth, mapOpenAiVoiceHttpStatus(401))
        assertEquals(VoiceError.ApiAuth, mapOpenAiVoiceHttpStatus(403))
    }

    @Test fun rateLimitIsRateLimit() {
        assertEquals(VoiceError.ApiRateLimit, mapOpenAiVoiceHttpStatus(429))
    }

    @Test fun modelAndServerErrorsAreApiRequests() {
        assertEquals(VoiceError.ApiRequest, mapOpenAiVoiceHttpStatus(400))
        assertEquals(VoiceError.ApiRequest, mapOpenAiVoiceHttpStatus(500))
    }
}
''', encoding='utf-8')

print('Voice error diagnostics patch applied')
