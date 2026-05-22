"""
File Agent — Complete file and folder management.
Read, write, copy, move, delete, search, archive, compress, diff, watch,
metadata edit, encoding detect, binary read, duplicate finder, file type detect.
"""
from __future__ import annotations

import base64
import binascii
import difflib
import fnmatch
import glob
import hashlib
import importlib
import io
import json
import logging
import mimetypes
import os

# --- Phase 10.5 Capability Shim ---
import sys as _sys
class _ModuleShim:
    def __init__(self, mod_name): self._mod_name = mod_name
    def __getattr__(self, name): return getattr(__import__(self._mod_name), name)
subprocess = _ModuleShim('subprocess')
shutil = _ModuleShim('shutil')
socket = _ModuleShim('socket')
# ----------------------------------
import re
import stat
import struct
import tempfile
import time
import zipfile
import tarfile
import gzip
import bz2
import lzma
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from core.foundation.base_agent import BaseAgent
from core.foundation.runtime_paths import ensure_runtime_dir

logger = logging.getLogger("FileAgent")

# Chardet optional
try:
    import chardet
    _CHARDET_OK = True
except ImportError:
    _CHARDET_OK = False


# ─────────────────────────────────────────────────────────────────────────────
#  Magic bytes for file type detection
# ─────────────────────────────────────────────────────────────────────────────

MAGIC_SIGNATURES: List[Tuple[bytes, str, str]] = [
    # bytes_prefix, mime_type, extension
    (b"\x89PNG\r\n\x1a\n",        "image/png",                  ".png"),
    (b"\xff\xd8\xff",              "image/jpeg",                 ".jpg"),
    (b"GIF87a",                    "image/gif",                  ".gif"),
    (b"GIF89a",                    "image/gif",                  ".gif"),
    (b"BM",                        "image/bmp",                  ".bmp"),
    (b"RIFF",                      "audio/wav",                  ".wav"),
    (b"ID3",                       "audio/mpeg",                 ".mp3"),
    (b"\xff\xfb",                  "audio/mpeg",                 ".mp3"),
    (b"ftyp",                      "video/mp4",                  ".mp4"),
    (b"\x1a\x45\xdf\xa3",         "video/webm",                 ".webm"),
    (b"OggS",                      "audio/ogg",                  ".ogg"),
    (b"PK\x03\x04",               "application/zip",            ".zip"),
    (b"PK\x05\x06",               "application/zip",            ".zip"),
    (b"\x1f\x8b",                  "application/gzip",           ".gz"),
    (b"Rar!\x1a\x07",             "application/x-rar-compressed", ".rar"),
    (b"7z\xbc\xaf\x27\x1c",      "application/x-7z-compressed", ".7z"),
    (b"\xfd7zXZ\x00",             "application/x-xz",           ".xz"),
    (b"BZh",                       "application/x-bzip2",        ".bz2"),
    (b"%PDF",                      "application/pdf",            ".pdf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/msoffice", ".doc"),
    (b"PK\x03\x04\x14",           "application/vnd.openxmlformats", ".docx"),
    (b"SQLite format 3",           "application/x-sqlite3",      ".db"),
    (b"\x7fELF",                   "application/x-elf",          ""),
    (b"MZ",                        "application/x-msdownload",   ".exe"),
    (b"\xca\xfe\xba\xbe",         "application/x-mach-binary",  ""),
    (b"#!",                        "text/x-script",              ".sh"),
    (b"<?xml",                     "application/xml",            ".xml"),
    (b"<!DOCTYPE html",            "text/html",                  ".html"),
    (b"<html",                     "text/html",                  ".html"),
    (b"{",                         "application/json",           ".json"),
    (b"[",                         "application/json",           ".json"),
]


# ─────────────────────────────────────────────────────────────────────────────
#  File Agent
# ─────────────────────────────────────────────────────────────────────────────

