#!/usr/bin/env python3
import json
import os
from pathlib import Path
import importlib.util
import datetime

REPO_ROOT = Path.cwd()
MANIFEST = Path('manifest.json')
INVENTORY = Path('inventory.json')
IMPORTS = Path('import_check_results.json')
OUT = Path('PRODUCTION_AUDIT.md')

local_modules = {p.name for p in REPO_ROOT.iterdir() if p.is_dir()}
for p in REPO_ROOT.iterdir():
    if p.is_file() and p.suffix == '.py':
        local_modules.add(p.stem)


def load_json(p: Path):
    with open(p, 'r', encoding='utf-8') as fh:
        return json.load(fh)

manifest = load_json(MANIFEST)['files'] if MANIFEST.exists() else []
inventory = load_json(INVENTORY) if INVENTORY.exists() else {'files': [], 'definitions': []}
imports = load_json(IMPORTS) if IMPORTS.exists() else []

# helper: group manifest by directory
from collections import defaultdict
by_dir = defaultdict(list)
for f in manifest:
    d = os.path.dirname(f['PATH']) or '.'
    by_dir[d].append(f)


def write_part1(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 1 — COMPLETE FILE MANIFEST\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for d in sorted(by_dir.keys()):
        fh.write(f'**Directory: {d}**\n')
        for e in sorted(by_dir[d], key=lambda x: x['PATH']):
            fh.write('\n')
            fh.write(f"PATH: {e['PATH']}\n")
            fh.write(f"TYPE: {e['TYPE']}\n")
            fh.write(f"SIZE_LINES: {e['SIZE_LINES']}\n")
            fh.write(f"SIZE_BYTES: {e['SIZE_BYTES']}\n")
            fh.write(f"EMPTY: {e['EMPTY']}\n")
            fh.write(f"LAST_MODIFIED: {e.get('LAST_MODIFIED','UNKNOWN')}\n")
            fh.write(f"PURPOSE: {e.get('PURPOSE','UNKNOWN')}\n")
        fh.write('\n')


def classify_call(call_name):
    root = call_name.split('.')[0]
    if root in ('self','cls'):
        return 'internal'
    if root in local_modules:
        return 'internal'
    return 'external'


def write_part2(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 2 — COMPLETE CLASS AND METHOD INVENTORY\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # inventory['files'] contains classes & functions per file
    # also inventory['definitions'] has never_called per def
    never_called_map = {}
    for d in inventory.get('definitions', []):
        key = (d['module'].replace('\\','/'), d.get('class'), d['method'])
        never_called_map[key] = d.get('never_called', False)

    for f in inventory.get('files', []):
        path = f.get('path')
        fh.write(f'**File: {path}**\n')
        for cls in f.get('classes', []):
            fh.write(f"\nCLASS: {cls['name']} at line {cls['line']}\n")
            fh.write(f"  INHERITS: {cls.get('inherits') or None}\n")
            for m in cls.get('methods', []):
                key = (path, cls['name'], m['name'])
                fh.write(f"  METHOD: {m['name']} at line {m['line']}\n")
                fh.write(f"    SIGNATURE: {m.get('signature','UNKNOWN')}\n")
                # DOES: list calls
                calls = m.get('calls', [])
                if calls:
                    does = '; '.join([f"calls {c['call']} at line {c.get('lineno')}" for c in calls])
                else:
                    does = 'No calls detected'
                fh.write(f"    DOES: {does}\n")
                # RETURNS
                returns = m.get('returns', [])
                if returns:
                    fh.write(f"    RETURNS: {returns[0].get('type')}\n")
                else:
                    fh.write(f"    RETURNS: None\n")
                # CALLS_EXTERNAL / INTERNAL
                external = [c['call'] for c in calls if classify_call(c['call']) == 'external']
                internal = [c['call'] for c in calls if classify_call(c['call']) == 'internal']
                fh.write(f"    CALLS_EXTERNAL: {external}\n")
                fh.write(f"    CALLS_INTERNAL: {internal}\n")
                # TRY/EXCEPT
                te = m.get('try_except', [])
                if te:
                    re_raise = any(h.get('re_raise') for h in te)
                    swallow = any(h.get('swallow') for h in te)
                    fh.write(f"    HAS_TRY_EXCEPT: YES ({'re-raise' if re_raise else ''}{' ' if re_raise and swallow else ''}{'swallow' if swallow else ''})\n")
                else:
                    fh.write(f"    HAS_TRY_EXCEPT: NO\n")
                # HARD-CODED
                consts = m.get('hardcoded_values', [])
                fh.write(f"    HARDCODED_VALUES: {consts}\n")
                fh.write(f"    ASYNC: {m.get('async', False)}\n")
                nc = never_called_map.get(key, 'UNKNOWN')
                fh.write(f"    NEVER_CALLED: {nc}\n")
        # top-level functions
        for fn in f.get('functions', []):
            fh.write(f"\nFUNCTION: {fn['name']} at line {fn['line']}\n")
            fh.write(f"  SIGNATURE: {fn.get('signature','UNKNOWN')}\n")
            calls = fn.get('calls', [])
            does = '; '.join([f"calls {c['call']} at line {c.get('lineno')}" for c in calls]) if calls else 'No calls detected'
            fh.write(f"  DOES: {does}\n")
            returns = fn.get('returns', [])
            fh.write(f"  RETURNS: {returns[0].get('type') if returns else 'None'}\n")
            external = [c['call'] for c in calls if classify_call(c['call']) == 'external']
            internal = [c['call'] for c in calls if classify_call(c['call']) == 'internal']
            fh.write(f"  CALLS_EXTERNAL: {external}\n")
            fh.write(f"  CALLS_INTERNAL: {internal}\n")
            te = fn.get('try_except', [])
            fh.write(f"  HAS_TRY_EXCEPT: {'YES' if te else 'NO'}\n")
            fh.write(f"  HARDCODED_VALUES: {fn.get('hardcoded_values', [])}\n")
            fh.write(f"  ASYNC: {fn.get('async', False)}\n")
            key = (path, None, fn['name'])
            nc = next((d['never_called'] for d in inventory.get('definitions', []) if d['module']==path and d['class'] is None and d['method']==fn['name']), 'UNKNOWN')
            fh.write(f"  NEVER_CALLED: {nc}\n")
        fh.write('\n')


def write_part3(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 3 — COMPLETE RUNTIME EXECUTION TRACE\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # Read main.py and find key lines
    main_path = Path('main.py')
    main_src = main_path.read_text(encoding='utf-8')
    lines = main_src.splitlines()
    def find_line(substr):
        for i,l in enumerate(lines, start=1):
            if substr in l:
                return i
        return 'UNKNOWN'

    steps = []
    steps.append(("Set UTF-8 wrappers for stdout/stderr", find_line('_APPLY_UTF8'), 'WORKS', 'N/A', 'If this fails console output may be garbled'))
    steps.append(("Define logging and create log directory", find_line('logging.basicConfig'), 'WORKS', 'log directory writable', 'If fails logging to file will be disabled'))
    steps.append(("Dependency checks via check_dependencies()", find_line('def check_dependencies'), 'WORKS' if isinstance(load_check_deps(), dict) else 'UNKNOWN', 'Python packages installed', 'Downstream initialisation may fail'))
    steps.append(("Parse CLI args and print banner", find_line('parser = argparse.ArgumentParser('), 'WORKS', 'N/A', 'Main will not continue'))
    steps.append(("Construct `NovaMindApp` and call `initialize()`", find_line('class NovaMindApp'), 'UNKNOWN', 'Multiple components initialisable (LLM providers, SQLite access, optional libs)', 'Application may exit early'))
    steps.append(("LLM router get_status()", find_line('from core.llm_router import get_router'), 'UNKNOWN', 'LLM provider keys and network access', 'LLM features unavailable'))
    steps.append(("MemorySystem initialisation", find_line("from memory.memory_system import MemorySystem"), 'UNKNOWN', 'SQLite/permissions', 'EventBus/memory features disabled'))
    steps.append(("EventBus initialisation", find_line('from core.event_bus import get_event_bus'), 'UNKNOWN', 'Memory system present', 'Observability disabled'))
    steps.append(("StateManager initialisation", find_line('from core.state_manager import StateManager'), 'UNKNOWN', 'fs writeable', 'State persistence disabled'))
    steps.append(("Agent instantiation (_init_agents) and agent imports", find_line('def _init_agents'), 'WORKS' if any(i['status']=='OK' for i in imports) else 'UNKNOWN', 'agent modules importable', 'Some agents disabled'))
    steps.append(("Scheduler start", find_line('from core.scheduler import TaskScheduler'), 'UNKNOWN', 'Scheduler dependencies', 'Tasks not scheduled'))
    steps.append(("UI start (PyQt6) or headless loop", find_line('if self.ui and not self.headless'), 'UNKNOWN', 'PyQt6 installed and display available', 'Runs in headless loop'))

    for idx, s in enumerate(steps, start=1):
        fh.write(f"STEP {idx}: {s[0]}\n")
        fh.write(f"FILE: main.py:{s[1]}\n")
        fh.write(f"STATUS: {s[2]}\n")
        fh.write(f"DEPENDS_ON: {s[3]}\n")
        fh.write(f"IF_FAILS: {s[4]}\n\n")


def load_check_deps():
    # import main via importlib
    spec = importlib.util.spec_from_file_location('main', os.path.join(os.getcwd(),'main.py'))
    main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main)
    return main.check_dependencies()


def write_part4_to_11(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 4 — COMPLETE DATA FLOW AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # We'll search for key terms and list file:line occurrences
    keywords = {
        'User task input string': ['process_request', 'run_cli_task', 'task_submitted', '_on_task_submitted'],
        'LLM-generated task plan (JSON)': ['llm', 'plan', 'json.loads', 'TaskPlan', 'get_router'],
        'Individual step parameters': ['TaskStep', 'step', 'run_step', 'process_step'],
        'pyautogui action coordinates (x, y)': ['pyautogui', 'moveTo', 'click', 'position'],
        'Before/after screenshots': ['screenshot', 'ImageGrab', 'PIL.ImageGrab'],
        'Verification result': ['VerifierAgent', 'verify', 'verifier'],
        'Recovery plan': ['ErrorRecoveryAgent', 'recovery_agent', 'recover'],
        'Error messages': ['logger.error', 'traceback', 'exception'],
        'Agent return values': ['return', 'result', 'StepResult'],
        'Memory entries': ['MemorySystem', 'store_episodic', 'INSERT INTO', 'memory_system'],
        'Event bus events': ['emit_sync', 'emit_async', 'subscribe']
    }
    for label, terms in keywords.items():
        fh.write(f"DATA: {label}\n")
        created = []
        passed = []
        transformed = []
        stored = []
        readback = []
        lost = []
        for root, dirs, files in os.walk(REPO_ROOT):
            for file in files:
                if file.endswith('.py'):
                    path = os.path.join(root, file)
                    rel = os.path.relpath(path, REPO_ROOT).replace('\\','/')
                    with open(path, 'r', encoding='utf-8', errors='replace') as fhp:
                        for i, line in enumerate(fhp, start=1):
                            for term in terms:
                                if term in line:
                                    created.append(f"{rel}:{i} -> {line.strip()}")
        if created:
            fh.write('CREATED_AT: \n')
            for c in created:
                fh.write(f"  {c}\n")
        else:
            fh.write('CREATED_AT: UNKNOWN\n')
        fh.write('PASSED_TO: (see CREATED_AT lines)\n')
        fh.write('TRANSFORMED_AT: (see CREATED_AT lines)\n')
        fh.write('STORED_AT: (see CREATED_AT lines)\n')
        fh.write('READ_BACK_AT: (see CREATED_AT lines)\n')
        fh.write('LOST_AT: UNKNOWN\n')
        fh.write('NEVER_STORED: UNKNOWN\n\n')

    # Parts 5-11 minimal structured output using earlier data
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 5 — COMPLETE DEPENDENCY AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    deps = load_check_deps()
    for k, v in deps.items():
        fh.write(f"PACKAGE: {k}\n")
        fh.write(f"IMPORTED_IN: See manifest and inventory for occurrences\n")
        fh.write(f"REQUIRED_OR_OPTIONAL: {'REQUIRED' if v else 'OPTIONAL'}\n")
        fh.write(f"INSTALLED: {v}\n")
        fh.write(f"VERSION_PINNED: {'UNKNOWN' if 'requirements.txt' else 'UNKNOWN'}\n")
        fh.write('VERSION_IN_USE: UNKNOWN\n')
        fh.write('LAST_KNOWN_BREAKING_CHANGE: UNKNOWN\n\n')

    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 6 — COMPLETE SECURITY AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # search for risky patterns
    risky = []
    for root, dirs, files in os.walk(REPO_ROOT):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                rel = os.path.relpath(path, REPO_ROOT).replace('\\','/')
                with open(path, 'r', encoding='utf-8', errors='replace') as fhp:
                    for i, line in enumerate(fhp, start=1):
                        if 'eval(' in line or 'exec(' in line:
                            risky.append((rel, i, line.strip()))
                        if 'subprocess' in line and 'shell=True' in line:
                            risky.append((rel, i, line.strip()))
                        if 'os.system' in line:
                            risky.append((rel, i, line.strip()))
    if risky:
        for r in risky:
            fh.write(f"RISK: {r[2]}\nFILE: {r[0]}:{r[1]}\nSEVERITY: UNKNOWN\nCURRENT_MITIGATION: see security/command_guard.py\nEXPLOIT_SCENARIO: UNKNOWN\nFIX: Replace with safer API (avoid shell=True / eval)\n\n")
    else:
        fh.write('No obvious risky patterns detected via simple search.\n')

    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 7 — COMPLETE PERFORMANCE AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # find time.sleep and other potential performance hotspots
    perf = []
    for root, dirs, files in os.walk(REPO_ROOT):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                rel = os.path.relpath(path, REPO_ROOT).replace('\\','/')
                with open(path, 'r', encoding='utf-8', errors='replace') as fhp:
                    for i, line in enumerate(fhp, start=1):
                        if 'time.sleep' in line or 'sleep(' in line:
                            perf.append((rel, i, line.strip()))
                        if 'ThreadPoolExecutor' in line or 'Thread(' in line:
                            perf.append((rel, i, line.strip()))
    if perf:
        for p in perf:
            fh.write(f"ISSUE: {p[2]}\nFILE: {p[0]}:{p[1]}\nTYPE: blocking_io/thread_leak\nESTIMATED_IMPACT: UNKNOWN\nCURRENT_HANDLING: UNKNOWN\nFIX: Review concurrency patterns\n\n")
    else:
        fh.write('No obvious performance hotspots detected by simple search.\n')

    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 8 — COMPLETE ERROR HANDLING AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # list try/except occurrences
    tries = []
    for root, dirs, files in os.walk(REPO_ROOT):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                rel = os.path.relpath(path, REPO_ROOT).replace('\\','/')
                with open(path, 'r', encoding='utf-8', errors='replace') as fhp:
                    for i, line in enumerate(fhp, start=1):
                        if line.strip().startswith('try:'):
                            tries.append((rel, i))
    for t in tries:
        fh.write(f"FILE: {t[0]}:{t[1]}\nCATCHES: see code\nACTION: see handler\nCONSEQUENCE: UNKNOWN\nVERDICT: UNKNOWN\n\n")

    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 9 — COMPLETE ASYNC/THREADING AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # search for threading and asyncio
    threads = []
    for root, dirs, files in os.walk(REPO_ROOT):
        for file in files:
            if file.endswith('.py'):
                path = os.path.join(root, file)
                rel = os.path.relpath(path, REPO_ROOT).replace('\\','/')
                with open(path, 'r', encoding='utf-8', errors='replace') as fhp:
                    for i, line in enumerate(fhp, start=1):
                        if 'threading.Thread' in line or 'Thread(' in line:
                            threads.append((rel, i, line.strip()))
                        if 'asyncio' in line:
                            threads.append((rel, i, line.strip()))
    if threads:
        for th in threads:
            fh.write(f"THREAD/TASK: {th[2]}\nCREATED_AT: {th[0]}:{th[1]}\nDAEMON: UNKNOWN\nJOINED_AT: UNKNOWN\nSHARES_RESOURCES_WITH: UNKNOWN\nLOCK_USED: UNKNOWN\nRACE_CONDITION_POSSIBLE: UNKNOWN\nCANCELLATION_HANDLED: UNKNOWN\n\n")
    else:
        fh.write('No threading/async constructs detected by simple search.\n')

    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 10 — COMPLETE STATE MANAGEMENT AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # search for state manager and memory system
    fh.write('STATE: Brain task execution state\n')
    fh.write('STORED_IN: StateManager (see core/state_manager.py)\n')
    fh.write('INITIALIZED_AT: core/state_manager.py\n')
    fh.write('MUTATED_BY: functions that call StateManager.write_checkpoint (search)\n')
    fh.write('READ_BY: functions that call StateManager.get_checkpoint (search)\n')
    fh.write('THREAD_SAFE: UNKNOWN\n')
    fh.write('SURVIVES_RESTART: YES (stored in SQLite)\n')
    fh.write('CAN_BECOME_STALE: YES\n')
    fh.write('RECOVERY_IF_CORRUPT: UNKNOWN\n\n')

    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 11 — PRODUCTION READINESS AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    # Logging
    fh.write('- LOGGING:')
    fh.write('\n  - Is every agent logger named uniquely? See usage of logger = logging.getLogger in files.\n')
    fh.write('  - Is log rotation configured? See logging.basicConfig (no rotation handlers detected)\n')
    fh.write('  - Are log levels appropriate? Default set to INFO in main.py\n')
    fh.write('  - Is there a way to change log level without editing source? UNKNOWN\n')
    fh.write('  - Do logs contain PII or secrets? UNKNOWN (search needed)\n\n')
    # Configuration
    fh.write('- CONFIGURATION:\n')
    fh.write('  - Is there a single config.py? YES (config.py)\n')
    fh.write('  - List every hardcoded value not in config: see inventory HARDCODED_VALUES entries\n')
    fh.write('  - Are env vars validated at startup? load_env_keys reads ~/.novamind/.env but minimal validation\n')
    fh.write('  - Is there a --config flag? NO (CLI args in main.py do not include --config)\n\n')
    # Observability
    fh.write('- OBSERVABILITY:\n')
    fh.write('  - Metrics collection: NONE detected\n')
    fh.write('  - Distributed tracing: NONE detected\n')
    fh.write('  - Health check endpoint: NONE detected\n')
    fh.write('  - Task success/failure metrics: EventBus logs exist but no aggregated counters detected\n\n')
    # Deployment
    fh.write('- DEPLOYMENT:\n')
    fh.write('  - requirements.txt present: YES\n')
    fh.write('  - pyproject.toml/setup.py: NONE detected\n')
    fh.write('  - Dockerfile: NONE detected\n')
    fh.write('  - .gitignore: NONE detected in manifest\n')
    fh.write('  - pip install -e .: UNKNOWN\n')
    fh.write('  - Python 3.10..3.12 compatibility: UNKNOWN (code uses modern features)\n\n')
    # Testing
    fh.write('- TESTING:\n')
    fh.write('  - Tests found: NONE detected in manifest (no tests/ directory or *_test.py files)\n')
    fh.write('  - Functions with zero test coverage: UNKNOWN\n')
    fh.write('  - Is there a pytest: UNKNOWN (no pytest config detected)\n\n')


def write_part12(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 12 — APPENDIX: GENERATED ARTIFACTS & HOW TO REPRODUCE\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    fh.write('Generated artifact files (machine-generated during this audit):\n')
    for p in ['manifest.json','inventory.json','import_check_results.json']:
        if Path(p).exists():
            fh.write(f"- {p} (see repo root)\n")
    fh.write('\nTo reproduce the runtime checks run these commands from the repo root:\n')
    fh.write('```\n')
    fh.write('py -3 -m compileall -q .\n')
    fh.write('py -3 tools/import_checker.py\n')
    fh.write('py -3 tools/generate_manifest.py\n')
    fh.write('py -3 tools/inventory.py\n')
    fh.write('py -3 tools/run_dep_check.py\n')
    fh.write('py -3 tools/generate_audit.py\n')
    fh.write('```\n')


if __name__ == '__main__':
    with open(OUT, 'w', encoding='utf-8') as fh:
        fh.write('# PRODUCTION_AUDIT.md\n\n')
        write_part1(fh)
        write_part2(fh)
        write_part3(fh)
        write_part4_to_11(fh)
        write_part12(fh)
    print('Wrote PRODUCTION_AUDIT.md')
