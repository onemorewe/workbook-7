from pathlib import Path

# Keep the substantive patch in one place, but correct the method-boundary assumption before
# executing it. In upstream AgentService, runAgent() is declared before submitHandsFreeCommand(),
# while stopAgent() follows submitHandsFreeCommand().
source_path = Path('..') / 'patch_handsfree_run_visibility.py'
source = source_path.read_text(encoding='utf-8')
old = "end = a.find('\\n    fun runAgent(', start)"
new = "end = a.find('\\n    fun stopAgent()', start)"
if old not in source:
    raise SystemExit('Expected submitHandsFreeCommand boundary anchor missing from visibility patch')
source = source.replace(old, new, 1)
exec(compile(source, str(source_path), 'exec'))