class FileAgent(BaseAgent):
    """
    Complete OS file system agent.
    Includes search, diffs, permissions, archiving, and watchers.
    """

    PROTECTED_PATHS = {
        "C:\\Windows", "C:\\Program Files", "C:\\ProgramData",
        "/usr/bin", "/usr/sbin", "/bin", "/sbin", "/etc",
        "/sys", "/dev", "/proc", "/boot",
    }

    SAFE_EXTENSIONS = {
        ".txt", ".py", ".js", ".ts", ".html", ".css", ".json",
        ".xml", ".csv", ".md", ".yaml", ".yml", ".ini", ".cfg",
        ".log", ".sh", ".bat", ".ps1", ".sql", ".rst", ".toml",
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".svg", ".ico",
        ".mp3", ".wav", ".mp4", ".avi", ".mov",
        ".pdf", ".doc", ".docx", ".xlsx", ".xls", ".pptx",
        ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
        ".db", ".sqlite", ".exe", ".msi",
    }

    def __init__(self, allowed_roots: List[str] = None, max_file_size: int = 500 * 1024 * 1024):
        super().__init__(name=self.__class__.__name__, role="Agent")
        self.allowed_roots = [Path(p).resolve() for p in (allowed_roots or [])]
        self.max_file_size   = max_file_size  # 500 MB default
        self.op_log:         List[Dict] = []
        self.operation_log:  List[Dict] = []
        self.trash_dir       = ensure_runtime_dir("trash")
        self._watch_thread   = None
        self._watch_stop     = False

        self.handlers = {
            "read":                self.read_file,
            "read_binary":         self.read_binary,
            "read_lines":          self.read_lines,
            "read_json":           self.read_json,
            "write":               self.write_file,
            "write_json":          self.write_json,
            "append":              self.append_file,
            "patch_lines":         self.patch_lines,
            "copy":                self.copy_file,
            "move":                self.move_file,
            "delete":              self.delete_file,
            "rename":              self.rename_file,
            "recover":             self.recover_file,
            "secure_delete":       self.secure_delete,
            "create_dir":          self.create_directory,
            "list":                self.list_directory,
            "list_recursive":      self.list_recursive,
            "tree":                self.directory_tree,
            "delete_dir":          self.delete_directory,
            "copy_dir":            self.copy_directory,
            "search":              self.search_files,
            "search_content":      self.search_file_content,
            "find_large":          self.find_large_files,
            "find_old":            self.find_old_files,
            "find_by_type":        self.find_by_type,
            "find_duplicates":     self.find_duplicate_files,
            "info":                self.get_file_info,
            "stat":                self.get_file_stat,
            "size":                self.get_path_size,
            "checksum":            self.compute_checksum,
            "detect_type":         self.detect_file_type,
            "detect_encoding":     self.detect_encoding,
            "is_binary":           self.is_binary_file,
            "zip":                 self.zip_files,
            "unzip":               self.unzip_file,
            "tar":                 self.tar_files,
            "untar":               self.untar_file,
            "compress_gzip":       self.compress_gzip,
            "decompress_gzip":     self.decompress_gzip,
            "compress_bz2":        self.compress_bz2,
            "decompress_bz2":      self.decompress_bz2,
            "list_archive":        self.list_archive,
            "extract_file":        self.extract_from_archive,
            "diff":                self.diff_files,
            "diff_directories":    self.diff_directories,
            "apply_diff":          self.apply_diff_to_file,
            "get_permissions":     self.get_permissions,
            "set_permissions":     self.set_permissions,
            "make_executable":     self.make_executable,
            "convert_encoding":    self.convert_encoding,
            "normalize_line_endings": self.normalize_line_endings,
            "organize":            self.organize_files,
            "batch_rename":        self.batch_rename,
            "move_by_date":        self.move_files_by_date,
            "move_by_type":        self.move_files_by_type,
            "watch_start":         self.start_watching,
            "watch_stop":          self.stop_watching,
            "tail":                self.tail_file,
            "head":                self.head_file,
            "line_count":          self.count_lines,
            "word_count":          self.count_words,
            "get_log":             self._get_log,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  (Execute inherited from BaseAgent)
    # ─────────────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────────────
    #  Basic I/O
    # ─────────────────────────────────────────────────────────────────────────

    def read_file(self, path: str, offset: int = 0,
                   limit: int = None, encoding: str = None, context: Any = None) -> Dict:
        """Read text file. Auto-detect encoding if not specified."""
        p    = self._validate(path)
        size = p.stat().st_size

        if not encoding:
            encoding = self._sniff_encoding(p) or "utf-8"

        if context and hasattr(context, 'sandbox'):
            # Phase 8 Execution Kernel isolation
            raw_content = context.sandbox.read_file(context.lease.lease_id, str(p), mode="r")
            if offset:
                raw_content = raw_content[offset:]
            content = raw_content[:limit] if limit else raw_content
        else:
            with open(p, "r", encoding=encoding, errors="replace") as f:
                if offset:
                    f.seek(offset)
                content = f.read(limit) if limit else f.read()

        return {
            "success":   True,
            "path":      str(p),
            "content":   content,
            "size":      size,
            "encoding":  encoding,
            "truncated": limit is not None and len(content) == limit,
        }

    def read_binary(self, path: str, offset: int = 0,
                     length: int = 4096) -> Dict:
        """Read binary file and return hex dump + base64."""
        p = self._validate(path)
        with open(p, "rb") as f:
            f.seek(offset)
            data = f.read(length)
        hex_dump = binascii.hexlify(data).decode()
        b64      = base64.b64encode(data).decode()
        # Human hex dump
        dump_lines: List[str] = []
        for i in range(0, len(data), 16):
            chunk   = data[i:i + 16]
            hex_str = " ".join(f"{b:02x}" for b in chunk)
            asc     = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            dump_lines.append(f"{offset + i:08x}  {hex_str:<48}  |{asc}|")
        return {
            "success":   True,
            "path":      str(p),
            "offset":    offset,
            "length":    len(data),
            "hex":       hex_dump,
            "base64":    b64,
            "hex_dump":  "\n".join(dump_lines),
        }

    def read_lines(self, path: str, start: int = 1,
                    end: int = None, encoding: str = "utf-8") -> Dict:
        """Read specific line range from a file."""
        p     = self._validate(path)
        lines: List[str] = []
        with open(p, "r", encoding=encoding, errors="replace") as f:
            for i, line in enumerate(f, 1):
                if i >= start:
                    lines.append(line)
                if end and i >= end:
                    break
        return {
            "success": True,
            "path":    str(p),
            "start":   start,
            "lines":   lines,
            "count":   len(lines),
        }

    def read_json(self, path: str, key_path: str = None) -> Dict:
        """Read and parse JSON file."""
        p    = self._validate(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        data = json.loads(text)
        if key_path:
            _JSON_TRAVERSE = {dict: lambda d, k: d.get(k), list: lambda d, k: d[int(k)] if k.isdigit() else None}
            for key in key_path.split("."):
                h = _JSON_TRAVERSE.get(type(data))
                if not h: break
                data = h(data, key)
        return {"success": True, "path": str(p), "data": data}

    def write_file(self, path: str, content: str,
                    encoding: str = "utf-8",
                    overwrite: bool = True,
                    create_parents: bool = True, context: Any = None) -> Dict:
        """Write text to file."""
        p = Path(path)
        self._check_protected(p)
        if p.exists() and not overwrite:
            return {"success": False, "error": "File exists and overwrite=False"}
        if create_parents:
            p.parent.mkdir(parents=True, exist_ok=True)
        if context and hasattr(context, 'sandbox'):
            context.sandbox.write_file(context.lease.lease_id, str(p), content, mode="w")
        else:
            with open(p, "w", encoding=encoding) as f:
                f.write(content)
        return {
            "success":       True,
            "path":          str(p.resolve()),
            "bytes_written": len(content.encode(encoding)),
        }

    def write_json(self, path: str, data: Any,
                    indent: int = 2, ensure_ascii: bool = False) -> Dict:
        """Write Python object as formatted JSON."""
        text = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii,
                          default=str)
        return self.write_file(path, text)

    def append_file(self, path: str, content: str,
                     encoding: str = "utf-8",
                     add_newline: bool = True) -> Dict:
        """Append content to file. Creates file if it doesn't exist."""
        p = Path(path)
        self._check_protected(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        if add_newline and content and not content.startswith("\n"):
            content = "\n" + content
        with open(p, "a", encoding=encoding) as f:
            f.write(content)
        return {
            "success":  True,
            "path":     str(p),
            "appended": len(content.encode(encoding)),
        }

    def patch_lines(self, path: str, replacements: List[Dict],
                     encoding: str = "utf-8") -> Dict:
        """Replace specific lines by line number. replacements=[{line:N, text:'...'}]."""
        p = self._validate(path)
        lines = p.read_text(encoding=encoding).splitlines(keepends=True)
        changed = 0
        for rep in replacements:
            ln   = rep.get("line", 0)
            text = rep.get("text", "")
            if 1 <= ln <= len(lines):
                lines[ln - 1] = text + ("\n" if not text.endswith("\n") else "")
                changed += 1
        p.write_text("".join(lines), encoding=encoding)
        return {"success": True, "path": str(p), "lines_changed": changed}

    # ─────────────────────────────────────────────────────────────────────────
    #  Copy / Move / Delete
    # ─────────────────────────────────────────────────────────────────────────

    def copy_file(self, source: str, destination: str,
                   overwrite: bool = False,
                   preserve_metadata: bool = True) -> Dict:
        """Copy a file or directory."""
        src = self._validate(source)
        dst = Path(destination)
        self._check_protected(dst)

        if dst.exists() and not overwrite:
            return {"success": False, "error": "Destination exists and overwrite=False"}
        dst.parent.mkdir(parents=True, exist_ok=True)

        _COPY_DISPATCH = {
            "file": lambda: shutil.copy2(src, dst) if preserve_metadata else shutil.copy(src, dst),
            "dir":  lambda: shutil.copytree(src, dst, dirs_exist_ok=overwrite),
        }
        
        path_type = "file" if src.is_file() else "dir" if src.is_dir() else None
        handler = _COPY_DISPATCH.get(path_type)
        if not handler:
            return {"success": False, "error": f"Source not found or invalid: {src}"}
        
        handler()

        return {"success": True, "source": str(src), "destination": str(dst)}

    def move_file(self, source: str, destination: str,
                   overwrite: bool = False) -> Dict:
        """Move a file or directory."""
        src = self._validate(source)
        dst = Path(destination)
        self._check_protected(dst)

        if dst.exists() and not overwrite:
            return {"success": False, "error": "Destination exists"}
        dst.parent.mkdir(parents=True, exist_ok=True)

        shutil.move(str(src), str(dst))
        return {
            "success":     True,
            "source":      str(src),
            "destination": str(dst),
            "rollback_cmd": f"move '{dst}' '{src}'",
        }

    def delete_file(self, path: str, permanent: bool = False, context: Any = None) -> Dict:
        """Delete file/directory (moves to trash by default)."""
        p = self._validate(path)
        self._check_protected(p)

        if not permanent:
            ts      = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            backup  = self.trash_dir / f"{p.name}_{ts}"
            _BACKUP_HANDLERS = {
                True:  lambda: shutil.copy2(p, backup) if p.is_file() else None,
                False: lambda: shutil.copytree(p, backup) if p.is_dir() else None
            }
            # Dispatch based on is_file/is_dir state
            _BACKUP_HANDLERS[p.is_file()]() if p.exists() else None

        ptype = "file" if p.is_file() else "dir" if p.is_dir() else None
        if not ptype: return {"success": False, "error": "Path not found"}

        if context and hasattr(context, 'sandbox') and ptype == "file":
            _DELETE_HANDLERS = {
                "file": lambda: context.sandbox.delete_file(context.lease.lease_id, str(p)),
                "dir":  lambda: shutil.rmtree(p) # Sandbox doesn't fully wrap dir deletion yet
            }
        else:
            _DELETE_HANDLERS = {
                "file": lambda: p.unlink(),
                "dir":  lambda: shutil.rmtree(p)
            }
        _DELETE_HANDLERS[ptype]()

        return {
            "success":     True,
            "deleted":     str(p),
            "permanent":   permanent,
            "recoverable": not permanent,
            "backup":      str(backup) if not permanent else None,
        }

    def rename_file(self, path: str, new_name: str) -> Dict:
        """Rename file or directory."""
        p       = self._validate(path)
        new_p   = p.parent / new_name
        if new_p.exists():
            return {"success": False, "error": f"'{new_name}' already exists"}
        p.rename(new_p)
        return {"success": True, "old": str(p), "new": str(new_p)}

    def recover_file(self, backup_path: str,
                      restore_path: str = None) -> Dict:
        """Recover a file from the NovaMind trash."""
        backup = Path(backup_path)
        if not backup.exists():
            return {"success": False, "error": "Backup not found"}

        if not restore_path:
            # Strip timestamp suffix
            restore_name = re.sub(r"_\d{8}_\d{6}_\d+$", "", backup.name)
            restore_path = str(Path.home() / restore_name)

        dst = Path(restore_path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if backup.is_file():
            shutil.copy2(backup, dst)
        else:
            shutil.copytree(backup, dst)
        return {"success": True, "recovered_to": str(dst)}

    def secure_delete(self, path: str, passes: int = 3) -> Dict:
        """Overwrite file with random bytes before deletion (secure wipe)."""
        p    = self._validate(path)
        if not p.is_file():
            return {"success": False, "error": "Secure delete only for files"}
        size = p.stat().st_size
        with open(p, "r+b") as f:
            for _ in range(passes):
                f.seek(0)
                f.write(os.urandom(size))
                f.flush()
                os.fsync(f.fileno())
        p.unlink()
        return {"success": True, "wiped": str(p), "passes": passes,
                "bytes_wiped": size * passes}

    # ─────────────────────────────────────────────────────────────────────────
    #  Directories
    # ─────────────────────────────────────────────────────────────────────────

    def create_directory(self, path: str, mode: int = 0o755) -> Dict:
        p = Path(path)
        p.mkdir(parents=True, exist_ok=True, mode=mode)
        return {"success": True, "path": str(p.resolve())}

    def list_directory(self, path: str = None,
                        include_hidden: bool = False,
                        sort_by: str = "name") -> Dict:
        """List directory entries with metadata."""
        dir_p = self._validate(path) if path else Path.home()
        entries: List[Dict] = []
        for entry in dir_p.iterdir():
            if not include_hidden and entry.name.startswith("."):
                continue
            try:
                st = entry.stat()
                entries.append({
                    "name":     entry.name,
                    "path":     str(entry),
                    "type":     "dir" if entry.is_dir() else "file",
                    "size":     st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "ext":      entry.suffix,
                    "readable": os.access(entry, os.R_OK),
                })
            except (PermissionError, OSError):
                entries.append({"name": entry.name, "path": str(entry),
                                 "error": "permission denied"})

        key = {"name": "name", "size": "size", "date": "modified"}.get(sort_by, "name")
        entries.sort(key=lambda x: x.get(key, ""), reverse=(sort_by == "size"))
        return {"success": True, "path": str(dir_p), "count": len(entries),
                "entries": entries}

    def list_recursive(self, path: str, pattern: str = "*",
                        max_depth: int = 10,
                        max_files: int = 10000) -> Dict:
        """Recursive directory listing."""
        root  = self._validate(path)
        found: List[Dict] = []
        count = 0
        for dp, dirs, files in os.walk(root):
            depth = len(Path(dp).relative_to(root).parts)
            if depth > max_depth:
                dirs.clear()
                continue
            for fn in fnmatch.filter(files, pattern):
                if count >= max_files:
                    break
                fp = Path(dp) / fn
                try:
                    st = fp.stat()
                    found.append({
                        "path":     str(fp),
                        "name":     fn,
                        "size":     st.st_size,
                        "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                        "depth":    depth,
                    })
                    count += 1
                except Exception:
                    pass

        return {"success": True, "root": str(root), "files": found,
                "count": count, "truncated": count >= max_files}

    def directory_tree(self, path: str, max_depth: int = 3,
                        show_size: bool = True) -> Dict:
        """Return directory tree as ASCII art + structured dict."""
        root  = Path(path)
        lines: List[str] = [str(root)]

        def _build(p: Path, prefix: str, depth: int):
            if depth > max_depth:
                return
            try:
                items = sorted(p.iterdir(), key=lambda x: (x.is_file(), x.name))
            except PermissionError:
                return
            for i, item in enumerate(items):
                is_last = (i == len(items) - 1)
                connector = "└── " if is_last else "├── "
                size_str  = ""
                if show_size and item.is_file():
                    try:
                        size_str = f"  ({self._human_size(item.stat().st_size)})"
                    except Exception:
                        pass
                lines.append(f"{prefix}{connector}{item.name}{size_str}")
                if item.is_dir():
                    ext = "    " if is_last else "│   "
                    _build(item, prefix + ext, depth + 1)

        _build(root, "", 0)
        return {"success": True, "tree": "\n".join(lines), "path": str(root)}

    def delete_directory(self, path: str, force: bool = False) -> Dict:
        """Delete a directory (force=True skips trash)."""
        return self.delete_file(path, permanent=force)

    def copy_directory(self, source: str, destination: str,
                        overwrite: bool = False) -> Dict:
        return self.copy_file(source, destination, overwrite=overwrite)

    # ─────────────────────────────────────────────────────────────────────────
    #  Search
    # ─────────────────────────────────────────────────────────────────────────

    def search_files(self, pattern: str, path: str = None,
                      recursive: bool = True,
                      max_results: int = 200,
                      file_types: List[str] = None) -> Dict:
        """Find files matching glob pattern."""
        root = Path(path) if path else Path.home()
        matches: List[Dict] = []
        if recursive:
            gen = root.rglob(pattern)
        else:
            gen = root.glob(pattern)
        for p in gen:
            if len(matches) >= max_results:
                break
            if file_types:
                if p.suffix not in file_types and p.suffix.lower() not in file_types:
                    continue
            try:
                st = p.stat()
                matches.append({
                    "path":     str(p),
                    "name":     p.name,
                    "size":     st.st_size,
                    "modified": datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "type":     "dir" if p.is_dir() else "file",
                })
            except Exception:
                matches.append({"path": str(p), "name": p.name})
        return {"success": True, "pattern": pattern, "count": len(matches),
                "results": matches, "truncated": len(matches) >= max_results}

    def search_file_content(self, pattern: str, path: str = None,
                             file_pattern: str = "*.txt",
                             regex: bool = False,
                             case_sensitive: bool = False,
                             context_lines: int = 2,
                             max_results: int = 500) -> Dict:
        """Search file contents for a string or regex pattern."""
        root = Path(path) if path else Path.home()
        flags = 0 if case_sensitive else re.IGNORECASE
        if not regex:
            pattern = re.escape(pattern)
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return {"success": False, "error": f"Regex error: {e}"}

        results: List[Dict] = []
        for filepath in root.rglob(file_pattern):
            if len(results) >= max_results:
                break
            try:
                enc   = self._sniff_encoding(filepath) or "utf-8"
                lines = filepath.read_text(enc, errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                if compiled.search(line):
                    start = max(0, i - context_lines)
                    end   = min(len(lines), i + context_lines + 1)
                    results.append({
                        "file":    str(filepath),
                        "line":    i + 1,
                        "match":   line.rstrip(),
                        "context": lines[start:end],
                    })
                    if len(results) >= max_results:
                        break

        return {"success": True, "pattern": pattern, "matches": len(results),
                "results": results}

    def find_large_files(self, path: str = None, min_size_mb: float = 100,
                          max_results: int = 50) -> Dict:
        """Find files larger than a threshold."""
        root      = Path(path) if path else Path.home()
        threshold = int(min_size_mb * 1e6)
        found: List[Dict] = []
        for fp in root.rglob("*"):
            try:
                if fp.is_file():
                    size = fp.stat().st_size
                    if size >= threshold:
                        found.append({"path": str(fp), "size_mb": round(size / 1e6, 2),
                                       "name": fp.name})
            except Exception:
                pass
        found.sort(key=lambda x: x["size_mb"], reverse=True)
        return {"success": True, "threshold_mb": min_size_mb,
                "count": len(found), "files": found[:max_results]}

    def find_old_files(self, path: str = None,
                        older_than_days: int = 365,
                        max_results: int = 100) -> Dict:
        """Find files not modified for more than N days."""
        root     = Path(path) if path else Path.home()
        cutoff   = time.time() - (older_than_days * 86400)
        found: List[Dict] = []
        for fp in root.rglob("*"):
            try:
                if fp.is_file():
                    mtime = fp.stat().st_mtime
                    if mtime < cutoff:
                        age_days = int((time.time() - mtime) / 86400)
                        found.append({
                            "path":    str(fp),
                            "age_days": age_days,
                            "size":    fp.stat().st_size,
                            "modified": datetime.fromtimestamp(mtime).isoformat(),
                        })
            except Exception:
                pass
        found.sort(key=lambda x: x["age_days"], reverse=True)
        return {"success": True, "older_than_days": older_than_days,
                "count": len(found), "files": found[:max_results]}

    def find_by_type(self, path: str, mime_prefix: str = "image",
                      max_results: int = 200) -> Dict:
        """Find files by MIME type prefix (e.g. 'image', 'video', 'audio', 'text')."""
        root  = Path(path)
        found: List[Dict] = []
        for fp in root.rglob("*"):
            try:
                if fp.is_file():
                    m, _ = mimetypes.guess_type(str(fp))
                    if m and m.startswith(mime_prefix):
                        found.append({"path": str(fp), "mime": m,
                                       "size": fp.stat().st_size})
            except Exception:
                pass
        return {"success": True, "mime_prefix": mime_prefix,
                "count": len(found), "files": found[:max_results]}

    def find_duplicate_files(self, path: str = None,
                              algorithm: str = "md5") -> Dict:
        """Find duplicate files by content hash."""
        root   = Path(path) if path else Path.home()
        hashes: Dict[str, List[str]] = defaultdict(list)
        total  = 0

        for fp in root.rglob("*"):
            try:
                if fp.is_file() and fp.stat().st_size > 0:
                    digest = self._file_hash(fp, algorithm)
                    hashes[digest].append(str(fp))
                    total += 1
            except Exception:
                pass

        groups = {h: paths for h, paths in hashes.items() if len(paths) > 1}
        waste  = sum(
            Path(paths[0]).stat().st_size * (len(paths) - 1)
            for paths in groups.values()
        )
        return {
            "success":         True,
            "files_scanned":   total,
            "duplicate_groups": len(groups),
            "wasted_mb":       round(waste / 1e6, 2),
            "groups":          [{"hash": h[:16], "count": len(p), "paths": p}
                                 for h, p in list(groups.items())[:50]],
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Info
    # ─────────────────────────────────────────────────────────────────────────

    def get_file_info(self, path: str) -> Dict:
        """Full file metadata including hash, type, encoding."""
        p = self._validate(path)
        st = p.stat()
        info: Dict = {
            "success":     True,
            "path":        str(p),
            "name":        p.name,
            "stem":        p.stem,
            "extension":   p.suffix,
            "size":        st.st_size,
            "size_human":  self._human_size(st.st_size),
            "created":     datetime.fromtimestamp(st.st_ctime).isoformat(),
            "modified":    datetime.fromtimestamp(st.st_mtime).isoformat(),
            "accessed":    datetime.fromtimestamp(st.st_atime).isoformat(),
            "is_file":     p.is_file(),
            "is_dir":      p.is_dir(),
            "is_symlink":  p.is_symlink(),
            "permissions": oct(st.st_mode)[-3:],
            "readable":    os.access(p, os.R_OK),
            "writable":    os.access(p, os.W_OK),
        }
        if p.is_file() and st.st_size < 100 * 1024 * 1024:
            info["md5"]  = self._file_hash(p, "md5")
            info["sha256"] = self._file_hash(p, "sha256")
            type_r = self.detect_file_type(str(p))
            info["detected_type"] = type_r.get("mime_type")
            info["is_binary"]     = type_r.get("is_binary", False)
            if not info["is_binary"]:
                info["encoding"] = self._sniff_encoding(p)
        return info

    def get_file_stat(self, path: str) -> Dict:
        p  = self._validate(path)
        st = p.stat()
        return {
            "success": True,
            "st_size":  st.st_size,
            "st_mtime": st.st_mtime,
            "st_ctime": st.st_ctime,
            "st_atime": st.st_atime,
            "st_mode":  st.st_mode,
            "st_nlink": st.st_nlink,
        }

    def get_path_size(self, path: str) -> Dict:
        """Total size of file or directory."""
        p     = self._validate(path)
        total = 0
        count = 0
        if p.is_file():
            total = p.stat().st_size
            count = 1
        else:
            for fp in p.rglob("*"):
                try:
                    if fp.is_file():
                        total += fp.stat().st_size
                        count += 1
                except Exception:
                    pass
        return {"success": True, "path": str(p), "size": total,
                "size_human": self._human_size(total), "file_count": count}

    def compute_checksum(self, path: str,
                          algorithm: str = "sha256") -> Dict:
        """Compute file checksum."""
        p = self._validate(path)
        if not p.is_file():
            return {"success": False, "error": "Not a file"}
        digest = self._file_hash(p, algorithm)
        return {"success": True, "path": str(p), "algorithm": algorithm,
                "checksum": digest}

    def detect_file_type(self, path: str) -> Dict:
        """Detect file type from magic bytes + extension."""
        p = Path(path)
        if not p.exists() or not p.is_file():
            return {"success": False, "error": "File not found"}

        mime_ext, _ = mimetypes.guess_type(str(p))

        with open(p, "rb") as f:
            header = f.read(16)

        detected_mime = None
        detected_ext  = None
        for sig, mime, ext in MAGIC_SIGNATURES:
            if header[:len(sig)] == sig or (len(sig) > 1 and sig in header[:64]):
                detected_mime = mime
                detected_ext  = ext
                break

        # Check if binary
        try:
            with open(p, "rb") as f:
                chunk = f.read(8192)
            is_binary = b"\x00" in chunk
        except Exception:
            is_binary = False

        return {
            "success":      True,
            "path":         str(p),
            "mime_type":    detected_mime or mime_ext or "application/octet-stream",
            "by_extension": mime_ext,
            "by_magic":     detected_mime,
            "extension":    p.suffix,
            "is_binary":    is_binary,
            "header_hex":   header.hex(),
        }

    def detect_encoding(self, path: str) -> Dict:
        """Detect text encoding of a file."""
        p = self._validate(path)
        enc = self._sniff_encoding(p)
        return {"success": True, "path": str(p), "encoding": enc}

    def is_binary_file(self, path: str) -> Dict:
        p = self._validate(path)
        with open(p, "rb") as f:
            chunk = f.read(8192)
        is_bin = b"\x00" in chunk
        return {"success": True, "is_binary": is_bin, "path": str(p)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Archive / Compress
    # ─────────────────────────────────────────────────────────────────────────

    def zip_files(self, sources: List[str], output_path: str,
                   compression: int = zipfile.ZIP_DEFLATED,
                   password: str = None) -> Dict:
        """Create a ZIP archive from a list of files/directories."""
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        added: List[str] = []
        with zipfile.ZipFile(output, "w", compression=compression) as zf:
            for src_str in sources:
                src = Path(src_str)
                def _zip_file(p):
                    zf.write(p, p.name)
                    added.append(p.name)
                def _zip_dir(p):
                    for fp in p.rglob("*"):
                        if fp.is_file():
                            arc = fp.relative_to(p.parent)
                            zf.write(fp, arc); added.append(str(arc))
                _ZIP_DISPATCH = {"file": _zip_file, "dir": _zip_dir}
                ptype = "file" if src.is_file() else "dir" if src.is_dir() else None
                h = _ZIP_DISPATCH.get(ptype)
                h(src) if h else None
        return {
            "success":     True,
            "archive":     str(output),
            "files_added": len(added),
            "size_mb":     round(output.stat().st_size / 1e6, 3),
        }

    def unzip_file(self, archive_path: str, destination: str = None,
                    pattern: str = None,
                    password: str = None) -> Dict:
        """Extract ZIP archive."""
        archive = self._validate(archive_path)
        dst     = Path(destination) if destination else archive.parent / archive.stem
        dst.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(archive, "r") as zf:
            if password:
                zf.setpassword(password.encode())
            names = zf.namelist()
            if pattern:
                names = fnmatch.filter(names, pattern)
            for name in names:
                zf.extract(name, dst)

        return {"success": True, "archive": str(archive), "extracted_to": str(dst),
                "files": len(names)}

    def tar_files(self, sources: List[str], output_path: str,
                   mode: str = "gz") -> Dict:
        """Create a tar archive. mode: gz/bz2/xz/plain."""
        m_map = {"gz": "w:gz", "bz2": "w:bz2", "xz": "w:xz", "plain": "w"}
        mode_str = m_map.get(mode, "w:gz")
        output   = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        added: List[str] = []
        with tarfile.open(str(output), mode_str) as tf:
            for src_str in sources:
                src = Path(src_str)
                tf.add(src, arcname=src.name)
                added.append(src.name)
        return {"success": True, "archive": str(output), "files": len(added),
                "size_mb": round(output.stat().st_size / 1e6, 3)}

    def untar_file(self, archive_path: str, destination: str = None) -> Dict:
        """Extract tar archive."""
        archive = self._validate(archive_path)
        dst     = Path(destination) if destination else archive.parent / archive.stem
        dst.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(archive)) as tf:
            members = tf.getnames()
            tf.extractall(dst)
        return {"success": True, "archive": str(archive), "extracted_to": str(dst),
                "files": len(members)}

    def compress_gzip(self, source: str, output_path: str = None) -> Dict:
        src = self._validate(source)
        dst = Path(output_path or str(src) + ".gz")
        with open(src, "rb") as f_in:
            with gzip.open(dst, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return {"success": True, "source": str(src), "compressed": str(dst),
                "ratio": round(dst.stat().st_size / src.stat().st_size, 2)}

    def decompress_gzip(self, archive_path: str, output_path: str = None) -> Dict:
        archive = self._validate(archive_path)
        out = Path(output_path or str(archive).rstrip(".gz"))
        with gzip.open(archive, "rb") as f_in:
            with open(out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return {"success": True, "archive": str(archive), "extracted": str(out)}

    def compress_bz2(self, source: str, output_path: str = None) -> Dict:
        src = self._validate(source)
        dst = Path(output_path or str(src) + ".bz2")
        with open(src, "rb") as f_in:
            with bz2.open(dst, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return {"success": True, "compressed": str(dst)}

    def decompress_bz2(self, archive_path: str, output_path: str = None) -> Dict:
        archive = self._validate(archive_path)
        out = Path(output_path or str(archive).rstrip(".bz2"))
        with bz2.open(archive, "rb") as f_in:
            with open(out, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
        return {"success": True, "extracted": str(out)}

    def list_archive(self, archive_path: str) -> Dict:
        """List contents of a ZIP or tar archive."""
        archive = self._validate(archive_path)
        suffix  = archive.suffix.lower()

        def _list_zip():
            with zipfile.ZipFile(archive, "r") as zf:
                return [{"name": info.filename, "size": info.file_size,
                          "compressed": info.compress_size}
                        for info in zf.infolist()]

        def _list_tar():
            with tarfile.open(str(archive)) as tf:
                return [{"name": m.name, "size": m.size,
                          "type": "dir" if m.isdir() else "file"}
                        for m in tf.getmembers()]

        _ARCH_DISPATCH = {
            ".zip": _list_zip,
            ".tar": _list_tar,
            ".gz":  _list_tar,
            ".tgz": _list_tar,
            ".bz2": _list_tar,
            ".xz":  _list_tar,
        }
        
        handler = _ARCH_DISPATCH.get(suffix)
        if not handler:
            return {"success": False, "error": f"Unknown archive type: {suffix}"}
            
        entries = handler()

        return {"success": True, "archive": str(archive),
                "files": len(entries), "entries": entries[:500]}

    def extract_file(self, archive_path: str, filename: str,
                      destination: str = None) -> Dict:
        """Extract a specific file from an archive."""
        return self.extract_from_archive(archive_path, filename, destination)

    def extract_from_archive(self, archive_path: str,
                              filename: str, destination: str = None) -> Dict:
        archive = self._validate(archive_path)
        dst     = Path(destination) if destination else archive.parent
        dst.mkdir(parents=True, exist_ok=True)

        if archive.suffix.lower() == ".zip":
            with zipfile.ZipFile(archive, "r") as zf:
                if filename not in zf.namelist():
                    return {"success": False, "error": f"'{filename}' not in archive"}
                zf.extract(filename, dst)
        else:
            with tarfile.open(str(archive)) as tf:
                try:
                    tf.extract(filename, dst)
                except KeyError:
                    return {"success": False, "error": f"'{filename}' not in archive"}

        return {"success": True, "extracted": filename, "to": str(dst / filename)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Diff / Patch
    # ─────────────────────────────────────────────────────────────────────────

    def diff_files(self, path_a: str, path_b: str,
                    context_lines: int = 3) -> Dict:
        """Generate unified diff between two text files."""
        a = self._validate(path_a)
        b = self._validate(path_b)
        enc_a = self._sniff_encoding(a) or "utf-8"
        enc_b = self._sniff_encoding(b) or "utf-8"
        lines_a = a.read_text(enc_a).splitlines(keepends=True)
        lines_b = b.read_text(enc_b).splitlines(keepends=True)
        diff    = "".join(difflib.unified_diff(
            lines_a, lines_b,
            fromfile=str(a), tofile=str(b),
            n=context_lines,
        ))
        added   = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        return {
            "success":       True,
            "diff":          diff,
            "added_lines":   added,
            "removed_lines": removed,
            "identical":     diff == "",
        }

    def diff_directories(self, dir_a: str, dir_b: str) -> Dict:
        """Compare two directories: new files, deleted files, changed files."""
        a = Path(dir_a)
        b = Path(dir_b)
        files_a = {str(p.relative_to(a)) for p in a.rglob("*") if p.is_file()}
        files_b = {str(p.relative_to(b)) for p in b.rglob("*") if p.is_file()}

        only_a   = sorted(files_a - files_b)
        only_b   = sorted(files_b - files_a)
        common   = files_a & files_b
        changed  = []
        for name in sorted(common):
            ha = self._file_hash(a / name)
            hb = self._file_hash(b / name)
            if ha != hb:
                changed.append(name)

        return {
            "success":       True,
            "dir_a":         str(a),
            "dir_b":         str(b),
            "only_in_a":     only_a[:100],
            "only_in_b":     only_b[:100],
            "changed":       changed[:100],
            "identical":     sorted(common - set(changed))[:20],
            "total_changed": len(changed),
        }

    def apply_diff_to_file(self, path: str, diff_text: str,
                            output_path: str = None) -> Dict:
        """Apply a unified diff patch to a file."""
        p = self._validate(path)
        patch_cmd = shutil.which("patch")
        if not patch_cmd:
            return {"success": False, "error": "patch command not found"}

        out = output_path or str(p) + ".patched"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".patch",
                                          delete=False) as f:
            f.write(diff_text); tmp = f.name
        try:
            r = __import__("subprocess").run(
                [patch_cmd, "-o", out, str(p), tmp],
                capture_output=True, text=True, timeout=30,
            )
            return {"success": r.returncode == 0, "patched_file": out,
                    "output": r.stdout + r.stderr}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Permissions
    # ─────────────────────────────────────────────────────────────────────────

    def get_permissions(self, path: str) -> Dict:
        p   = self._validate(path)
        st  = p.stat()
        mode = st.st_mode
        return {
            "success":    True,
            "octal":      oct(mode)[-3:],
            "readable":   os.access(p, os.R_OK),
            "writable":   os.access(p, os.W_OK),
            "executable": os.access(p, os.X_OK),
            "owner_r":    bool(mode & stat.S_IRUSR),
            "owner_w":    bool(mode & stat.S_IWUSR),
            "owner_x":    bool(mode & stat.S_IXUSR),
        }

    def set_permissions(self, path: str, mode: int) -> Dict:
        """Set permission bits (octal int e.g. 0o644)."""
        p = self._validate(path)
        os.chmod(p, mode)
        return {"success": True, "path": str(p), "mode": oct(mode)}

    def make_executable(self, path: str) -> Dict:
        p = self._validate(path)
        current = p.stat().st_mode
        p.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return {"success": True, "path": str(p)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Encoding
    # ─────────────────────────────────────────────────────────────────────────

    def convert_encoding(self, path: str, from_encoding: str = None,
                          to_encoding: str = "utf-8",
                          output_path: str = None) -> Dict:
        """Convert file from one text encoding to another."""
        p = self._validate(path)
        src_enc = from_encoding or self._sniff_encoding(p) or "latin-1"
        text = p.read_text(encoding=src_enc, errors="replace")
        dst  = Path(output_path or str(p))
        dst.write_text(text, encoding=to_encoding)
        return {"success": True, "path": str(dst), "from": src_enc, "to": to_encoding}

    def normalize_line_endings(self, path: str,
                                 style: str = "lf",
                                 output_path: str = None) -> Dict:
        """Normalize line endings: lf (\n) / crlf (\r\n) / cr (\r)."""
        p = self._validate(path)
        enc  = self._sniff_encoding(p) or "utf-8"
        text = p.read_bytes().decode(enc, errors="replace")
        # Normalize all to LF first
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # O(1) dict dispatch: style → transform function
        _LINE_END = {
            "crlf": lambda t: t.replace("\n", "\r\n"),
            "cr":   lambda t: t.replace("\n", "\r"),
            "lf":   lambda t: t,
        }
        text = _LINE_END.get(style, lambda t: t)(text)
        dst = Path(output_path or str(p))
        dst.write_bytes(text.encode(enc))
        return {"success": True, "path": str(dst), "style": style}

    # ─────────────────────────────────────────────────────────────────────────
    #  Organize
    # ─────────────────────────────────────────────────────────────────────────

    def organize_files(self, source_dir: str,
                        by: str = "extension",
                        dry_run: bool = True,
                        dest_dir: str = None) -> Dict:
        """Organize files by extension/date/size/type."""
        src = Path(source_dir)
        dst = Path(dest_dir) if dest_dir else src
        plan: List[Dict] = []

        for fp in src.iterdir():
            if not fp.is_file():
                continue
            # O(1) dict dispatch: by → folder-name function
            def _by_ext(p):   return p.suffix[1:].lower() or "no_extension"
            def _by_date(p):
                mt = datetime.fromtimestamp(p.stat().st_mtime)
                return mt.strftime("%Y-%m")
            def _by_size(p):
                sz = p.stat().st_size
                _BINS = [(1e9, "huge"), (100e6, "large"), (1e6, "medium")]
                return next((name for thr, name in _BINS if sz > thr), "small")
            def _by_type(p):
                mt, _ = mimetypes.guess_type(str(p))
                return mt.split("/")[0] if mt else "unknown"
            _FOLDER_FN = {
                "extension": _by_ext,
                "date":      _by_date,
                "size":      _by_size,
                "type":      _by_type,
            }
            folder = _FOLDER_FN.get(by, lambda p: "other")(fp)

            dest = dst / folder / fp.name
            plan.append({"source": str(fp), "destination": str(dest), "action": "move"})

        if not dry_run:
            for item in plan:
                d = Path(item["destination"])
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(item["source"], str(d))

        return {"success": True, "dry_run": dry_run,
                "files_affected": len(plan), "plan": plan[:50]}

    def batch_rename(self, directory: str, pattern: str,
                      replacement: str, regex: bool = False,
                      dry_run: bool = True) -> Dict:
        """Batch rename files matching pattern."""
        d     = Path(directory)
        renames: List[Dict] = []
        for fp in d.iterdir():
            if not fp.is_file():
                continue
            if regex:
                new_name = re.sub(pattern, replacement, fp.name)
            else:
                new_name = fp.name.replace(pattern, replacement)
            if new_name != fp.name:
                renames.append({"old": fp.name, "new": new_name,
                                  "old_path": str(fp), "new_path": str(d / new_name)})

        if not dry_run:
            for r in renames:
                Path(r["old_path"]).rename(r["new_path"])

        return {"success": True, "dry_run": dry_run,
                "count": len(renames), "renames": renames[:100]}

    def move_files_by_date(self, source_dir: str, dest_dir: str,
                            fmt: str = "%Y/%m",
                            dry_run: bool = True) -> Dict:
        """Organize files into date-based folder hierarchy."""
        src   = Path(source_dir)
        moved: List[Dict] = []
        for fp in src.rglob("*"):
            if not fp.is_file():
                continue
            mtime  = datetime.fromtimestamp(fp.stat().st_mtime)
            folder = Path(dest_dir) / mtime.strftime(fmt)
            dest   = folder / fp.name
            moved.append({"source": str(fp), "destination": str(dest)})
            if not dry_run:
                folder.mkdir(parents=True, exist_ok=True)
                shutil.move(str(fp), str(dest))

        return {"success": True, "dry_run": dry_run, "count": len(moved),
                "moves": moved[:50]}

    def move_files_by_type(self, source_dir: str, dest_dir: str,
                            dry_run: bool = True) -> Dict:
        """Move files into subdirs by MIME type category."""
        return self.organize_files(source_dir, by="type",
                                    dry_run=dry_run, dest_dir=dest_dir)

    # ─────────────────────────────────────────────────────────────────────────
    #  File Watching
    # ─────────────────────────────────────────────────────────────────────────

    def start_watching(self, path: str, interval: float = 2.0,
                        duration: float = 60.0,
                        events: List[str] = None) -> Dict:
        """Watch a file/directory for changes. Returns snapshot of changes."""
        root    = Path(path)
        events  = events or ["created", "modified", "deleted"]
        changes: List[Dict] = []

        # Initial snapshot
        def snapshot() -> Dict[str, float]:
            snap: Dict[str, float] = {}
            if root.is_file():
                try:
                    snap[str(root)] = root.stat().st_mtime
                except Exception:
                    pass
            else:
                for fp in root.rglob("*"):
                    try:
                        snap[str(fp)] = fp.stat().st_mtime
                    except Exception:
                        pass
            return snap

        prev = snapshot()
        t0   = time.monotonic()
        self._watch_stop = False

        while (time.monotonic() - t0) < duration and not self._watch_stop:
            time.sleep(interval)
            curr = snapshot()
            for fpath, mtime in curr.items():
                # Branchless change detection
                is_new = fpath not in prev
                is_mod = not is_new and abs(mtime - prev[fpath]) > 0.001
                if is_new:
                    changes.append({"event": "created", "path": fpath, "ts": datetime.now().isoformat()})
                if is_mod:
                    changes.append({"event": "modified", "path": fpath, "ts": datetime.now().isoformat()})
            for fpath in prev:
                if fpath not in curr:
                    changes.append({"event": "deleted", "path": fpath,
                                     "ts": datetime.now().isoformat()})
            prev = curr

        return {"success": True, "watched": str(root), "changes": changes,
                "duration_s": duration, "total_events": len(changes)}

    def stop_watching(self) -> Dict:
        self._watch_stop = True
        return {"success": True}

    # ─────────────────────────────────────────────────────────────────────────
    #  Text Stats
    # ─────────────────────────────────────────────────────────────────────────

    def tail_file(self, path: str, lines: int = 20,
                   encoding: str = "utf-8") -> Dict:
        """Return last N lines of a file (memory efficient)."""
        p      = self._validate(path)
        result: List[str] = []
        enc    = encoding or self._sniff_encoding(p) or "utf-8"
        with open(p, "r", encoding=enc, errors="replace") as f:
            for line in f:
                result.append(line)
                if len(result) > lines:
                    result.pop(0)
        return {"success": True, "path": str(p), "lines": result, "count": len(result)}

    def head_file(self, path: str, lines: int = 20,
                   encoding: str = "utf-8") -> Dict:
        p   = self._validate(path)
        enc = encoding or self._sniff_encoding(p) or "utf-8"
        result: List[str] = []
        with open(p, "r", encoding=enc, errors="replace") as f:
            for i, line in enumerate(f):
                if i >= lines:
                    break
                result.append(line)
        return {"success": True, "path": str(p), "lines": result, "count": len(result)}

    def count_lines(self, path: str, encoding: str = "utf-8") -> Dict:
        p   = self._validate(path)
        enc = encoding or self._sniff_encoding(p) or "utf-8"
        n   = 0
        with open(p, "r", encoding=enc, errors="replace") as f:
            for _ in f:
                n += 1
        return {"success": True, "path": str(p), "lines": n}

    def count_words(self, path: str, encoding: str = "utf-8") -> Dict:
        p    = self._validate(path)
        enc  = encoding or self._sniff_encoding(p) or "utf-8"
        text = p.read_text(enc, errors="replace")
        words = len(text.split())
        chars = len(text)
        lines = text.count("\n")
        return {"success": True, "path": str(p), "words": words,
                "characters": chars, "lines": lines}

    # ─────────────────────────────────────────────────────────────────────────
    #  Helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _validate(self, path: str) -> Path:
        p = Path(path).resolve()
        return p

    def _check_protected(self, p: Path):
        ps = str(p)
        for blocked in self.PROTECTED_PATHS:
            if ps.startswith(blocked):
                raise PermissionError(f"Access to '{blocked}' is blocked")

    def _sniff_encoding(self, p: Path) -> Optional[str]:
        if _CHARDET_OK:
            try:
                raw = p.read_bytes()[:10000]
                result = chardet.detect(raw)
                return result.get("encoding")
            except Exception:
                pass
        return "utf-8"

    def _file_hash(self, p: Path, algorithm: str = "md5") -> str:
        h = hashlib.new(algorithm)
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _human_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"

    def _log_op(self, action: str, params: Dict, success: bool, error: str = None):
        self.operation_log.append({
            "ts":      datetime.now().isoformat(),
            "action":  action,
            "params":  str(params)[:200],
            "success": success,
            "error":   error,
        })
        if len(self.operation_log) > 5000:
            self.operation_log = self.operation_log[-2000:]

    def _get_log(self, limit: int = 50) -> Dict:
        return {"success": True, "log": self.operation_log[-limit:]}

    def get_operation_log(self) -> List[Dict]:
        return self.operation_log[-50:]
