#!/usr/bin/env python3
import os
import ast
import json
from pathlib import Path

REPO_ROOT = Path.cwd()
LOCAL_MODULES = {p.name for p in REPO_ROOT.iterdir() if p.is_dir()}
# include top-level py files as local module names (without .py)
for p in REPO_ROOT.iterdir():
    if p.is_file() and p.suffix == '.py':
        LOCAL_MODULES.add(p.stem)


def get_call_name(node):
    # node is ast.Call
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = []
        cur = func
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        parts.reverse()
        return '.'.join(parts)
    try:
        return ast.unparse(func)
    except Exception:
        return '<unknown>'


def root_name_of_call(call_name):
    if '.' in call_name:
        return call_name.split('.')[0]
    return call_name


def analyze_method(func_node):
    info = {}
    info['line'] = func_node.lineno
    # signature
    try:
        sig = ast.unparse(func_node.args)
    except Exception:
        sig = 'complex'
    info['signature'] = f"def {func_node.name}({sig})"
    # async
    info['async'] = isinstance(func_node, ast.AsyncFunctionDef)
    # find calls, returns, try/except, constants
    calls = []
    returns = []
    try_except = []
    constants = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            cn = get_call_name(node)
            calls.append({'call': cn, 'lineno': getattr(node, 'lineno', None)})
        if isinstance(node, ast.Return):
            if node.value is None:
                returns.append({'type': 'None', 'lineno': node.lineno})
            else:
                try:
                    returns.append({'type': ast.unparse(node.value), 'lineno': node.lineno})
                except Exception:
                    returns.append({'type': 'complex', 'lineno': node.lineno})
        if isinstance(node, ast.Try):
            # capture whether handlers re-raise or swallow
            for h in node.handlers:
                handler_actions = [type(n).__name__ for n in ast.walk(h)]
                re_raise = any(isinstance(n, ast.Raise) for n in ast.walk(h))
                swallow = any(isinstance(n, (ast.Pass, ast.Return)) for n in ast.walk(h))
                try_except.append({'handler_line': h.lineno, 're_raise': re_raise, 'swallow': swallow})
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (str, int, float)):
                constants.append({'value': node.value, 'lineno': node.lineno})
    info['calls'] = calls
    info['returns'] = returns
    info['try_except'] = try_except
    info['hardcoded_values'] = constants
    return info


def analyze_file(path):
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        src = fh.read()
    tree = ast.parse(src)
    classes = []
    functions = []
    def _handle_class(n):
        cls = {'name': n.name, 'line': n.lineno, 'inherits': [ast.unparse(b) if not isinstance(b, ast.Name) else b.id for b in n.bases], 'methods': []}
        for item in n.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                m = analyze_method(item)
                m['name'] = item.name; cls['methods'].append(m)
        classes.append(cls)

    def _handle_func(n):
        f = analyze_method(n)
        f['name'] = n.name; functions.append(f)

    _NODE_HANDLERS = {ast.ClassDef: _handle_class, ast.FunctionDef: _handle_func, ast.AsyncFunctionDef: _handle_func}
    for node in tree.body:
        h = _NODE_HANDLERS.get(type(node))
        h(node) if h else None
    return {'path': str(path.relative_to(REPO_ROOT)).replace('\\','/'), 'classes': classes, 'functions': functions}


def collect_all_files():
    py_files = [p for p in REPO_ROOT.rglob('*.py') if 'tools/' not in str(p).replace('\\','/')]
    return sorted(py_files)


def main():
    files = collect_all_files()
    results = []
    all_calls = set()
    defs = []
    for f in files:
        try:
            res = analyze_file(f)
            results.append(res)
            # collect defined methods/functions
            for cls in res['classes']:
                for m in cls['methods']:
                    defs.append({'module': res['path'], 'class': cls['name'], 'method': m['name'], 'line': m['line']})
            for fn in res['functions']:
                defs.append({'module': res['path'], 'class': None, 'method': fn['name'], 'line': fn['line']})
            # collect all called names
            for cls in res['classes']:
                for m in cls['methods']:
                    for c in m['calls']:
                        all_calls.add(c['call'])
            for fn in res['functions']:
                for c in fn['calls']:
                    all_calls.add(c['call'])
        except Exception as e:
            results.append({'path': str(f), 'error': str(e)})
    # mark NEVER_CALLED heuristically
    called_simple = {c.split('.')[-1] for c in all_calls}
    # annotate defs
    for d in defs:
        d['never_called'] = (d['method'] not in called_simple)
    out = {'definitions': defs, 'files': results}
    with open('inventory.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)
    print('Wrote inventory.json with entries for', len(results), 'files and', len(defs), 'definitions')

if __name__ == '__main__':
    main()
