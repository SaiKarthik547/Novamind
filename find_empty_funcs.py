import ast
import os
from pathlib import Path

def analyze_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        tree = ast.parse(code)
    except Exception:
        return []
    
    empty_funcs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            body = node.body
            real_stmts = []
            for stmt in body:
                if isinstance(stmt, ast.Expr):
                    if isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                        continue # docstring
                    if isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis:
                        real_stmts.append('...')
                        continue
                if isinstance(stmt, ast.Pass):
                    real_stmts.append('pass')
                    continue
                if isinstance(stmt, ast.Raise):
                    if isinstance(stmt.exc, ast.Call) and getattr(stmt.exc.func, 'id', '') == 'NotImplementedError':
                        real_stmts.append('NotImplementedError')
                        continue
                real_stmts.append('REAL_CODE')
            
            if len(real_stmts) > 0 and all(s in ('pass', '...', 'NotImplementedError') for s in real_stmts):
                empty_funcs.append((node.name, real_stmts[0]))
    return empty_funcs

root = Path('.')
results = {}
for py_file in root.rglob('*.py'):
    if 'site-packages' in py_file.parts or 'test_env' in py_file.parts or '.venv' in py_file.parts: continue
    funcs = analyze_file(py_file)
    if funcs:
        results[str(py_file)] = funcs

import json
print(json.dumps(results, indent=2))
