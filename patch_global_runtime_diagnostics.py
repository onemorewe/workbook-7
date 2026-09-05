from pathlib import Path

root = Path('.')


def replace_once(path: Path, old: str, new: str):
    text = path.read_text(encoding='utf-8')
    if old not in text:
        raise SystemExit(f'Patch anchor not found in {path}: {old[:120]!r}')
    path.write_text(text.replace(old, new, 1), encoding='utf-8')


# The private relay used to be configured only from HandsFreeVoiceService.onCreate().
# That made the most important failure mode invisible: if hands-free never starts,
# ordinary UI / Accessibility activity cannot emit remote diagnostics either.
main = root / 'app/src/main/kotlin/ai/closepaw/app/MainActivity.kt'
replace_once(
    main,
    '''    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
''',
    '''    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.configure(this)
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
            stage = "main-activity-created",
            message = "MainActivity created",
        )
''',
)

service = root / 'app/src/main/kotlin/ai/closepaw/app/AgentService.kt'
replace_once(
    service,
    '''    override fun onServiceConnected() {
        super.onServiceConnected()
''',
    '''    override fun onServiceConnected() {
        super.onServiceConnected()
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.configure(this)
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
            stage = "agent-service-connected",
            message = "Accessibility AgentService connected",
        )
''',
)
replace_once(
    service,
    '''    override fun onInterrupt() {
        Log.w(TAG, "AgentService interrupted")
    }
''',
    '''    override fun onInterrupt() {
        Log.w(TAG, "AgentService interrupted")
        ai.closepaw.ui.capsule.voice.HandsFreeDebugRelay.publish(
            stage = "agent-service-interrupted",
            level = "warn",
            message = "Accessibility AgentService interrupted",
        )
    }
''',
)

print('Global runtime diagnostics patch applied')
