from pathlib import Path

for rel in (
    'app/src/test/kotlin/ai/closepaw/llm/OpenAiApiCostGuardTest.kt',
    'app/src/test/kotlin/ai/closepaw/ui/capsule/voice/UnifiedVoiceFlowContractTest.kt',
):
    path = Path(rel)
    if not path.exists():
        raise SystemExit(f'Expected unit test missing: {rel}')
    text = path.read_text(encoding='utf-8')
    text = text.replace('import kotlin.test.Test\n', 'import org.junit.Test\n')
    text = text.replace('import kotlin.test.assertTrue\n', 'import org.junit.Assert.assertTrue\n')
    text = text.replace('import kotlin.test.assertFalse\n', 'import org.junit.Assert.assertFalse\n')
    if 'kotlin.test' in text:
        raise SystemExit(f'Unsupported kotlin.test import remains in {rel}')
    path.write_text(text, encoding='utf-8')

print('New JVM tests normalized to upstream JUnit4 test runtime')
