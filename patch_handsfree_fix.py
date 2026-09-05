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

# patch_voice_ux.py generates a JVM regression test. This upstream app exposes JUnit 4 in the
# unit-test classpath, not kotlin-test, so normalize the generated imports before Gradle compiles it.
t = Path('app/src/test/kotlin/ai/closepaw/ui/capsule/voice/VoiceHttpErrorMappingTest.kt')
if t.exists():
    text = t.read_text(encoding='utf-8')
    text = text.replace('import kotlin.test.Test\n', 'import org.junit.Test\n')
    text = text.replace('import kotlin.test.assertEquals\n', 'import org.junit.Assert.assertEquals\n')
    t.write_text(text, encoding='utf-8')

print('Hands-free state + voice test compatibility fixes applied')
