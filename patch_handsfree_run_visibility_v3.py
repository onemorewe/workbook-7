from pathlib import Path

# Apply the substantive Jarvis visibility patch against the actual upstream layout and normalize
# ClosePaw's @JvmInline SessionId to its String value everywhere the UI/run ledger needs text keys.
source_path = Path('..') / 'patch_handsfree_run_visibility.py'
source = source_path.read_text(encoding='utf-8')

old_boundary = "end = a.find('\\n    fun runAgent(', start)"
new_boundary = "end = a.find('\\n    fun stopAgent()', start)"
if old_boundary not in source:
    raise SystemExit('Expected submitHandsFreeCommand boundary anchor missing')
source = source.replace(old_boundary, new_boundary, 1)

# AgentSession.sessionId is ai.closepaw.protocol.SessionId, not String.
# Convert to .value at the boundary where we store/display/correlate it.
for old, new in (
    ('current.sessionId', 'current.sessionId.value'),
    ('newSession.sessionId', 'newSession.sessionId.value'),
    ('agentSession.sessionId', 'agentSession.sessionId.value'),
):
    source = source.replace(old, new)

exec(compile(source, str(source_path), 'exec'))
