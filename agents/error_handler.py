"""
Error Handler — LLM-assisted error analysis and fix suggestion.
Pattern matching, solution caching, recovery plan generation.
classify_error uses dict dispatch + frozenset membership — no if-elif chain.
"""
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from core.orchestration.llm_router import get_router

logger = logging.getLogger("ErrorHandler")


# ─────────────────────────────────────────────────────────────────────────────
#  O(1) classification tables  — replaces the if/elif chain
# ─────────────────────────────────────────────────────────────────────────────

SEVERITY_SETS: List[Tuple[str, frozenset]] = [
    ("critical", frozenset({"fatal", "crash", "corrupt", "segmentation",
                             "kernel panic", "blue screen"})),
    ("high",     frozenset({"permission", "access denied", "connection refused",
                             "unauthorized", "forbidden"})),
    ("medium",   frozenset({"timeout", "not found", "unavailable", "bad request",
                             "invalid", "failed"})),
    ("low",      frozenset({"warning", "deprecated", "retry"})),
]

CATEGORY_SETS: Dict[str, frozenset] = {
    "filesystem":  frozenset({"file", "path", "directory", "not found",
                               "filenotfound", "no such file"}),
    "network":     frozenset({"network", "connection", "timeout", "dns",
                               "socket", "refused", "err_"}),
    "permission":  frozenset({"permission", "access", "denied",
                               "unauthorized", "forbidden"}),
    "memory":      frozenset({"memory", "alloc", "oom", "heap", "stack"}),
    "dependency":  frozenset({"module", "import", "package",
                               "modulenotfound", "no module named"}),
    "syntax":      frozenset({"syntaxerror", "unexpected token",
                               "indentationerror", "parse error"}),
    "type":        frozenset({"typeerror", "valueerror", "attributeerror",
                               "keyerror", "indexerror"}),
    "ui":          frozenset({"element", "click", "stale", "selector",
                               "playwright", "selenium"}),
}

PATTERN_SOLUTIONS = {
    r"No module named '([^']+)'": lambda m: {
        "action": f"pip install {m.group(1)}",
        "description": f"Install missing module: {m.group(1)}",
        "auto_fixable": True, "confidence": 0.95,
    },
    r"ImportError:.*'([^']+)'": lambda m: {
        "action": f"pip install {m.group(1)}",
        "description": f"Install missing package: {m.group(1)}",
        "auto_fixable": True, "confidence": 0.9,
    },
    r"PermissionError|Access is denied": lambda _: {
        "action": "run_as_admin",
        "description": "Execute with elevated permissions",
        "auto_fixable": False, "confidence": 0.85,
    },
    r"FileNotFoundError|The system cannot find": lambda _: {
        "action": "verify_path",
        "description": "Check if file/path exists",
        "auto_fixable": False, "confidence": 0.85,
    },
    r"ConnectionError|ConnectionRefused": lambda _: {
        "action": "check_network",
        "description": "Verify network connectivity and service availability",
        "auto_fixable": False, "confidence": 0.8,
    },
    r"TimeoutError|Timeout.*loading": lambda _: {
        "action": "increase_timeout",
        "description": "Increase timeout — service may be slow",
        "auto_fixable": True, "confidence": 0.75,
    },
    r"element.*not found|stale element": lambda _: {
        "action": "retry_with_explicit_wait",
        "description": "Wait for element, then retry with explicit wait",
        "auto_fixable": True, "confidence": 0.8,
    },
    r"net::ERR_": lambda _: {
        "action": "check_url",
        "description": "Verify URL is correct and reachable",
        "auto_fixable": False, "confidence": 0.85,
    },
}


