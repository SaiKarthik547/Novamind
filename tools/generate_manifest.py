#!/usr/bin/env python3
import os
import sys
import json
import ast
from datetime import datetime, timezone

REPO_ROOT = os.getcwd()
EXCLUDE_DIRS = {'.git', '__pycache__', '.venv'}
EXT_MAP = {
    '.py':'python', '.json':'json', '.yaml':'yaml', '.yml':'yaml', '.toml':'toml',
    '.md':'md', '.txt':'txt', '.env':'env', '.ini':'other', '.cfg':'other', '.csv':'other'
}


def is_binary_string(bytes_data):
    if b'\x00' in bytes_data:
        return True
    # Heuristic: if many non-text characters
    textchars = bytearray({7,8,9,10,12,13,27} | set(range(0x20,0x100)))
    return bool(bytes_data.translate(None, textchars))


def first_sentence(text):
    if not text:
        return None
    # collapse whitespace
    s = ' '.join(text.strip().split())
    # split on sentence end
    for sep in ('.', '\n'):
        if sep in s:
            parts = s.split(sep)
            if parts and parts[0].strip():
                return parts[0].strip() + ('.' if sep == '.' else '')
    return s if len(s) < 200 else s[:200] + '...'


def python_purpose(path, content):
    try:
        tree = ast.parse(content)
        doc = ast.get_docstring(tree)
        if doc:
            return first_sentence(doc)
        # try top-level class or function docstring
        for node in tree.body:
            if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
                doc = ast.get_docstring(node)
                if doc:
                    header = node.name
                    return f"Contains `{header}`: {first_sentence(doc)}"
    except Exception:
        pass
    # fallback to top comments
    for line in content.splitlines()[:20]:
        line = line.strip()
        if line.startswith('#'):
            return line.lstrip('# ').strip()
    return 'UNKNOWN: no module docstring or top-level comment'


def file_purpose(path, ext, content_bytes):
    if ext == '.py':
        try:
            text = content_bytes.decode('utf-8')
        except Exception:
            try:
                text = content_bytes.decode('latin-1')
            except Exception:
                return 'UNKNOWN: cannot decode python file'
        return python_purpose(path, text)
    if ext in ('.md', '.txt'):
        try:
            text = content_bytes.decode('utf-8')
        except Exception:
            text = content_bytes.decode('latin-1', errors='replace')
        for line in text.splitlines():
            if line.strip():
                return first_sentence(line)
        return 'UNKNOWN: empty text file'
    if ext == '.json':
        try:
            obj = json.loads(content_bytes.decode('utf-8'))
            if isinstance(obj, dict):
                keys = list(obj.keys())[:5]
                return 'JSON file with top-level keys: ' + ', '.join(map(str, keys))
            return 'JSON file' 
        except Exception:
            return 'UNKNOWN: invalid JSON'
    if ext in ('.yaml', '.yml', '.toml'):
        try:
            # try decode first lines
            text = content_bytes.decode('utf-8')
            for line in text.splitlines():
                if line.strip():
                    return first_sentence(line)
        except Exception:
            pass
        return 'UNKNOWN: structured config file'
    return 'BINARY' if is_binary_string(content_bytes[:1024]) else 'UNKNOWN: no purpose extracted'


def process_file(root, file):
    abspath = os.path.join(root, file)
    rel = os.path.relpath(abspath, REPO_ROOT).replace('\\', '/')
    stat = os.stat(abspath)
    size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    ext = os.path.splitext(file)[1].lower()
    ftype = EXT_MAP.get(ext, 'other')
    try:
        with open(abspath, 'rb') as fh:
            data = fh.read()
    except Exception as e:
        return {
            'PATH': rel,
            'TYPE': ftype,
            'SIZE_LINES': 0,
            'SIZE_BYTES': size,
            'EMPTY': 'UNKNOWN',
            'LAST_MODIFIED': mtime,
            'PURPOSE': f'UNKNOWN: cannot read file ({e})'
        }
    binary = is_binary_string(data[:1024])
    if binary:
        size_lines = 0
        empty = 'YES' if size == 0 else 'NO'
        purpose = 'BINARY'
    else:
        try:
            text = data.decode('utf-8')
        except Exception:
            text = data.decode('latin-1', errors='replace')
        size_lines = len(text.splitlines())
        # empty defined as 0 bytes or only whitespace/comments for text
        stripped = '\n'.join([ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith('#')])
        empty = 'YES' if size == 0 or stripped.strip() == '' else 'NO'
        purpose = file_purpose(rel, ext, data)
    return {
        'PATH': rel,
        'TYPE': ftype,
        'SIZE_LINES': size_lines,
        'SIZE_BYTES': size,
        'EMPTY': empty,
        'LAST_MODIFIED': mtime,
        'PURPOSE': purpose
    }


def main():
    all_files = []
    for root, dirs, files in os.walk(REPO_ROOT):
        # prune
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
        for f in files:
            all_files.append(process_file(root, f))
    out = {'files': all_files}
    with open('manifest.json', 'w', encoding='utf-8') as fh:
        json.dump(out, fh, indent=2)
    print('Wrote manifest.json with', len(all_files), 'entries')

if __name__ == '__main__':
    main()
