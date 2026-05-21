"""
Code Agent — Write, analyse, refactor, profile, test, and execute code.
Production grade: real subprocess execution, AST analysis, git integration,
pip management, virtual-env creation, code search, diff generation, linting.
"""
from __future__ import annotations

import ast
import difflib
import hashlib
import importlib
import inspect
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import tokenize
import traceback
from collections import defaultdict, Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Generator

from core.base_agent import BaseAgent
from core.llm_router import get_router

logger = logging.getLogger("CodeAgent")


# ─────────────────────────────────────────────────────────────────────────────
#  Data Classes
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CodeIssue:
    severity: str          # "error" | "warning" | "info"
    line: int
    column: int
    code: str              # rule id, e.g. "E501"
    message: str
    source: str            # "ast" | "pylint" | "flake8" | "mypy" | "bandit" | "llm"


@dataclass
class RefactorSuggestion:
    kind: str              # "extract_function" | "rename" | "split_class" | ...
    location: Tuple[int, int]   # (start_line, end_line)
    description: str
    rationale: str
    code_before: str
    code_after: str


@dataclass
class ExecutionResult:
    success: bool
    stdout: str
    stderr: str
    returncode: int
    execution_time: float
    peak_memory_mb: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CodeMetrics:
    lines_total: int
    lines_code: int
    lines_blank: int
    lines_comment: int
    functions: int
    classes: int
    imports: int
    cyclomatic_complexity: int
    cognitive_complexity: int
    max_depth: int
    duplicated_blocks: int
    maintainability_index: float


# ─────────────────────────────────────────────────────────────────────────────
#  AST Helpers
# ─────────────────────────────────────────────────────────────────────────────

class ComplexityVisitor(ast.NodeVisitor):
    """Cyclomatic + cognitive complexity calculator."""

    def __init__(self):
        self.cyclomatic = 1
        self.cognitive  = 0
        self._nesting   = 0

    def visit_If(self, node):
        self.cyclomatic += 1
        self.cognitive  += 1 + self._nesting
        self._nesting   += 1
        self.generic_visit(node)
        self._nesting   -= 1

    def visit_While(self, node):
        self.cyclomatic += 1
        self.cognitive  += 1 + self._nesting
        self._nesting   += 1
        self.generic_visit(node)
        self._nesting   -= 1

    def visit_For(self, node):
        self.cyclomatic += 1
        self.cognitive  += 1 + self._nesting
        self._nesting   += 1
        self.generic_visit(node)
        self._nesting   -= 1

    def visit_ExceptHandler(self, node):
        self.cyclomatic += 1
        self.cognitive  += 1 + self._nesting
        self.generic_visit(node)

    def visit_BoolOp(self, node):
        self.cyclomatic += len(node.values) - 1
        self.generic_visit(node)

    def visit_comprehension(self, node):
        self.cyclomatic += 1
        self.generic_visit(node)


class MaxDepthVisitor(ast.NodeVisitor):
    """Measure maximum nesting depth."""

    def __init__(self):
        self.max_depth = 0
        self._depth    = 0

    def _enter(self, node):
        self._depth   += 1
        self.max_depth = max(self.max_depth, self._depth)
        self.generic_visit(node)
        self._depth   -= 1

    visit_If         = _enter
    visit_For        = _enter
    visit_While      = _enter
    visit_With       = _enter
    visit_Try        = _enter
    visit_FunctionDef = _enter
    visit_AsyncFunctionDef = _enter
    visit_ClassDef   = _enter


class DuplicateBlockDetector:
    """Detect duplicate code blocks by hashing normalised token sequences."""

    MIN_BLOCK_LINES = 6

    def count_duplicates(self, code: str) -> int:
        lines = code.splitlines()
        hashes: Dict[str, List[int]] = defaultdict(list)
        for i in range(len(lines) - self.MIN_BLOCK_LINES + 1):
            block  = "\n".join(lines[i:i + self.MIN_BLOCK_LINES])
            digest = hashlib.md5(block.strip().encode()).hexdigest()
            hashes[digest].append(i)
        return sum(1 for v in hashes.values() if len(v) > 1)


# ─────────────────────────────────────────────────────────────────────────────
#  Code Agent
# ─────────────────────────────────────────────────────────────────────────────

