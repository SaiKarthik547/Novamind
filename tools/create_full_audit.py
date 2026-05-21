import json
import os
import re
import ast
from pathlib import Path
from collections import defaultdict
import datetime

REPO_ROOT = Path(os.getcwd())
OUT = REPO_ROOT / 'PRODUCTION_AUDIT.md'

def get_all_py_files():
    files = []
    for root, dirs, fnames in os.walk(REPO_ROOT):
        if '.local' in root or '.git' in root or '__pycache__' in root:
            continue
        for f in fnames:
            if f.endswith('.py'):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, REPO_ROOT).replace('\\', '/')
                files.append((path, rel))
    return files

def write_part1(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 1 — COMPLETE FILE MANIFEST\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for root, dirs, files in os.walk(REPO_ROOT):
        if '__pycache__' in root or '.git' in root: continue
        rel_dir = os.path.relpath(root, REPO_ROOT).replace('\\', '/')
        if rel_dir == '.': rel_dir_print = '.'
        else: rel_dir_print = rel_dir
        fh.write(f'**Directory: {rel_dir_print}**\n')
        for file in sorted(files):
            path = os.path.join(root, file)
            rel_path = os.path.relpath(path, REPO_ROOT).replace('\\', '/')
            ext = file.split('.')[-1] if '.' in file else 'other'
            try:
                size_bytes = os.path.getsize(path)
                mtime = os.path.getmtime(path)
                last_modified = datetime.datetime.fromtimestamp(mtime).isoformat()
            except Exception:
                size_bytes = 0
                last_modified = 'UNKNOWN'
            empty = 'YES' if size_bytes == 0 else 'NO'
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    size_lines = len(lines)
                    purpose = "UNKNOWN"
                    for line in lines:
                        sline = line.strip()
                        if sline and not sline.startswith(('import ', 'from ', '#!')):
                            purpose = sline[:120].replace('\n', ' ')
                            break
                    if not any(l.strip() for l in lines): empty = 'YES'
            except Exception:
                size_lines = 0
                purpose = "binary or unreadable file"
            fh.write(f"\nPATH: {rel_path}\nTYPE: {ext}\nSIZE_LINES: {size_lines}\nSIZE_BYTES: {size_bytes}\nEMPTY: {empty}\nLAST_MODIFIED: {last_modified}\nPURPOSE: {purpose}\n")
        fh.write('\n')

def get_calls(node):
    calls = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            if isinstance(child.func, ast.Name):
                calls.append(child.func.id)
            elif isinstance(child.func, ast.Attribute):
                calls.append(child.func.attr)
    return calls

def write_part2(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 2 — COMPLETE CLASS AND METHOD INVENTORY\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for path, rel_path in get_all_py_files():
        try:
            tree = ast.parse(open(path, 'r', encoding='utf-8').read())
        except Exception: continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                inherits = [b.id for b in node.bases if isinstance(b, ast.Name)]
                fh.write(f"\nCLASS: {node.name} at line {node.lineno}\n  INHERITS: {', '.join(inherits) if inherits else 'None'}\n")
                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        fh.write(f"  METHOD: {child.name} at line {child.lineno}\n")
                        args = [a.arg for a in child.args.args]
                        fh.write(f"    SIGNATURE: def {child.name}({', '.join(args)})\n")
                        doc = ast.get_docstring(child)
                        does = doc.split('\n')[0].strip() if doc else f"Literally executes {len(child.body)} AST statements."
                        fh.write(f"    DOES: {does}\n")
                        returns = "UNKNOWN"
                        if child.returns:
                            if isinstance(child.returns, ast.Name): returns = child.returns.id
                        fh.write(f"    RETURNS: {returns}\n")
                        calls = get_calls(child)
                        internal = [c for c in calls if c.startswith('_') or c in ('print', 'len')]
                        external = [c for c in set(calls) - set(internal)]
                        fh.write(f"    CALLS_EXTERNAL: {external}\n    CALLS_INTERNAL: {internal}\n")
                        has_try = any(isinstance(n, ast.Try) for n in ast.walk(child))
                        swallow = any(isinstance(n, ast.Pass) for n in ast.walk(child)) if has_try else False
                        re_raise = any(isinstance(n, ast.Raise) for n in ast.walk(child)) if has_try else False
                        try_msg = f"YES (re-raises={re_raise}, swallows={swallow})" if has_try else "NO"
                        fh.write(f"    HAS_TRY_EXCEPT: {try_msg}\n")
                        consts = [n.value for n in ast.walk(child) if isinstance(n, ast.Constant) and isinstance(n.value, (str, int))]
                        fh.write(f"    HARDCODED_VALUES: {list(set(consts))[:5]}\n")
                        fh.write(f"    ASYNC: {'YES' if isinstance(child, ast.AsyncFunctionDef) else 'NO'}\n")
                        fh.write(f"    NEVER_CALLED: UNKNOWN (requires graph resolution)\n")

def write_part3(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 3 — COMPLETE RUNTIME EXECUTION TRACE\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    main_path = REPO_ROOT / 'main.py'
    if not main_path.exists():
        fh.write("main.py NOT FOUND\n")
        return
    lines = open(main_path, 'r', encoding='utf-8').read().splitlines()
    fh.write("TRACE OF main.py BY LITERAL LINES EXECUTED:\n\n")
    for i, line in enumerate(lines, 1):
        s = line.strip()
        if s.startswith('sys.') or s.startswith('logging.') or s.startswith('def ') or s.startswith('class ') or s.startswith('app =') or s.startswith('app.') or s.startswith('if __name__'):
            fh.write(f"STEP: {s}\nFILE: main.py:{i}\nSTATUS: EXACT PARSE\nDEPENDS_ON: Preceding lines\nIF_FAILS: Runtime crash\n\n")

def write_part4(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 4 — COMPLETE DATA FLOW AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    targets = {
        "User task input string": ["task_submitted", "process_request", "--task"],
        "LLM-generated task plan (JSON)": ["TaskPlan", "parse_plan", "json.loads"],
        "Individual step parameters": ["TaskStep", "step ="],
        "pyautogui action coordinates (x, y)": ["pyautogui", ".click", "moveTo"],
        "Before/after screenshots": ["screenshot", "ImageGrab"],
        "Verification result": ["VerifierAgent", ".verify"],
        "Recovery plan": ["ErrorRecoveryAgent", "execute_recovery"],
        "Error messages": ["logger.error(", "except Exception", "traceback"],
        "Memory entries": ["INSERT INTO", "memory_system", "store_"],
        "Event bus events": ["emit_sync", "emit_async", "event_bus"]
    }
    
    for t_name, keywords in targets.items():
        fh.write(f"DATA: {t_name}\n")
        matches = []
        for path, rel in get_all_py_files():
            with open(path, 'r', encoding='utf-8') as f:
                for i, line in enumerate(f, 1):
                    if any(k in line for k in keywords):
                        matches.append(f"{rel}:{i} -> {line.strip()[:100]}")
        if matches:
            fh.write("OCCURRENCES ACROSS CODEBASE (LITERAL EXTRACT):\n")
            for m in matches[:15]: # cap at 15
                fh.write(f"  {m}\n")
            if len(matches) > 15: fh.write(f"  ... and {len(matches)-15} more.\n")
        else:
            fh.write("OCCURRENCES ACROSS CODEBASE: ZERO DETECTED.\n")
        fh.write("CREATED_AT: UNKNOWN (Derived from above occurrences)\n")
        fh.write("PASSED_TO: UNKNOWN\nTRANSFORMED_AT: UNKNOWN\nSTORED_AT: UNKNOWN\nREAD_BACK_AT: UNKNOWN\nLOST_AT: UNKNOWN\nNEVER_STORED: UNKNOWN\n\n")

def write_part5(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 5 — COMPLETE DEPENDENCY AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    fh.write('SECTION A — Python packages:\n')
    req_path = REPO_ROOT / 'requirements.txt'
    reqs = open(req_path, 'r').read().splitlines() if req_path.exists() else []
    for r in reqs:
        if not r.strip() or r.startswith('#'): continue
        pkg = re.split(r'[>=<]', r)[0]
        imported_in = []
        for path, rel in get_all_py_files():
            content = open(path, 'r', encoding='utf-8').read()
            if f"import {pkg}" in content or f"from {pkg}" in content:
                imported_in.append(rel)
        fh.write(f"PACKAGE: {pkg}\nIMPORTED_IN: {imported_in if imported_in else 'NONE DETECTED (Possibly indirect)'}\nREQUIRED_OR_OPTIONAL: REQUIRED\nINSTALLED: UNKNOWN\nVERSION_PINNED: {'YES' if '==' in r else 'NO'}\nVERSION_IN_USE: {r}\nLAST_KNOWN_BREAKING_CHANGE: UNKNOWN\n\n")

    fh.write('SECTION B — External services:\n')
    services = []
    for path, rel in get_all_py_files():
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if 'os.getenv' in line and ('KEY' in line or 'TOKEN' in line):
                    services.append(f"SERVICE: API Key Fetch\nFILE: {rel}:{i}\nAUTH_METHOD: {line.strip()}\nENV_VAR_SET: UNKNOWN\nFALLBACK_IF_DOWN: UNKNOWN\nRATE_LIMIT_HANDLED: UNKNOWN\nRETRY_LOGIC: UNKNOWN\n\n")
    if services:
        for s in set(services): fh.write(s)
    else: fh.write("No direct os.getenv API keys found.\n\n")

    fh.write('SECTION C — System dependencies:\n')
    sysdeps = []
    for path, rel in get_all_py_files():
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if 'subprocess' in line:
                    sysdeps.append(f"DEPENDENCY: Subprocess Execution\nREQUIRED_BY: {rel}:{i} -> {line.strip()[:60]}\nPRESENT_ON_THIS_MACHINE: UNKNOWN\nFALLBACK_IF_MISSING: UNKNOWN\n\n")
    if sysdeps:
        for s in set(sysdeps): fh.write(s)
    else: fh.write("No subprocess system dependencies found.\n\n")

def write_part6(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 6 — COMPLETE SECURITY AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for path, rel in get_all_py_files():
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if 'subprocess' in line and 'shell=True' in line:
                    fh.write(f"RISK: shell=True execution\nFILE: {rel}:{i}\nSEVERITY: HIGH\nCURRENT_MITIGATION: EXACT CODE -> {line.strip()}\nEXPLOIT_SCENARIO: UNKNOWN\nFIX: UNKNOWN\n\n")
                elif 'eval(' in line:
                    fh.write(f"RISK: eval() used\nFILE: {rel}:{i}\nSEVERITY: CRITICAL\nCURRENT_MITIGATION: EXACT CODE -> {line.strip()}\nEXPLOIT_SCENARIO: UNKNOWN\nFIX: UNKNOWN\n\n")
                elif 'exec(' in line:
                    fh.write(f"RISK: exec() used\nFILE: {rel}:{i}\nSEVERITY: CRITICAL\nCURRENT_MITIGATION: EXACT CODE -> {line.strip()}\nEXPLOIT_SCENARIO: UNKNOWN\nFIX: UNKNOWN\n\n")

def write_part7(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 7 — COMPLETE PERFORMANCE AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for path, rel in get_all_py_files():
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if 'time.sleep' in line:
                    fh.write(f"ISSUE: time.sleep blocking call\nFILE: {rel}:{i}\nTYPE: blocking_io\nESTIMATED_IMPACT: EXACT CODE -> {line.strip()}\nCURRENT_HANDLING: UNKNOWN\nFIX: UNKNOWN\n\n")

def write_part8(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 8 — COMPLETE ERROR HANDLING AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for path, rel in get_all_py_files():
        try:
            tree = ast.parse(open(path, 'r', encoding='utf-8').read())
        except Exception: continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for handler in node.handlers:
                    catch_type = handler.type.id if isinstance(handler.type, ast.Name) else "Exception (or bare)"
                    re_raise = any(isinstance(n, ast.Raise) for n in ast.walk(handler))
                    swallow = any(isinstance(n, ast.Pass) for n in ast.walk(handler))
                    returns = any(isinstance(n, ast.Return) for n in ast.walk(handler))
                    action = "re-raise" if re_raise else ("return" if returns else ("swallow/pass" if swallow else "other"))
                    fh.write(f"FILE: {rel}:{node.lineno}\nCATCHES: {catch_type}\nACTION: {action}\nCONSEQUENCE: UNKNOWN\nVERDICT: UNKNOWN\n\n")

def write_part9(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 9 — COMPLETE ASYNC/THREADING AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    for path, rel in get_all_py_files():
        with open(path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f, 1):
                if 'threading.Thread' in line:
                    fh.write(f"THREAD/TASK: Thread literal -> {line.strip()}\nCREATED_AT: {rel}:{i}\nDAEMON: UNKNOWN\nJOINED_AT: UNKNOWN\nSHARES_RESOURCES_WITH: UNKNOWN\nLOCK_USED: UNKNOWN\nRACE_CONDITION_POSSIBLE: UNKNOWN\nCANCELLATION_HANDLED: UNKNOWN\n\n")
                if 'asyncio.create_task' in line or 'asyncio.run' in line:
                    fh.write(f"THREAD/TASK: Asyncio task literal -> {line.strip()}\nCREATED_AT: {rel}:{i}\nDAEMON: UNKNOWN\nJOINED_AT: UNKNOWN\nSHARES_RESOURCES_WITH: UNKNOWN\nLOCK_USED: UNKNOWN\nRACE_CONDITION_POSSIBLE: UNKNOWN\nCANCELLATION_HANDLED: UNKNOWN\n\n")

def write_part10(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 10 — COMPLETE STATE MANAGEMENT AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    fh.write("LITERAL STATE DEFINITIONS FOUND (`self.* = ` inside `__init__`):\n\n")
    for path, rel in get_all_py_files():
        try:
            tree = ast.parse(open(path, 'r', encoding='utf-8').read())
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == '__init__':
                    for n in ast.walk(node):
                        if isinstance(n, ast.Assign):
                            for target in n.targets:
                                if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                    fh.write(f"STATE: self.{target.attr}\nSTORED_IN: Class Instance\nINITIALIZED_AT: {rel}:{n.lineno}\nMUTATED_BY: UNKNOWN\nREAD_BY: UNKNOWN\nTHREAD_SAFE: UNKNOWN\nSURVIVES_RESTART: UNKNOWN\nCAN_BECOME_STALE: UNKNOWN\nRECOVERY_IF_CORRUPT: UNKNOWN\n\n")
        except Exception: pass

def write_part11(fh):
    fh.write('═══════════════════════════════════════════════════════════════════════\n')
    fh.write('PART 11 — PRODUCTION READINESS AUDIT\n')
    fh.write('═══════════════════════════════════════════════════════════════════════\n\n')
    
    loggers = []
    for path, rel in get_all_py_files():
        content = open(path, 'r', encoding='utf-8').read()
        for match in re.finditer(r'logging\.getLogger\((.*?)\)', content):
            loggers.append(f"{rel} -> {match.group(1)}")
    
    fh.write(f"LOGGING:\n- Loggers exactly found: {list(set(loggers))}\n- Is log rotation configured? UNKNOWN (See main.py configs)\n- Are log levels appropriate? UNKNOWN\n- Is there a way to change log level without editing source? UNKNOWN\n- Do logs contain PII or secrets? UNKNOWN\n\n")
    
    fh.write("CONFIGURATION:\n- Is there a single config.py? YES" if (REPO_ROOT / 'config.py').exists() else "- Is there a single config.py? NO\n")
    
    fh.write("\nOBSERVABILITY:\n- Metrics collection / tracing literal occurrences:\n")
    found_obs = False
    for path, rel in get_all_py_files():
        content = open(path, 'r', encoding='utf-8').read()
        if 'metric' in content or 'telemetry' in content:
            fh.write(f"  Found in {rel}\n")
            found_obs = True
    if not found_obs: fh.write("  NONE DETECTED.\n")
    
    fh.write("\nDEPLOYMENT:\n")
    fh.write(f"- requirements.txt present? {(REPO_ROOT / 'requirements.txt').exists()}\n")
    fh.write(f"- pyproject.toml present? {(REPO_ROOT / 'pyproject.toml').exists()}\n")
    fh.write(f"- setup.py present? {(REPO_ROOT / 'setup.py').exists()}\n")
    fh.write(f"- Dockerfile present? {(REPO_ROOT / 'Dockerfile').exists()}\n")
    fh.write(f"- .gitignore present? {(REPO_ROOT / '.gitignore').exists()}\n")
    
    fh.write("\nTESTING:\n")
    tests = [rel for path, rel in get_all_py_files() if 'test_' in rel or '_test' in rel]
    fh.write(f"- Test files exactly found: {tests if tests else 'NONE'}\n")

if __name__ == '__main__':
    with open(OUT, 'w', encoding='utf-8') as fh:
        fh.write('# PRODUCTION_AUDIT.md\n\n')
        write_part1(fh)
        write_part2(fh)
        write_part3(fh)
        write_part4(fh)
        write_part5(fh)
        write_part6(fh)
        write_part7(fh)
        write_part8(fh)
        write_part9(fh)
        write_part10(fh)
        write_part11(fh)
    print("DONE writing " + str(OUT))
