from pathlib import Path

p = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt')
s = p.read_text(encoding='utf-8')
old = '''            if (entry.provider != LLMProvider.OPENAI_CODEX) {
                return "Hands-free intent gate requires a ChatGPT subscription model; '$selected' uses ${entry.provider}"
            }
            if (!runCatching { auth.has(LLMProvider.OPENAI_CODEX) }.getOrDefault(false)) {
                return "ChatGPT sign-in is required for the hands-free intent gate"
            }
            return null
'''
new = '''            when (entry.provider) {
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
if old not in s:
    raise SystemExit('hands-free API-direct preflight anchor not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
print('Hands-free direct OpenAI API startup enabled')