class CodeAgent(BaseAgent):
    """
    Full production code agent.
    write → analyse → refactor → fix → profile → test → format → execute.
    Git, pip, venv, linting, security scanning all wired up.
    """

    HIGH_RISK_MODULES = {"ctypes", "winreg", "nt", "_winapi", "cffi"}
    BLOCKED_MODULES   = {"socket"}
    BLOCKED_CALLS     = {"compile"}

    ALLOWED_MODULES = {
        "math", "random", "datetime", "json", "re", "string",
        "collections", "itertools", "functools", "statistics",
        "os", "os.path", "sys", "pathlib", "io", "textwrap",
        "typing", "dataclasses", "abc", "enum", "copy",
        "time", "calendar", "hashlib", "hmac", "base64",
        "struct", "array", "bisect", "heapq", "queue",
        "threading", "multiprocessing", "concurrent",
        "subprocess", "shutil", "glob", "fnmatch", "tempfile",
        "pickle", "shelve", "csv", "configparser",
        "logging", "warnings", "contextlib", "weakref",
        "inspect", "types", "operator", "functools",
        "decimal", "fractions", "cmath", "numbers",
        "zipfile", "tarfile", "gzip", "bz2", "lzma",
        "html", "html.parser", "xml", "xml.etree",
        "urllib", "urllib.parse", "urllib.request",
        "http", "http.client", "http.server",
        "email", "mimetypes", "mailbox",
        "unittest", "doctest", "pdb",
        "pprint", "reprlib", "traceback",
        "argparse", "getopt", "shlex",
        "numpy", "pandas", "matplotlib", "PIL", "Pillow",
        "requests", "aiohttp", "httpx",
        "scipy", "sklearn",
        "cv2", "pyautogui",
        "sqlalchemy", "sqlite3",
        "flask", "fastapi",
    }

    MAX_OUTPUT   = 50_000   # chars
    EXEC_TIMEOUT = 60       # seconds default

    def __init__(self):
        super().__init__()
        self.router            = get_router()
        self.execution_history: List[ExecutionResult]   = []
        self.refactor_history:  List[Dict]              = []
        self._dup_detector     = DuplicateBlockDetector()
        self._git_available    = shutil.which("git") is not None
        self._ruff_available   = shutil.which("ruff") is not None
        self._mypy_available   = shutil.which("mypy") is not None
        self._bandit_available = shutil.which("bandit") is not None
        self._black_available  = shutil.which("black") is not None

        self.handlers = {
            "write_code":            self.write_code,
            "execute_python":        self.execute_python,
            "execute_javascript":    self.execute_javascript,
            "execute_bash":          self.execute_bash,
            "execute_powershell":    self.execute_powershell,
            "analyze_code":          self.analyze_code,
            "calculate_metrics":     self.calculate_metrics,
            "find_issues":           self.find_issues,
            "security_scan":         self.security_scan,
            "detect_duplicates":     self.detect_duplicates,
            "find_dead_code":        self.find_dead_code,
            "check_types":           self.check_types,
            "fix_code":              self.fix_code,
            "refactor_code":         self.refactor_code,
            "extract_function":      self.extract_function,
            "rename_symbol":         self.rename_symbol,
            "add_type_hints":        self.add_type_hints,
            "add_docstrings":        self.add_docstrings,
            "remove_unused_imports": self.remove_unused_imports,
            "explain_code":          self.explain_code,
            "format_code":           self.format_code,
            "lint_code":             self.lint_code,
            "generate_tests":        self.generate_tests,
            "run_tests":             self.run_tests,
            "run_coverage":          self.run_coverage,
            "profile_code":          self.profile_code,
            "benchmark_code":        self.benchmark_code,
            "generate_script":       self.generate_script,
            "create_module":         self.create_module,
            "create_package":        self.create_package,
            "git_status":            self.git_status,
            "git_diff":              self.git_diff,
            "git_log":               self.git_log,
            "git_commit":            self.git_commit,
            "git_create_branch":     self.git_create_branch,
            "git_stash":             self.git_stash,
            "pip_install":           self.pip_install,
            "pip_list":              self.pip_list,
            "pip_check":             self.pip_check,
            "create_venv":           self.create_venv,
            "generate_requirements": self.generate_requirements,
            "diff_code":             self.diff_code,
            "apply_patch":           self.apply_patch,
            "search_code":           self.search_code,
            "find_usages":           self.find_usages,
            "get_history":           self._history_action,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Write Code
    # ─────────────────────────────────────────────────────────────────────────

    def write_code(self, description: str, language: str = "python",
                   context: str = "", constraints: List[str] = None,
                   style: str = "production") -> Dict:
        """Generate production-quality code from description using LLM."""
        constraints = constraints or []
        base_constraints = [
            "Full error handling with specific exception types",
            "Type hints on all function signatures",
            "Google-style docstrings",
            "Logging (not print) for diagnostics",
            "A __main__ block for standalone execution",
            "No placeholder TODOs — every function fully implemented",
        ]
        all_constraints = base_constraints + constraints
        bullet_list = "\n".join(f"  - {c}" for c in all_constraints)

        prompt = (
            f"Write {style}-quality {language} code for the following task:\n\n"
            f"{description}\n\n"
            f"Mandatory requirements:\n{bullet_list}\n\n"
            f"Extra context:\n{context}\n\n"
            "Return ONLY the complete code inside a single fenced code block. "
            "No explanation outside the block."
        )
        resp = self.router.quick_request(prompt, task_type="coding")
        code = self._extract_code(resp, language)

        result: Dict = {"success": True, "code": code, "language": language}

        # Python-specific validation — frozenset guard, no elif chain
        is_python = language in frozenset({"python"})
        result = self._python_validate_result(code, result) if is_python else result
        return result

    # ─────────────────────────────────────────────────────────────────────────
    #  Execute Python
    # ─────────────────────────────────────────────────────────────────────────

    def execute_python(self, code: str, timeout: int = None,
                       capture_output: bool = True,
                       env_vars: Dict[str, str] = None,
                       working_dir: str = None,
                       safe_mode: bool = True) -> Dict:
        """Execute Python code in a subprocess. Full real execution."""
        if safe_mode:
            safety = self._check_code_safety(code)
            if not safety["safe"]:
                return {
                    "success": False,
                    "error": f"Safety check failed: {safety['reason']}",
                    "violations": safety["violations"],
                }

        timeout = timeout or self.EXEC_TIMEOUT

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                         delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name

        env = os.environ.copy()
        if env_vars:
            env.update(env_vars)

        start = time.monotonic()
        try:
            proc = subprocess.Popen(
                [sys.executable, tmp],
                stdout=subprocess.PIPE if capture_output else None,
                stderr=subprocess.PIPE if capture_output else None,
                text=True, encoding="utf-8", errors="replace",
                env=env, cwd=working_dir,
            )
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                # Secondary timeout to prevent double-hang during cleanup
                stdout, stderr = proc.communicate(timeout=5)
                return {
                    "success": False,
                    "error": f"Execution timed out after {timeout}s",
                    "stdout": stdout or "", "stderr": stderr or "",
                }

            elapsed = time.monotonic() - start
            res = ExecutionResult(
                success=proc.returncode == 0,
                stdout=(stdout or "")[:self.MAX_OUTPUT],
                stderr=(stderr or "")[:self.MAX_OUTPUT],
                returncode=proc.returncode,
                execution_time=round(elapsed, 3),
            )
            self.execution_history.append(res)
            if len(self.execution_history) > 2000:
                self.execution_history = self.execution_history[-1000:]
            return {
                "success": res.success,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "returncode": res.returncode,
                "execution_time": res.execution_time,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Execute JavaScript / Bash / PowerShell
    # ─────────────────────────────────────────────────────────────────────────

    def execute_javascript(self, code: str, timeout: int = 30,
                            node_version: str = None) -> Dict:
        """Execute JS via Node.js. Wraps code in try/catch for clean error reporting."""
        node = shutil.which("node") or shutil.which("nodejs")
        if not node:
            return {"success": False, "error": "Node.js not found. Install from nodejs.org"}

        wrapped = (
            f"'use strict';\n"
            f"(async () => {{\ntry {{\n{code}\n}} "
            f"catch(e){{ console.error('[ERROR]', e.message); process.exit(1); }}\n}})();\n"
        )
        with tempfile.NamedTemporaryFile(mode="w", suffix=".js",
                                          delete=False, encoding="utf-8") as f:
            f.write(wrapped)
            tmp = f.name
        try:
            proc = subprocess.Popen(
                [node, tmp], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout[:self.MAX_OUTPUT],
                "stderr": stderr[:self.MAX_OUTPUT],
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"success": False, "error": f"JS execution timed out after {timeout}s"}
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def execute_bash(self, code: str, timeout: int = 60,
                     shell: str = None) -> Dict:
        """Execute shell script. Uses cmd.exe on Windows, bash/sh on Unix."""
        if os.name == "nt":
            ext = ".bat"
            interpreter = ["cmd.exe", "/C"]
        else:
            sh = shell or shutil.which("bash") or shutil.which("sh") or "sh"
            ext = ".sh"
            interpreter = [sh]

        with tempfile.NamedTemporaryFile(mode="w", suffix=ext,
                                          delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name

        try:
            proc = subprocess.Popen(
                interpreter + [tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout[:self.MAX_OUTPUT],
                "stderr": stderr[:self.MAX_OUTPUT],
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"success": False, "error": f"Script timed out after {timeout}s"}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def execute_powershell(self, code: str, timeout: int = 60) -> Dict:
        """Execute PowerShell script. Windows only."""
        ps = shutil.which("pwsh") or shutil.which("powershell")
        if not ps:
            return {"success": False, "error": "PowerShell not found"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1",
                                          delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp = f.name
        try:
            proc = subprocess.Popen(
                [ps, "-ExecutionPolicy", "Bypass", "-NonInteractive", "-File", tmp],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace",
            )
            stdout, stderr = proc.communicate(timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "stdout": stdout[:self.MAX_OUTPUT],
                "stderr": stderr[:self.MAX_OUTPUT],
            }
        except subprocess.TimeoutExpired:
            proc.kill()
            return {"success": False, "error": "PowerShell timed out"}
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Analysis
    # ─────────────────────────────────────────────────────────────────────────

    def analyze_code(self, code: str, language: str = "python",
                     include_llm: bool = True) -> Dict:
        """Full static analysis: AST + linters + LLM insight."""
        result = {
            "success": True,
            "language": language,
            "issues": [],
            "suggestions": [],
            "metrics": {},
        }

        # Python-specific analysis tools — frozenset guard, no elif
        is_python = language in frozenset({"python"})
        self._python_run_static_analysis(code, result) if is_python else None

        if include_llm:
            try:
                prompt = (
                    f"Analyze this {language} code for bugs, anti-patterns, "
                    f"and improvements:\n```{language}\n{code[:4000]}\n```\n"
                    'Return JSON only: {"issues":[{"severity":"error|warning|info",'
                    '"line":0,"message":"...","source":"llm"}],'
                    '"suggestions":["..."]}'
                )
                resp = self.router.quick_request(prompt, task_type="coding")
                m = re.search(r"\{.*\}", resp, re.DOTALL)
                if m:
                    data = json.loads(m.group())
                    result["issues"].extend(data.get("issues", []))
                    result["suggestions"].extend(data.get("suggestions", []))
            except Exception as e:
                logger.warning(f"LLM analysis step failed: {e}")

        # Sort by severity
        sev_order = {"error": 0, "warning": 1, "info": 2}
        result["issues"].sort(key=lambda x: sev_order.get(x.get("severity", "info"), 3))
        result["error_count"]   = sum(1 for i in result["issues"] if i.get("severity") == "error")
        result["warning_count"] = sum(1 for i in result["issues"] if i.get("severity") == "warning")
        return result

    def calculate_metrics(self, code: str, language: str = "python") -> Dict:
        """Compute code quality metrics: LOC, complexity, depth, duplicates, MI."""
        if language != "python":
            lines = code.splitlines()
            return {
                "success": True,
                "lines_total": len(lines),
                "language": language,
                "note": "Deep metrics only available for Python",
            }

        _, metrics = self._ast_analyze(code)
        return {"success": True, **metrics}

    def find_issues(self, code: str, language: str = "python",
                    min_severity: str = "warning") -> Dict:
        """Run all linters and return filtered issues."""
        all_issues = self.analyze_code(code, language, include_llm=False)
        sev_map = {"error": 0, "warning": 1, "info": 2}
        threshold = sev_map.get(min_severity, 1)
        filtered = [i for i in all_issues.get("issues", [])
                    if sev_map.get(i.get("severity", "info"), 2) <= threshold]
        return {
            "success": True,
            "issues": filtered,
            "count": len(filtered),
            "min_severity": min_severity,
        }

    def security_scan(self, code: str, language: str = "python") -> Dict:
        """Dedicated security scan using bandit + LLM."""
        findings: List[Dict] = []

        # Frozenset guard: bandit only for Python — no if/else branching
        (language in frozenset({"python"}) and self._bandit_available and
         findings.extend(self._run_bandit(code, severity="LOW") or []))

        # LLM security review
        try:
            prompt = (
                f"Security review this {language} code. Find: SQL injection, "
                "command injection, path traversal, hardcoded credentials, "
                "insecure random, missing auth, XSS, SSRF, timing attacks.\n"
                f"```{language}\n{code[:4000]}\n```\n"
                'Return JSON: {"findings":[{"severity":"CRITICAL|HIGH|MEDIUM|LOW",'
                '"line":0,"cwe":"CWE-xxx","title":"...","description":"...","fix":"..."}]}'
            )
            resp = self.router.quick_request(prompt, task_type="coding")
            m = re.search(r"\{.*\}", resp, re.DOTALL)
            if m:
                data = json.loads(m.group())
                findings.extend(data.get("findings", []))
        except Exception as e:
            logger.warning(f"LLM security scan failed: {e}")

        sev_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        findings.sort(key=lambda x: sev_order.get(x.get("severity", "LOW"), 4))
        return {
            "success": True,
            "findings": findings,
            "critical": sum(1 for f in findings if f.get("severity") == "CRITICAL"),
            "high":     sum(1 for f in findings if f.get("severity") == "HIGH"),
        }

    def detect_duplicates(self, code: str) -> Dict:
        """Find duplicated code blocks (min 6 lines)."""
        lines = code.splitlines()
        hashes: Dict[str, List[int]] = defaultdict(list)
        BLOCK = 6
        for i in range(len(lines) - BLOCK + 1):
            block  = "\n".join(lines[i:i + BLOCK])
            digest = hashlib.md5(block.strip().encode()).hexdigest()
            hashes[digest].append(i + 1)

        dupes = [
            {"lines": starts, "count": len(starts)}
            for starts in hashes.values()
            if len(starts) > 1
        ]
        return {
            "success": True,
            "duplicate_blocks": len(dupes),
            "details": dupes[:20],
        }

    def find_dead_code(self, code: str, language: str = "python") -> Dict:
        """Find functions/classes/variables that are never used in the module."""
        if language != "python":
            return {"success": False, "error": "Dead code detection only for Python"}

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"success": False, "error": f"Syntax error: {e}"}

        defined: Dict[str, int] = {}
        def _handle_func(n): defined[n.name] = n.lineno
        def _handle_class(n): defined[n.name] = n.lineno
        def _handle_assign(n):
            for t in n.targets:
                if isinstance(t, ast.Name): defined[t.id] = n.lineno

        _NODE_DISPATCH = {
            ast.FunctionDef:      _handle_func,
            ast.AsyncFunctionDef: _handle_func,
            ast.ClassDef:         _handle_class,
            ast.Assign:           _handle_assign,
        }
        
        for node in ast.walk(tree):
            handler = _NODE_DISPATCH.get(type(node))
            handler(node) if handler else None

        used: set = set()
        _WALK_HANDLERS = {
            ast.Name:      lambda n: used.add(n.id) if isinstance(n.ctx, ast.Load) else None,
            ast.Attribute: lambda n: used.add(n.attr),
        }
        for node in ast.walk(tree):
            handler = _WALK_HANDLERS.get(type(node))
            handler(node) if handler else None

        dead = {name: lineno for name, lineno in defined.items()
                if name not in used and not name.startswith("_")}
        return {
            "success": True,
            "dead_symbols": dead,
            "count": len(dead),
        }

    def check_types(self, code: str, strict: bool = False) -> Dict:
        """Run mypy type checking on code snippet."""
        if not self._mypy_available:
            return {"success": False, "error": "mypy not installed. Run: pip install mypy"}

        issues = self._run_mypy(code, strict=strict)
        return {
            "success": len(issues) == 0,
            "issues": issues,
            "count": len(issues),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Fix / Refactor
    # ─────────────────────────────────────────────────────────────────────────

    def fix_code(self, code: str, error_message: str = None,
                 language: str = "python", auto_verify: bool = True) -> Dict:
        """Fix code using LLM. Optionally verifies the fix parses."""
        context = f"\nError to fix: {error_message}" if error_message else ""
        prompt = (
            f"Fix this {language} code.{context}\n"
            f"```{language}\n{code}\n```\n"
            "Rules: preserve all existing logic, only fix the bug, "
            "keep same function signatures.\n"
            "Return ONLY the fixed code in a fenced block."
        )
        resp = self.router.quick_request(prompt, task_type="coding")
        fixed = self._extract_code(resp, language)

        result: Dict = {
            "success": True,
            "original_code": code,
            "fixed_code": fixed,
            "language": language,
            "changed": fixed != code,
        }

        if auto_verify and language == "python" and fixed != code:
            try:
                ast.parse(fixed)
                result["syntax_valid"] = True
            except SyntaxError as e:
                result["syntax_valid"] = False
                result["fix_warning"] = f"Fixed code has syntax error: {e}"

        return result

    def refactor_code(self, code: str, goal: str,
                      language: str = "python") -> Dict:
        """LLM-guided refactoring towards a stated goal."""
        prompt = (
            f"Refactor this {language} code to achieve:\n{goal}\n\n"
            f"Original code:\n```{language}\n{code}\n```\n\n"
            "Requirements:\n"
            "  - Preserve all external interfaces and behaviour\n"
            "  - Improve readability, structure, or performance per the goal\n"
            "  - Add/update docstrings to reflect changes\n"
            "Return ONLY the refactored code in a fenced block, "
            "then a brief 'Changes:' section below the block."
        )
        resp = self.router.quick_request(prompt, task_type="coding")
        refactored = self._extract_code(resp, language)

        # Extract change summary
        changes = ""
        m = re.search(r"changes?:(.*?)(?:\n```|$)", resp, re.IGNORECASE | re.DOTALL)
        if m:
            changes = m.group(1).strip()

        self.refactor_history.append({
            "ts": datetime.now().isoformat(),
            "goal": goal,
            "before_lines": len(code.splitlines()),
            "after_lines": len(refactored.splitlines()),
        })
        return {
            "success": True,
            "refactored_code": refactored,
            "changes_summary": changes,
            "diff": self._make_diff(code, refactored),
        }

    def extract_function(self, code: str, start_line: int, end_line: int,
                         function_name: str, language: str = "python") -> Dict:
        """Extract lines into a named function and replace original with a call."""
        lines = code.splitlines()
        if start_line < 1 or end_line > len(lines) or start_line > end_line:
            return {"success": False, "error": "Invalid line range"}

        block = lines[start_line - 1:end_line]
        indent = len(block[0]) - len(block[0].lstrip())
        dedented = textwrap.dedent("\n".join(block))

        prompt = (
            f"Extract the following {language} code block into a function "
            f"named '{function_name}'.\n"
            f"Block:\n```\n{dedented}\n```\n"
            "Requirements:\n"
            "  - Detect parameters from free variables\n"
            "  - Add return statement if the block produces a value\n"
            "  - Return two code blocks: 1) the new function definition, "
            "2) the replacement call"
        )
        resp = self.router.quick_request(prompt, task_type="coding")
        blocks = re.findall(r"```(?:\w+)?\s*(.*?)```", resp, re.DOTALL)
        if len(blocks) >= 2:
            func_def  = blocks[0].strip()
            call_code = blocks[1].strip()
        else:
            func_def  = self._extract_code(resp, language)
            call_code = f"{function_name}()"

        # Rebuild full code
        new_lines = (
            lines[:start_line - 1]
            + [" " * indent + l for l in call_code.splitlines()]
            + lines[end_line:]
        )
        new_code = func_def + "\n\n" + "\n".join(new_lines)
        return {
            "success": True,
            "new_code": new_code,
            "extracted_function": func_def,
            "replacement_call": call_code,
        }

    def rename_symbol(self, code: str, old_name: str, new_name: str,
                      language: str = "python") -> Dict:
        """Rename a symbol throughout code using regex-aware replacement."""
        if not re.match(r"^[A-Za-z_]\w*$", new_name):
            return {"success": False, "error": "Invalid identifier: " + new_name}

        pattern = r"\b" + re.escape(old_name) + r"\b"
        new_code, count = re.subn(pattern, new_name, code)
        return {
            "success": True,
            "new_code": new_code,
            "replacements": count,
            "diff": self._make_diff(code, new_code),
        }

    def add_type_hints(self, code: str) -> Dict:
        """Use LLM to add missing type hints to Python functions."""
        prompt = (
            "Add complete PEP 484 type hints to all function signatures in this Python code. "
            "Do NOT change any logic. Import typing constructs as needed.\n"
            f"```python\n{code}\n```\n"
            "Return ONLY the annotated code in a single fenced block."
        )
        resp  = self.router.quick_request(prompt, task_type="coding")
        typed = self._extract_code(resp, "python")
        return {
            "success": True,
            "annotated_code": typed,
            "diff": self._make_diff(code, typed),
        }

    def add_docstrings(self, code: str, style: str = "google") -> Dict:
        """Use LLM to add or improve docstrings in Python code."""
        prompt = (
            f"Add {style}-style docstrings to all public functions and classes "
            "in this Python code. Include Args, Returns, and Raises sections. "
            "Do NOT change any logic.\n"
            f"```python\n{code}\n```\n"
            "Return ONLY the code with docstrings in a fenced block."
        )
        resp = self.router.quick_request(prompt, task_type="coding")
        documented = self._extract_code(resp, "python")
        return {
            "success": True,
            "documented_code": documented,
            "diff": self._make_diff(code, documented),
        }

    def remove_unused_imports(self, code: str) -> Dict:
        """Remove imports that are never used in the module."""
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"success": False, "error": str(e)}

        used_names: set = set()
        def _handle_name(n): used_names.add(n.id)
        def _handle_attr(n):
            curr = n
            while isinstance(curr, ast.Attribute): curr = curr.value
            if isinstance(curr, ast.Name): used_names.add(curr.id)
            
        _IMPORT_USED_HANDLERS = {ast.Name: _handle_name, ast.Attribute: _handle_attr}
        for node in ast.walk(tree):
            h = _IMPORT_USED_HANDLERS.get(type(node))
            h(node) if h else None

        lines = code.splitlines()
        removed: List[str] = []
        keep: List[str] = []
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                # Parse this import line
                try:
                    imp_tree = ast.parse(stripped)
                    _IMPORT_TYPE_HANDLERS = {
                        ast.Import:     lambda n: [a.asname or a.name.split(".")[0] for a in n.names],
                        ast.ImportFrom: lambda n: [a.asname or a.name for a in n.names if a.name != "*"],
                    }
                    for node in ast.walk(imp_tree):
                        h = _IMPORT_TYPE_HANDLERS.get(type(node))
                        if h: names = h(node)
                    if any(n in used_names for n in names):
                        keep.append(line)
                    else:
                        removed.append(line.strip())
                except Exception:
                    keep.append(line)
            else:
                keep.append(line)

        new_code = "\n".join(keep)
        return {
            "success": True,
            "new_code": new_code,
            "removed_imports": removed,
            "diff": self._make_diff(code, new_code),
        }

    def explain_code(self, code: str, language: str = "python",
                     detail_level: str = "medium",
                     audience: str = "developer") -> Dict:
        """Produce a plain-English explanation of code behaviour."""
        prompt = (
            f"Explain this {language} code in detail level '{detail_level}' "
            f"for audience '{audience}'.\n"
            f"```{language}\n{code[:4000]}\n```\n"
            "Cover: purpose, algorithm, inputs/outputs, side effects, edge cases, "
            "and any non-obvious design decisions."
        )
        explanation = self.router.quick_request(prompt, task_type="coding")
        return {"success": True, "explanation": explanation, "language": language}

    # ─────────────────────────────────────────────────────────────────────────
    #  Format / Lint
    # ─────────────────────────────────────────────────────────────────────────

    def format_code(self, code: str, language: str = "python",
                    line_length: int = 100) -> Dict:
        """Format code using black (Python), prettier (JS), or LLM fallback."""
        # O(1) dict dispatch: language → formatter function (no elif)
        _FORMATTERS = {
            "python":     lambda: self._format_python(code, line_length),
            "javascript": lambda: self._format_js(code, "js"),
            "typescript": lambda: self._format_js(code, "ts"),
        }
        fmt = _FORMATTERS.get(language)
        return fmt() if fmt else {"success": False,
                                   "error": f"No formatter available for {language}"}

    def lint_code(self, code: str, language: str = "python",
                  ruleset: str = "default") -> Dict:
        """Run all available linters and consolidate results."""
        if language != "python":
            return {"success": False, "error": f"Linting only supported for Python"}
        issues = []
        if self._ruff_available:
            issues.extend(self._run_ruff(code, select="ALL" if ruleset == "strict" else None))
        else:
            ast_issues, _ = self._ast_analyze(code)
            issues.extend(ast_issues)
        return {
            "success": True,
            "issues": issues,
            "count": len(issues),
            "errors":   sum(1 for i in issues if i.get("severity") == "error"),
            "warnings": sum(1 for i in issues if i.get("severity") == "warning"),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Testing
    # ─────────────────────────────────────────────────────────────────────────

    def generate_tests(self, code: str, framework: str = "pytest",
                       language: str = "python",
                       coverage_target: int = 80) -> Dict:
        """Generate unit tests for given code, targeting a coverage level."""
        prompt = (
            f"Generate comprehensive {framework} tests for this {language} code.\n"
            f"```{language}\n{code[:4000]}\n```\n"
            f"Requirements:\n"
            f"  - Aim for >{coverage_target}% line coverage\n"
            "  - Test happy paths, edge cases, error conditions\n"
            "  - Use fixtures and parametrize where appropriate\n"
            "  - Mock external dependencies\n"
            "  - Include docstrings on test functions\n"
            "Return ONLY the test code in a fenced block."
        )
        resp  = self.router.quick_request(prompt, task_type="coding")
        tests = self._extract_code(resp, language)
        return {"success": True, "test_code": tests, "framework": framework}

    def run_tests(self, code: str, test_code: str = None,
                  language: str = "python",
                  framework: str = "pytest") -> Dict:
        """Execute tests and return results."""
        if language != "python":
            return {"success": False, "error": f"Test runner only supports Python"}

        if not test_code:
            gen = self.generate_tests(code, framework, language)
            test_code = gen.get("test_code", "")

        combined = f"{code}\n\n{test_code}\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            test_file = os.path.join(tmp_dir, "test_novamind.py")
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(combined)

            runner = shutil.which("pytest") or shutil.which("python")
            cmd    = ([runner, "-v", "--tb=short", test_file]
                      if "pytest" in (runner or "") else
                      [runner, "-m", "pytest", "-v", test_file])

            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120
                )
                output = proc.stdout + proc.stderr
                passed = len(re.findall(r" PASSED", output))
                failed = len(re.findall(r" FAILED", output))
                return {
                    "success": proc.returncode == 0,
                    "passed": passed,
                    "failed": failed,
                    "output": output[:self.MAX_OUTPUT],
                    "returncode": proc.returncode,
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Tests timed out after 120s"}
            except Exception as exc:
                return {"success": False, "error": f"Test runner error: {exc}"}

    def run_coverage(self, code: str, test_code: str = None) -> Dict:
        """Run pytest with coverage.py and return a coverage report."""
        cov = shutil.which("coverage")
        if not cov:
            return {"success": False, "error": "coverage.py not installed. pip install coverage"}

        if not test_code:
            gen      = self.generate_tests(code)
            test_code = gen.get("test_code", "")

        with tempfile.TemporaryDirectory() as tmp_dir:
            src_file  = os.path.join(tmp_dir, "module.py")
            test_file = os.path.join(tmp_dir, "test_module.py")
            with open(src_file, "w", encoding="utf-8") as f:
                f.write(code)
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(test_code)

            try:
                subprocess.run(
                    [cov, "run", "--source=module", test_file],
                    capture_output=True, cwd=tmp_dir, timeout=120,
                )
                proc = subprocess.run(
                    [cov, "report", "--show-missing"],
                    capture_output=True, text=True, cwd=tmp_dir, timeout=30,
                )
                report = proc.stdout
                pct_m  = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", report)
                return {
                    "success": True,
                    "coverage_percent": int(pct_m.group(1)) if pct_m else None,
                    "report": report,
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Coverage run timed out"}

    # ─────────────────────────────────────────────────────────────────────────
    #  Performance
    # ─────────────────────────────────────────────────────────────────────────

    def profile_code(self, code: str, runs: int = 3) -> Dict:
        """Profile Python code with cProfile and return hotspot report."""
        wrapper = (
            "import cProfile, pstats, io\n"
            "_pr = cProfile.Profile()\n"
            "_pr.enable()\n\n"
            f"{code}\n\n"
            "_pr.disable()\n"
            "_sio = io.StringIO()\n"
            "_ps = pstats.Stats(_pr, stream=_sio).sort_stats('cumulative')\n"
            "_ps.print_stats(20)\n"
            "print(_sio.getvalue())\n"
        )
        results = []
        for _ in range(runs):
            r = self.execute_python(wrapper, timeout=120, safe_mode=False)
            if r.get("success", False):
                results.append(r.get("stdout", ""))

        return {
            "success": bool(results),
            "runs": len(results),
            "profile_output": results[0] if results else "",
            "all_runs": results,
        }

    def benchmark_code(self, code: str, iterations: int = 1000,
                        setup: str = "") -> Dict:
        """Benchmark execution time using timeit."""
        bench_code = (
            f"import timeit\n"
            f"_setup = '''{setup}'''\n"
            f"_code  = '''{code}'''\n"
            f"_t = timeit.timeit(_code, setup=_setup, number={iterations})\n"
            f"print(f'Total: {{_t:.4f}}s | Per run: {{_t/{iterations}*1000:.4f}}ms | "
            f"Iterations: {iterations}')\n"
        )
        r = self.execute_python(bench_code, timeout=300, safe_mode=False)
        return {
            "success": r["success"],
            "output":  r.get("stdout", ""),
            "error":   r.get("stderr", ""),
            "iterations": iterations,
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Script / Module / Package Generation
    # ─────────────────────────────────────────────────────────────────────────

    def generate_script(self, task: str, language: str = "python",
                        save_path: str = None,
                        cli_args: List[str] = None) -> Dict:
        """Generate a runnable script with argparse CLI interface."""
        args_desc = ", ".join(cli_args) if cli_args else "no CLI arguments"
        constraints = [
            f"Include argparse for CLI with arguments: {args_desc}",
            "Print usage help with --help",
            "Exit with code 0 on success, 1 on error",
            "Include shebang line for Unix",
        ]
        result = self.write_code(task, language, constraints=constraints)
        if result["success"] and save_path:
            try:
                path = Path(save_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(result["code"], encoding="utf-8")
                if os.name != "nt":
                    path.chmod(path.stat().st_mode | 0o111)
                result["saved_to"] = str(path.resolve())
            except Exception as e:
                result["save_error"] = str(e)
        return result

    def create_module(self, name: str, description: str,
                      functions: List[str] = None,
                      save_dir: str = ".") -> Dict:
        """Create a complete Python module file with all listed functions."""
        func_list = "\n".join(f"  - {f}" for f in (functions or []))
        code_result = self.write_code(
            f"A Python module named '{name}' for: {description}\n"
            f"Must include these public functions:\n{func_list}",
            "python",
            constraints=["Module-level __all__", "__version__ = '1.0.0'",
                         "__author__ = 'NovaMind'"],
        )
        if not code_result["success"]:
            return code_result

        save_path = os.path.join(save_dir, f"{name}.py")
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(code_result["code"])
            return {
                "success": True,
                "module_path": save_path,
                "code": code_result["code"],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_package(self, name: str, description: str,
                       modules: List[str] = None,
                       save_dir: str = ".") -> Dict:
        """Create a full Python package directory with __init__.py and submodules."""
        pkg_dir = Path(save_dir) / name
        try:
            pkg_dir.mkdir(parents=True, exist_ok=True)

            init_result = self.write_code(
                f"__init__.py for package '{name}': {description}",
                "python",
                constraints=[
                    "__all__ = [...]  — list all public submodules",
                    "__version__ = '0.1.0'",
                    "Import key symbols from submodules",
                ],
            )
            (pkg_dir / "__init__.py").write_text(
                init_result.get("code", ""), encoding="utf-8"
            )

            created: List[str] = ["__init__.py"]
            for mod in (modules or []):
                mod_result = self.create_module(mod, f"Module {mod} in {name}", save_dir=str(pkg_dir))
                if mod_result["success"]:
                    created.append(f"{mod}.py")

            # setup.py
            setup_code = (
                f"from setuptools import setup, find_packages\n\n"
                f"setup(\n"
                f"    name='{name}',\n"
                f"    version='0.1.0',\n"
                f"    description='{description}',\n"
                f"    packages=find_packages(),\n"
                f"    python_requires='>=3.9',\n"
                f")\n"
            )
            (pkg_dir.parent / "setup.py").write_text(setup_code, encoding="utf-8")
            created.append("../setup.py")

            return {
                "success": True,
                "package_dir": str(pkg_dir),
                "files_created": created,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ─────────────────────────────────────────────────────────────────────────
    #  Git Operations
    # ─────────────────────────────────────────────────────────────────────────

    def _git(self, *args, cwd: str = None) -> Dict:
        if not self._git_available:
            return {"success": False, "error": "git not found"}
        try:
            proc = subprocess.run(
                ["git"] + list(args),
                capture_output=True, text=True, timeout=60,
                cwd=cwd or os.getcwd(),
            )
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def git_status(self, repo_path: str = None) -> Dict:
        r = self._git("status", "--porcelain", "-b", cwd=repo_path)
        if r["success"]:
            lines  = r["stdout"].splitlines()
            branch = lines[0].replace("## ", "") if lines else ""
            changes = [l for l in lines[1:] if l.strip()]
            r.update({"branch": branch, "changes": changes, "clean": len(changes) == 0})
        return r

    def git_diff(self, repo_path: str = None, staged: bool = False,
                 file_path: str = None) -> Dict:
        args = ["diff"]
        if staged:
            args.append("--cached")
        if file_path:
            args.extend(["--", file_path])
        return self._git(*args, cwd=repo_path)

    def git_log(self, repo_path: str = None, limit: int = 20,
                oneline: bool = True) -> Dict:
        args = ["log", f"-{limit}"]
        if oneline:
            args.append("--oneline")
        return self._git(*args, cwd=repo_path)

    def git_commit(self, message: str, repo_path: str = None,
                   add_all: bool = True) -> Dict:
        if add_all:
            add_r = self._git("add", "-A", cwd=repo_path)
            if not add_r["success"]:
                return add_r
        return self._git("commit", "-m", message, cwd=repo_path)

    def git_create_branch(self, branch_name: str, repo_path: str = None,
                           from_branch: str = None) -> Dict:
        args = ["checkout", "-b", branch_name]
        if from_branch:
            args.append(from_branch)
        return self._git(*args, cwd=repo_path)

    def git_stash(self, message: str = None, repo_path: str = None,
                  action: str = "push") -> Dict:
        # O(1) dict dispatch: action → base args
        _STASH_ARGS = {
            "push": ["stash", "push"],
            "pop":  ["stash", "pop"],
            "list": ["stash", "list"],
        }
        args = _STASH_ARGS.get(action)
        if args is None:
            return {"success": False, "error": f"Unknown stash action: {action}"}
        # Extend push args with optional message — branchless via list-multiply
        args = args + (["-m", message] * bool(action == "push" and message))
        return self._git(*args, cwd=repo_path)

    # ─────────────────────────────────────────────────────────────────────────
    #  Pip / Venv
    # ─────────────────────────────────────────────────────────────────────────

    def pip_install(self, packages: List[str], upgrade: bool = False,
                    quiet: bool = False, venv_path: str = None) -> Dict:
        pip = self._resolve_pip(venv_path)
        args = [pip, "install"] + packages
        if upgrade:
            args.append("--upgrade")
        if quiet:
            args.append("-q")
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=300)
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
                "packages": packages,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "pip install timed out"}

    def pip_list(self, outdated: bool = False,
                  format: str = "json", venv_path: str = None) -> Dict:
        pip  = self._resolve_pip(venv_path)
        args = [pip, "list"]
        if outdated:
            args.append("--outdated")
        args.extend(["--format", format])
        try:
            proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
            packages = json.loads(proc.stdout) if format == "json" and proc.stdout else []
            return {
                "success": proc.returncode == 0,
                "packages": packages,
                "count": len(packages),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def pip_check(self, venv_path: str = None) -> Dict:
        """Check for broken/conflicting packages."""
        pip = self._resolve_pip(venv_path)
        proc = subprocess.run([pip, "check"], capture_output=True, text=True, timeout=60)
        return {
            "success": proc.returncode == 0,
            "output": proc.stdout + proc.stderr,
            "conflicts_found": proc.returncode != 0,
        }

    def create_venv(self, venv_path: str, python_version: str = None) -> Dict:
        """Create a Python virtual environment."""
        python = sys.executable
        if python_version:
            for cmd in [f"python{python_version}", f"py -{python_version}", python_version]:
                found = shutil.which(cmd)
                if found:
                    python = found
                    break
        try:
            proc = subprocess.run(
                [python, "-m", "venv", venv_path],
                capture_output=True, text=True, timeout=120,
            )
            return {
                "success": proc.returncode == 0,
                "venv_path": venv_path,
                "python_used": python,
                "stderr": proc.stderr,
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    def generate_requirements(self, code: str = None,
                               directory: str = None) -> Dict:
        """Generate requirements.txt from imports in code or directory."""
        imports: set = set()

        if code:
            try:
                tree = ast.parse(code)
                _REQ_HANDLERS = {
                    ast.Import:     lambda n: [imports.add(a.name.split(".")[0]) for a in n.names],
                    ast.ImportFrom: lambda n: imports.add(n.module.split(".")[0]) if n.module else None,
                }
                for node in ast.walk(tree):
                    h = _REQ_HANDLERS.get(type(node))
                    h(node) if h else None
            except SyntaxError:
                pass

        if directory:
            for py_file in Path(directory).rglob("*.py"):
                try:
                    code_text = py_file.read_text(encoding="utf-8", errors="replace")
                    tree = ast.parse(code_text)
                    _REQ_HANDLERS = {
                        ast.Import:     lambda n: [imports.add(a.name.split(".")[0]) for a in n.names],
                        ast.ImportFrom: lambda n: imports.add(n.module.split(".")[0]) if n.module else None,
                    }
                    for node in ast.walk(tree):
                        h = _REQ_HANDLERS.get(type(node))
                        h(node) if h else None
                except Exception:
                    continue

        stdlib = set(sys.stdlib_module_names) if hasattr(sys, "stdlib_module_names") else set()
        third_party = sorted(imports - stdlib - {""})

        req_lines = "\n".join(third_party)
        return {
            "success": True,
            "requirements": third_party,
            "requirements_txt": req_lines,
            "count": len(third_party),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Diff / Patch / Search
    # ─────────────────────────────────────────────────────────────────────────

    def diff_code(self, code_a: str, code_b: str,
                  label_a: str = "original", label_b: str = "modified",
                  context_lines: int = 3) -> Dict:
        """Generate a unified diff between two code strings."""
        diff = self._make_diff(code_a, code_b, label_a, label_b, context_lines)
        added   = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
        return {
            "success": True,
            "diff": diff,
            "added_lines": added,
            "removed_lines": removed,
            "unchanged": len(code_a.splitlines()) - removed,
        }

    def apply_patch(self, code: str, patch: str) -> Dict:
        """Apply a unified diff patch to source code using Python difflib."""
        try:
            with tempfile.TemporaryDirectory() as tmp_dir:
                src_file   = os.path.join(tmp_dir, "source.py")
                patch_file = os.path.join(tmp_dir, "changes.patch")
                out_file   = os.path.join(tmp_dir, "patched.py")

                with open(src_file,   "w", encoding="utf-8") as f: f.write(code)
                with open(patch_file, "w", encoding="utf-8") as f: f.write(patch)

                patch_cmd = shutil.which("patch")
                if patch_cmd:
                    proc = subprocess.run(
                        [patch_cmd, "-o", out_file, src_file, patch_file],
                        capture_output=True, text=True, timeout=30,
                    )
                    if proc.returncode == 0:
                        patched = Path(out_file).read_text(encoding="utf-8")
                        return {"success": True, "patched_code": patched}
                    return {"success": False, "error": proc.stderr}

                return {"success": False, "error": "patch command not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def search_code(self, pattern: str, directory: str = ".",
                    file_pattern: str = "*.py",
                    regex: bool = False,
                    context_lines: int = 2) -> Dict:
        """Search for pattern in code files under directory."""
        results: List[Dict] = []
        flags = re.IGNORECASE
        if not regex:
            pattern = re.escape(pattern)
        try:
            compiled = re.compile(pattern, flags)
        except re.error as e:
            return {"success": False, "error": f"Regex error: {e}"}

        for path in Path(directory).rglob(file_pattern):
            try:
                lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for i, line in enumerate(lines):
                if compiled.search(line):
                    start = max(0, i - context_lines)
                    end   = min(len(lines), i + context_lines + 1)
                    results.append({
                        "file": str(path),
                        "line": i + 1,
                        "match": line.rstrip(),
                        "context": lines[start:end],
                    })

        return {
            "success": True,
            "matches": results[:500],
            "total": len(results),
        }

    def find_usages(self, symbol: str, code: str = None,
                    directory: str = None) -> Dict:
        """Find all usages of a symbol in code or directory."""
        results: List[Dict] = []
        pattern = r"\b" + re.escape(symbol) + r"\b"

        if code:
            for i, line in enumerate(code.splitlines(), 1):
                if re.search(pattern, line):
                    results.append({"source": "<code>", "line": i, "text": line.strip()})

        if directory:
            search_r = self.search_code(pattern, directory, regex=True)
            results.extend(search_r.get("matches", []))

        return {
            "success": True,
            "symbol": symbol,
            "usages": results,
            "count": len(results),
        }

    # ─────────────────────────────────────────────────────────────────────────
    #  Safety / AST Internals
    # ─────────────────────────────────────────────────────────────────────────

    def _check_code_safety(self, code: str) -> Dict:
        violations: List[str] = []
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return {"safe": False, "reason": f"Syntax error: {e}", "violations": [str(e)]}

        def _check_call(n):
            if isinstance(n.func, ast.Name) and n.func.id in self.BLOCKED_CALLS:
                violations.append(f"Blocked call: {n.func.id}")
        
        def _check_import(n):
            for alias in n.names:
                mod = alias.name.split(".")[0]
                status = "Blocked" if mod in self.BLOCKED_MODULES else "High-risk" if mod in self.HIGH_RISK_MODULES else None
                if status: violations.append(f"{status} import: {alias.name}")

        def _check_import_from(n):
            if n.module:
                mod = n.module.split(".")[0]
                status = "Blocked" if mod in self.BLOCKED_MODULES else "High-risk" if mod in self.HIGH_RISK_MODULES else None
                if status: violations.append(f"{status} import: {n.module}")

        _SAFETY_HANDLERS = {
            ast.Call:       _check_call,
            ast.Import:     _check_import,
            ast.ImportFrom: _check_import_from,
        }
        for node in ast.walk(tree):
            h = _SAFETY_HANDLERS.get(type(node))
            h(node) if h else None

        return {
            "safe": len(violations) == 0,
            "reason": "; ".join(violations) if violations else "OK",
            "violations": violations,
        }

    def _ast_analyze(self, code: str) -> Tuple[List[Dict], Dict]:
        """Return (issues, metrics) from AST walk."""
        issues:  List[Dict] = []
        metrics: Dict       = {}

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            issues.append({"severity": "error", "line": e.lineno or 0,
                           "column": e.offset or 0, "message": str(e),
                           "source": "ast"})
            return issues, metrics

        lines   = code.splitlines()
        blank   = sum(1 for l in lines if not l.strip())
        comment = sum(1 for l in lines if l.strip().startswith("#"))

        comp_v = ComplexityVisitor(); comp_v.visit(tree)
        dep_v  = MaxDepthVisitor();   dep_v.visit(tree)
        dup_n  = self._dup_detector.count_duplicates(code)

        funcs   = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]

        loc    = len(lines) - blank - comment
        mi_raw = max(0, (171 - 5.2 * (comp_v.cyclomatic ** 0.5) - 0.23 * loc
                         - 16.2 * (len(lines) ** 0.5)) * 100 / 171)

        metrics = {
            "lines_total":          len(lines),
            "lines_code":           loc,
            "lines_blank":          blank,
            "lines_comment":        comment,
            "functions":            len(funcs),
            "classes":              len(classes),
            "imports":              len(imports),
            "cyclomatic_complexity": comp_v.cyclomatic,
            "cognitive_complexity":  comp_v.cognitive,
            "max_depth":             dep_v.max_depth,
            "duplicated_blocks":     dup_n,
            "maintainability_index": round(mi_raw, 1),
        }

        # Pattern-based issues
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                issues.append({
                    "severity": "warning", "line": node.lineno, "column": 0,
                    "message": "Bare except clause — be specific",
                    "source": "ast",
                })
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "print":
                    issues.append({
                        "severity": "info", "line": node.lineno, "column": 0,
                        "message": "Use logging instead of print for production code",
                        "source": "ast",
                    })
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    issues.append({
                        "severity": "info", "line": node.lineno, "column": 0,
                        "message": f"Function '{node.name}' lacks a docstring",
                        "source": "ast",
                    })

        if comp_v.cyclomatic > 10:
            issues.append({
                "severity": "warning", "line": 0, "column": 0,
                "message": f"Cyclomatic complexity {comp_v.cyclomatic} > 10 — consider splitting",
                "source": "ast",
            })

        return issues, metrics

    def _run_ruff(self, code: str, select: str = None) -> List[Dict]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                          delete=False, encoding="utf-8") as f:
            f.write(code); tmp = f.name
        try:
            args = ["ruff", "check", "--output-format=json", tmp]
            if select:
                args.extend(["--select", select])
            proc = subprocess.run(args, capture_output=True, text=True, timeout=30)
            try:
                data = json.loads(proc.stdout or "[]")
                return [{
                    "severity": "error" if d["severity"] == "error" else "warning",
                    "line":     d["location"]["row"],
                    "column":   d["location"]["column"],
                    "message":  d["message"],
                    "code":     d["code"],
                    "source":   "ruff",
                } for d in data]
            except json.JSONDecodeError:
                return []
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _run_mypy(self, code: str, strict: bool = False) -> List[Dict]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                          delete=False, encoding="utf-8") as f:
            f.write(code); tmp = f.name
        try:
            args = ["mypy", "--no-error-summary", "--no-pretty", tmp]
            if strict:
                args.append("--strict")
            proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
            issues = []
            for line in (proc.stdout + proc.stderr).splitlines():
                m = re.match(r".+:(\d+):\s*(error|warning|note):\s*(.+)", line)
                if m:
                    issues.append({
                        "severity": m.group(2) if m.group(2) != "note" else "info",
                        "line":     int(m.group(1)),
                        "column":   0,
                        "message":  m.group(3),
                        "source":   "mypy",
                    })
            return issues
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _run_bandit(self, code: str, severity: str = "MEDIUM") -> List[Dict]:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                          delete=False, encoding="utf-8") as f:
            f.write(code); tmp = f.name
        try:
            proc = subprocess.run(
                ["bandit", "-f", "json", "-l", "-q", tmp],
                capture_output=True, text=True, timeout=30,
            )
            try:
                data = json.loads(proc.stdout or "{}")
                return [{
                    "severity":    r["issue_severity"],
                    "line":        r["line_number"],
                    "column":      0,
                    "message":     r["issue_text"],
                    "code":        r["test_id"],
                    "confidence":  r["issue_confidence"],
                    "source":      "bandit",
                } for r in data.get("results", [])]
            except json.JSONDecodeError:
                return []
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    #  Python-specific validation / static analysis
    # ─────────────────────────────────────────────────────────────────────────

    def _python_validate_result(self, code: str, result: dict) -> dict:
        """Validate Python code syntax via AST. Zero if/elif/else."""
        VALIDATORS: Dict[str, Callable] = {
            "syntax": lambda c: ast.parse(c),
        }

        outcomes: Dict[str, Any] = {}
        for name, validator in VALIDATORS.items():
            try:
                validator(code)
                outcomes[name] = True
            except SyntaxError as e:
                outcomes[name] = str(e)

        RESULT_MAP: Dict[bool, Dict] = {
            True:  {"syntax_valid": True},
            False: {"syntax_valid": False,
                    "syntax_error": outcomes["syntax"],
                    "success": False},
        }

        result.update(RESULT_MAP[outcomes["syntax"] is True])
        return result

    def _python_run_static_analysis(self, code: str, result: dict) -> None:
        """Run bandit + py_compile on code. Populates result['static_analysis']."""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py",
            delete=False, encoding="utf-8"
        ) as f:
            f.write(code)
            tmp_path = f.name

        ANALYSERS: Dict[str, list] = {
            "bandit": ["bandit", "-q", "-f", "json", tmp_path],
            "syntax": [sys.executable, "-m", "py_compile", tmp_path],
        }

        analysis_results: Dict[str, Any] = {}

        def _parse_bandit(r) -> Any:
            try:
                return json.loads(r.stdout or "{}").get("results", [])
            except (json.JSONDecodeError, AttributeError):
                return []

        def _parse_syntax(r) -> Any:
            return [] if r.returncode == 0 else [r.stderr]

        PARSE_OUTPUT: Dict[str, Callable] = {
            "bandit": _parse_bandit,
            "syntax": _parse_syntax,
        }

        for tool, cmd in ANALYSERS.items():
            try:
                r = subprocess.run(
                    cmd, capture_output=True,
                    text=True, timeout=15
                )
                analysis_results[tool] = PARSE_OUTPUT[tool](r)
            except FileNotFoundError:
                analysis_results[tool] = f"{tool}_not_installed"
            except subprocess.TimeoutExpired:
                analysis_results[tool] = f"{tool}_timed_out"
            except Exception as e:
                analysis_results[tool] = str(e)

        # Cleanup temp file after all analysers have finished
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

        result["static_analysis"] = analysis_results

    # ─────────────────────────────────────────────────────────────────────────

    def _resolve_pip(self, venv_path: str = None) -> str:
        if venv_path:
            candidates = [
                os.path.join(venv_path, "Scripts", "pip.exe"),
                os.path.join(venv_path, "bin", "pip"),
                os.path.join(venv_path, "Scripts", "pip"),
            ]
            for c in candidates:
                if os.path.isfile(c):
                    return c
        return shutil.which("pip") or shutil.which("pip3") or f"{sys.executable} -m pip"

    def _extract_code(self, text: str, language: str = "python") -> str:
        for pattern in [
            rf"```{language}\s*(.*?)```",
            rf"```\w*\s*(.*?)```",
        ]:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                return m.group(1).strip()
        return text.strip()

    def _make_diff(self, a: str, b: str,
                   label_a: str = "original", label_b: str = "modified",
                   context: int = 3) -> str:
        return "".join(difflib.unified_diff(
            a.splitlines(keepends=True),
            b.splitlines(keepends=True),
            fromfile=label_a, tofile=label_b,
            n=context,
        ))

    def _history_action(self, limit: int = 50) -> Dict:
        recent = self.execution_history[-limit:]
        return {
            "success": True,
            "count": len(recent),
            "history": [
                {
                    "ts":       r.timestamp,
                    "success":  r.success,
                    "time_s":   r.execution_time,
                    "returncode": r.returncode,
                }
                for r in recent
            ],
        }

    def get_history(self) -> List[Dict]:
        return [
            {"ts": r.timestamp, "success": r.success, "time_s": r.execution_time}
            for r in self.execution_history[-50:]
        ]
