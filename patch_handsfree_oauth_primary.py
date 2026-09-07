from pathlib import Path

service = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt')
text = service.read_text(encoding='utf-8')

old = '''            when (entry.provider) {
                LLMProvider.OPENAI_CODEX -> {
                    if (!runCatching { auth.has(LLMProvider.OPENAI_CODEX) }.getOrDefault(false)) {
                        return "ChatGPT sign-in is required for the hands-free intent gate"
                    }
                }
                LLMProvider.OPENAI_API -> {
                    if (!runCatching { auth.has(LLMProvider.OPENAI_API) }.getOrDefault(false)) {
                        return "OpenAI API key is required for the hands-free intent gate"
                    }
                }
                else -> return "Hands-free intent gate requires an OpenAI ChatGPT/API model; '$selected' uses ${entry.provider}"
            }
            return null
'''

new = '''            val catalog = ModelCatalogRepositoryHolder.get(context).catalog.value
            val oauthMirror = when (entry.provider) {
                LLMProvider.OPENAI_CODEX -> entry
                LLMProvider.OPENAI_API -> catalog.modelsFor(LLMProvider.OPENAI_CODEX)
                    .firstOrNull { it.modelId == entry.modelId }
                else -> null
            }
            val oauthReady = oauthMirror != null && runCatching {
                auth.has(LLMProvider.OPENAI_CODEX)
            }.getOrDefault(false)

            when (entry.provider) {
                LLMProvider.OPENAI_CODEX -> {
                    if (!oauthReady) {
                        return "ChatGPT sign-in is required for the hands-free intent gate"
                    }
                }
                LLMProvider.OPENAI_API -> {
                    // If a matching OAuth model is connected, HandsFreeIntentGate uses it first and
                    // falls back to this API model only on a true usage/rate limit. If OAuth is not
                    // connected, an explicitly selected API model remains a valid direct route.
                    val apiReady = runCatching { auth.has(LLMProvider.OPENAI_API) }.getOrDefault(false)
                    if (!oauthReady && !apiReady) {
                        return "OpenAI API key is required for the hands-free intent gate"
                    }
                }
                else -> return "Hands-free intent gate requires an OpenAI ChatGPT/API model; '$selected' uses ${entry.provider}"
            }
            return null
'''

if old not in text:
    raise SystemExit('OAuth-primary preflight anchor not found')
service.write_text(text.replace(old, new, 1), encoding='utf-8')
print('Hands-free OAuth-primary preflight route applied')

# Apply process-wide billing safety patches from the checkout root. The workflow copies this script
# into the pinned ClosePaw checkout, while the patch repository remains its parent directory.
for patch_name in ('patch_openai_cost_guard.py', 'patch_openai_responses_cost_guard.py'):
    patch = Path('..') / patch_name
    if not patch.exists():
        raise SystemExit(f'{patch_name} missing from patch checkout')
    exec(compile(patch.read_text(encoding='utf-8'), str(patch), 'exec'))
