from pathlib import Path

# Keep the hands-free state switch exhaustive for upstream SessionState.
p = Path('app/src/main/kotlin/ai/closepaw/app/AgentService.kt')
s = p.read_text(encoding='utf-8')
old = '''                SessionState.Running, SessionState.Paused -> current.submit(Op.Supplement(command))
                SessionState.Shutdown -> runAgent(command)
'''
new = '''                SessionState.Running, SessionState.Paused, SessionState.TakeoverPending -> current.submit(Op.Supplement(command))
                SessionState.Shutdown -> runAgent(command)
'''
if old not in s:
    raise SystemExit('hands-free state patch anchor not found')
p.write_text(s.replace(old, new, 1), encoding='utf-8')

# An APK update kills the foreground microphone service but preserves the enabled preference.
# When the user next opens ClosePaw, re-issue ACTION_START if hands-free was enabled. setEnabled(true)
# is safe when the service is already alive because HandsFreeVoiceService guards against a second
# listener job.
main = Path('app/src/main/kotlin/ai/closepaw/app/MainActivity.kt')
main_text = main.read_text(encoding='utf-8')
main_anchor = '''    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
'''
main_replacement = '''    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (ai.closepaw.ui.capsule.voice.HandsFreeVoiceService.isEnabled(this)) {
            ai.closepaw.ui.capsule.voice.HandsFreeVoiceService.setEnabled(this, true)
        }
'''
if main_anchor not in main_text:
    raise SystemExit('MainActivity hands-free restart anchor not found')
main.write_text(main_text.replace(main_anchor, main_replacement, 1), encoding='utf-8')

# patch_voice_ux.py generates a JVM regression test. This upstream app exposes JUnit 4 in the
# unit-test classpath, not kotlin-test, so normalize the generated imports before Gradle compiles it.
t = Path('app/src/test/kotlin/ai/closepaw/ui/capsule/voice/VoiceHttpErrorMappingTest.kt')
if t.exists():
    text = t.read_text(encoding='utf-8')
    text = text.replace('import kotlin.test.Test\n', 'import org.junit.Test\n')
    text = text.replace('import kotlin.test.assertEquals\n', 'import org.junit.Assert.assertEquals\n')
    t.write_text(text, encoding='utf-8')

print('Hands-free restart/state + voice test compatibility fixes applied')
