import os
import re

MIGRATIONS = {
    'core.base_agent': 'core.foundation.base_agent',
    'core.session_registry': 'core.foundation.session_registry',
    'core.canonical': 'core.foundation.canonical',
    'core.runtime_paths': 'core.foundation.runtime_paths',
    'core.element_finder': 'core.os_utils.element_finder',
    'core.os_executor': 'core.os_utils.os_executor',
    'core.perception': 'core.os_utils.perception',
    'core.uia_executor': 'core.os_utils.uia_executor',
    'core.runtime_store': 'core.state.runtime_store',
    'core.snapshot_store': 'core.state.snapshot_store',
    'core.state_manager': 'core.state.state_manager',
    'core.state_snapshot': 'core.state.state_snapshot',
    
    # Stage B
    'core.ipc_serializer': 'core.ipc.ipc_serializer',
    'core.ipc_transport': 'core.ipc.ipc_transport',
    'core.bridge_server': 'core.ipc.bridge_server',
    'core.effect_reconciler': 'core.transaction.effect_reconciler',
    'core.effect_wal': 'core.transaction.effect_wal',
    'core.panic_manager': 'core.transaction.panic_manager',
    'core.transaction_manager': 'core.transaction.transaction_manager',
    
    # Stage C
    'core.causal_scheduler': 'core.orchestration.causal_scheduler',
    'core.llm_router': 'core.orchestration.llm_router',
    'core.step_executor': 'core.orchestration.step_executor',
    'core.task_manager': 'core.orchestration.task_manager',
    'core.task_parser': 'core.orchestration.task_parser',
    
    'core.divergence_analyzer': 'core.replay.divergence_analyzer',
    'core.event_recorder': 'core.replay.event_recorder',
    'core.replay_cursor': 'core.replay.replay_cursor',
    
    'core.synchronization': 'core.sync.synchronization',
    
    # Stage D
    'core.brain': 'core.runtime.brain',
    'core.capability_broker': 'core.runtime.capability_broker',
    'core.execution_sandbox': 'core.runtime.execution_sandbox',
    'core.resource_governor': 'core.runtime.resource_governor',
    'core.runtime_auditor': 'core.runtime.runtime_auditor',
    'core.runtime_supervisor': 'core.runtime.runtime_supervisor',
    'core.syscall_gate': 'core.runtime.syscall_gate',
    'core.worker_runtime': 'core.runtime.worker_runtime',
    'core.agent_context': 'core.runtime.agent_context',
    'core.kernel_supervisor': 'core.runtime.kernel_supervisor',
    'core.worker_protocol': 'core.ipc.worker_protocol',
    'core.windows_job_objects': 'core.os_utils.windows_job_objects',
    'core.log_manager': 'core.os_utils.log_manager',
    'core.tool_result': 'core.contracts.tool_result',
    'core.version': 'core.foundation.version'
}

def update_imports(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    original = content
    for old_mod, new_mod in MIGRATIONS.items():
        # Replace 'from core.module import ...'
        content = re.sub(rf'^from\s+{old_mod}\s+import', f'from {new_mod} import', content, flags=re.MULTILINE)
        # Replace 'import core.module'
        content = re.sub(rf'^import\s+{old_mod}(\s|$)', rf'import {new_mod}\1', content, flags=re.MULTILINE)

    if content != original:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"Updated: {filepath}")

def main():
    root_dirs = ['core', 'agents', 'ui', 'vision', 'workers', 'tests', '.']
    for root_dir in root_dirs:
        if root_dir == '.':
            files = [f for f in os.listdir('.') if os.path.isfile(f) and f.endswith('.py')]
            for f in files:
                update_imports(f)
            continue
        
        for dirpath, _, filenames in os.walk(root_dir):
            if '__pycache__' in dirpath:
                continue
            for f in filenames:
                if f.endswith('.py'):
                    update_imports(os.path.join(dirpath, f))

if __name__ == '__main__':
    main()
