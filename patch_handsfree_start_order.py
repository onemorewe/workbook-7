from pathlib import Path

p = Path('app/src/main/kotlin/ai/closepaw/ui/capsule/voice/HandsFreeVoiceService.kt')
s = p.read_text(encoding='utf-8')
old = '''            val intent = Intent(app, HandsFreeVoiceService::class.java).apply { action = ACTION_START }
            val startError = runCatching { ContextCompat.startForegroundService(app, intent) }.exceptionOrNull()
            if (startError != null) {
                val message = "Could not start microphone service: ${startError.message ?: startError::class.java.simpleName}"
                prefs.edit().putBoolean(KEY_ENABLED, false).apply()
                _lastError.value = message
                _runtimeStatus.value = "Error"
                return message
            }

            prefs.edit().putBoolean(KEY_ENABLED, true).apply()
            _lastError.value = null
'''
new = '''            // Publish enabled before starting the service: onStartCommand reads this flag immediately.
            // Roll it back if Android rejects startForegroundService.
            prefs.edit().putBoolean(KEY_ENABLED, true).apply()
            val intent = Intent(app, HandsFreeVoiceService::class.java).apply { action = ACTION_START }
            val startError = runCatching { ContextCompat.startForegroundService(app, intent) }.exceptionOrNull()
            if (startError != null) {
                val message = "Could not start microphone service: ${startError.message ?: startError::class.java.simpleName}"
                prefs.edit().putBoolean(KEY_ENABLED, false).apply()
                _lastError.value = message
                _runtimeStatus.value = "Error"
                return message
            }

            _lastError.value = null
'''
if old not in s:
    raise SystemExit('start ordering patch anchor not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')
print('Hands-free start ordering fixed')
