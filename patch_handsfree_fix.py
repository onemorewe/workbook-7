from pathlib import Path
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
print('Hands-free state fix applied')