class ErrorHandler:
    """
    LLM-assisted error analyst and fix suggester.
    Supports other agents recovering from failures.
    All classification uses O(1) frozenset lookup — no if-elif chains.
    """

    def __init__(self):
        self.router = get_router()
        self.error_history: List[Dict] = []
        self.solution_cache: Dict[str, Dict] = {}

    def execute(self, action: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        ACTION_TABLE = {
            "analyze_error":           self.analyze_error,
            "suggest_fix":             self.suggest_fix,
            "search_solutions":        self.search_solutions,
            "classify_error":          self.classify_error,
            "generate_recovery_plan":  self.generate_recovery_plan,
        }
        handler = ACTION_TABLE.get(action)
        if not handler:
            return {"success": False, "error": f"Unknown action: {action}"}
        try:
            return handler(**parameters)
        except Exception as exc:
            logger.error(f"ErrorHandler failed: {exc}")
            return {"success": False, "error": str(exc)}

    def analyze_error(self, error_message: str, context: str = "",
                      task_description: str = "") -> Dict:
        pattern_analysis = _match_error_patterns(error_message)

        prompt = f"""Analyze this error and provide diagnosis:

Error: {error_message}
Task: {task_description}
Context: {context}
Pattern matches: {json.dumps(pattern_analysis)}

Respond in JSON:
{{
    "error_type": "classification",
    "severity": "critical|high|medium|low",
    "root_cause": "detailed explanation",
    "probable_causes": ["cause1", "cause2"],
    "suggested_actions": ["action1", "action2"],
    "prevention_tips": ["tip1"],
    "recoverable": true/false,
    "auto_fix_possible": true/false
}}"""

        result = self.router.quick_request(prompt, task_type="coding")
        analysis = _extract_json_safe(result)

        if pattern_analysis:
            analysis["pattern_match"] = pattern_analysis
            if not analysis.get("suggested_actions"):
                analysis["suggested_actions"] = [pattern_analysis.get("action", "")]

        self._log_error(error_message, task_description, analysis)

        return {
            "success": True,
            "error_message": error_message,
            "analysis": analysis,
            "recoverable": analysis.get("recoverable", True),
            "auto_fix_possible": analysis.get("auto_fix_possible", False),
        }

    def suggest_fix(self, error_message: str, code: str = None,
                    language: str = "python",
                    previous_attempts: List[str] = None) -> Dict:
        attempts_str = "\n".join(f"- {a}" for a in (previous_attempts or []))
        code_section = f"\nCode:\n```{language}\n{code}\n```" if code else ""

        prompt = f"""Fix this error:

Error: {error_message}
Language: {language}
{code_section}

Previous attempts (don't repeat):
{attempts_str}

Provide ONLY the fixed code or specific fix instructions. Be concise."""

        fix = self.router.quick_request(prompt, task_type="coding")
        fixed_code = _extract_code_safe(fix, language)

        return {
            "success": True,
            "original_error": error_message,
            "suggested_fix": fixed_code or fix,
            "language": language,
            "is_code_fix": fixed_code is not None,
        }

    def search_solutions(self, error_message: str,
                         memory_system=None) -> Dict:
        solutions = []

        if memory_system:
            try:
                similar = memory_system.find_similar_experiences(
                    error_message, limit=5
                )
                for exp in similar:
                    if not exp.get("success", True):
                        solutions.append({
                            "source": "memory",
                            "error": exp.get("task", ""),
                            "solution": exp.get("recovery_action", "No solution recorded"),
                            "confidence": 0.8,
                        })
            except Exception as exc:
                logger.warning(f"Memory search: {exc}")

        key = _normalize_error(error_message)
        if key in self.solution_cache:
            solutions.append({"source": "cache", **self.solution_cache[key],
                               "confidence": 0.9})

        solutions.extend(_get_pattern_solutions(error_message))
        solutions.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return {
            "success": True,
            "solutions_found": len(solutions),
            "solutions": solutions[:5],
        }

    def classify_error(self, error_message: str) -> Dict:
        """
        O(1) severity via priority-ordered frozenset scan.
        O(categories) category multi-assignment via frozenset membership.
        Zero if-elif in the dispatch path.
        """
        em = error_message.lower()

        severity = "medium"
        for sev, kws in SEVERITY_SETS:
            if any(k in em for k in kws):
                severity = sev
                break

        categories = [
            cat for cat, kws in CATEGORY_SETS.items()
            if any(k in em for k in kws)
        ] or ["general"]

        return {
            "success":       True,
            "severity":      severity,
            "categories":    categories,
            "recoverable":   severity != "critical",
            "needs_attention": severity in ("critical", "high"),
        }

    def generate_recovery_plan(self, error_message: str,
                                current_step: Dict,
                                available_agents: List[str]) -> Dict:
        analysis       = self.analyze_error(
            error_message,
            task_description=current_step.get("description", ""),
        )
        classification = self.classify_error(error_message)

        strategies = []
        if classification["recoverable"]:
            strategies = [
                {"priority": 1, "action": "retry",
                 "description": "Retry with increased timeout"},
                {"priority": 2, "action": "fallback_agent",
                 "description": f"Try: {', '.join(available_agents[:3])}"},
            ]
            if analysis.get("auto_fix_possible"):
                strategies.append({
                    "priority": 3, "action": "auto_fix",
                    "description": "Apply automatic fix from pattern",
                })
            strategies.append({
                "priority": 4, "action": "manual_intervention",
                "description": "Request user assistance",
            })

        return {
            "success": True,
            "recovery_plan": {
                "error_analysis":      analysis,
                "classification":      classification,
                "recovery_strategies": strategies,
                "recommended_strategy": strategies[0] if strategies else None,
                "estimated_recovery_time":
                    "1-5 minutes" if classification["recoverable"] else "unknown",
            },
            "recoverable": classification["recoverable"],
        }

    def cache_solution(self, error_key: str, solution: Dict) -> None:
        self.solution_cache[error_key] = {
            **solution,
            "cached_at": datetime.now().isoformat(),
        }

    def get_error_stats(self) -> Dict:
        if not self.error_history:
            return {"total_errors": 0}
        recent = self.error_history[-100:]
        severities: Dict[str, int] = {}
        categories_cnt: Dict[str, int] = {}
        for entry in recent:
            analysis = entry.get("analysis", {})
            sev = analysis.get("severity", "unknown")
            severities[sev] = severities.get(sev, 0) + 1
            for cat in analysis.get("categories", ["unknown"]):
                categories_cnt[cat] = categories_cnt.get(cat, 0) + 1
        return {
            "total_errors":          len(self.error_history),
            "recent_errors":         len(recent),
            "severity_distribution": severities,
            "category_distribution": categories_cnt,
            "solutions_cached":      len(self.solution_cache),
        }

    def _log_error(self, error: str, task: str, analysis: Dict) -> None:
        self.error_history.append({
            "timestamp": datetime.now().isoformat(),
            "error":     error[:500],
            "task":      task,
            "analysis":  analysis,
        })
        if len(self.error_history) > 500:
            self.error_history = self.error_history[-500:]


# ─────────────────────────────────────────────────────────────────────────────
#  Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _match_error_patterns(error_message: str) -> Optional[Dict]:
    for pattern, builder in PATTERN_SOLUTIONS.items():
        m = re.search(pattern, error_message, re.IGNORECASE)
        if m:
            result = builder(m)
            result["matched_pattern"] = pattern
            return result
    return None


def _get_pattern_solutions(error_message: str) -> List[Dict]:
    solutions = []
    for pattern, builder in PATTERN_SOLUTIONS.items():
        m = re.search(pattern, error_message, re.IGNORECASE)
        if m:
            solutions.append(builder(m))
    return solutions


def _normalize_error(error_message: str) -> str:
    n = re.sub(r'File "[^"]+"', 'File "..."', error_message)
    n = re.sub(r'line \d+', 'line N', n)
    n = re.sub(r'\d{4}-\d{2}-\d{2}[\sT]\d{2}:\d{2}:\d{2}', '', n)
    return n[:200]


def _extract_json_safe(text: str) -> Dict:
    try:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as e:
        import logging; logging.getLogger(__name__).debug(f"Exception caught: {e}")
        pass
    return {
        "error_type": "unknown",
        "severity": "medium",
        "root_cause": text[:500],
        "recoverable": True,
        "auto_fix_possible": False,
    }


def _extract_code_safe(text: str, language: str) -> Optional[str]:
    for pattern in (f'```{language}\\s*(.*?)```', r'```\\s*(.*?)```'):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            return m.group(1).strip()
    return None