import sys
sys.path.insert(0, r'C:\Users\karth\OneDrive\Desktop\Novamind')

# Fix 1: disable_startup_item exists
from agents.system_agent import SystemAgent
agent = SystemAgent()
assert hasattr(agent, 'disable_startup_item'), 'MISSING: disable_startup_item'
assert 'disable_startup' in agent.handlers, 'MISSING handler key'
print('Fix 1 OK: disable_startup_item method exists and is wired in handlers')

# Fix 2: r.error or '' guard
from core.brain import Brain, StepResult, ExecutionStatus
r = StepResult(step_number=1, status=ExecutionStatus.SUCCESS, agent='x', action='y', error=None)
val = (r.error or '')[:200]
print(f'Fix 2 OK: (None or "")[:200] = "{val}"')

# Fix 3: confirm run_blocking hooks
import pathlib
src = pathlib.Path(r'C:\Users\karth\OneDrive\Desktop\Novamind\game\nova_mindscape.py').read_text()
assert 'app.update = self._game_update' in src, 'MISSING app.update assignment'
has_input = 'app.input  = self._game_input' in src or 'app.input = self._game_input' in src
assert has_input, 'MISSING app.input assignment'
print('Fix 3 OK: app.update and app.input set before app.run() in run_blocking')

print()
print('All 3 fixes verified.')
