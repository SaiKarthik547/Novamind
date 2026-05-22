"""
Task Parser - Natural Language Understanding
Converts user commands into structured, executable task plans.
O(1) task-type detection via inverted word→type dict (no if-elif chains).
O(1) risk assessment via priority-ordered frozenset membership.
"""
import json
import re
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from core.orchestration.llm_router import get_router

logger = logging.getLogger("TaskParser")


class TaskType(Enum):
    FILE_OPERATION      = "file_operation"
    SYSTEM_COMMAND      = "system_command"
    BROWSER_ACTION      = "browser_action"
    CODE_EXECUTION      = "code_execution"
    APPLICATION_CONTROL = "application_control"
    VISION_ANALYSIS     = "vision_analysis"
    MULTI_STEP          = "multi_step"
    INFORMATION         = "information"
    DRAWING             = "drawing"
    TEXT_INPUT          = "text_input"
    UNKNOWN             = "unknown"


class RiskLevel(Enum):
    SAFE     = "safe"
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


@dataclass
class TaskStep:
    step_number:           int
    description:           str
    agent:                 str
    action:                str
    parameters:            Dict[str, Any] = field(default_factory=dict)
    verification_method:   str = ""
    rollback_action:       str = ""
    requires_confirmation: bool = False
    risk_level:            RiskLevel = RiskLevel.SAFE
    depends_on:            List[int] = field(default_factory=list)


@dataclass
class TaskPlan:
    original_request:      str
    task_type:             TaskType
    summary:               str
    steps:                 List[TaskStep]
    estimated_duration:    str = "unknown"
    requires_user_confirm: bool = False
    risk_assessment:       RiskLevel = RiskLevel.SAFE
    context_needed:        List[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
#  O(1) word→TaskType inverted index (built once at module load)
# ─────────────────────────────────────────────────────────────────────────────

_TASK_TYPE_KEYWORDS: Dict[TaskType, List[str]] = {
    TaskType.FILE_OPERATION:      ["file", "folder", "directory", "read",
                                   "write", "copy", "move", "delete"],
    TaskType.SYSTEM_COMMAND:      ["command", "cmd", "powershell", "terminal",
                                   "execute", "run"],
    TaskType.BROWSER_ACTION:      ["browser", "web", "website", "search",
                                   "url", "internet"],
    TaskType.CODE_EXECUTION:      ["code", "python", "script", "program", "debug"],
    TaskType.APPLICATION_CONTROL: ["click", "type", "open", "close", "launch", "app"],
    TaskType.VISION_ANALYSIS:     ["look", "see", "find", "screen", "locate"],
    TaskType.DRAWING:             ["draw", "paint", "sketch", "diagram"],
}

WORD_TO_TASK_TYPE: Dict[str, TaskType] = {
    word: task_type
    for task_type, words in _TASK_TYPE_KEYWORDS.items()
    for word in words
}

# ─────────────────────────────────────────────────────────────────────────────
#  O(1) risk assessment via priority-ordered frozensets
# ─────────────────────────────────────────────────────────────────────────────

_RISK_KEYWORD_SETS: List[tuple] = [
    (RiskLevel.CRITICAL, frozenset([
        "delete", "remove", "format", "wipe", "clean", "destroy",
        "registry", "system32", "chmod", "rm -rf", "del /f", "format c:",
    ])),
    (RiskLevel.HIGH, frozenset([
        "overwrite", "replace", "modify", "change permission",
        "chmod", "grant admin", "disable firewall", "kill process",
    ])),
    (RiskLevel.MEDIUM, frozenset([
        "install", "execute", "run script", "move system", "copy system",
    ])),
    (RiskLevel.LOW, frozenset(["create", "rename", "copy", "list", "view", "read"])),
]


def _assess_risk_fast(request: str) -> RiskLevel:
    rl = request.lower()
    for level, kws in _RISK_KEYWORD_SETS:
        if any(k in rl for k in kws):
            return level
    return RiskLevel.SAFE


# ─────────────────────────────────────────────────────────────────────────────
#  O(1) agent name lookup
# ─────────────────────────────────────────────────────────────────────────────

AGENT_MAPPING: Dict[str, str] = {
    "file": "file_agent", "files": "file_agent", "folder": "file_agent",
    "directory": "file_agent", "read": "file_agent", "write": "file_agent",
    "copy": "file_agent", "move": "file_agent", "delete": "file_agent",
    "organize": "file_agent", "backup": "file_agent",
    "command": "system_agent", "cmd": "system_agent",
    "powershell": "system_agent", "terminal": "system_agent",
    "execute": "system_agent", "run": "system_agent",
    "install": "system_agent", "system": "system_agent",
    "process": "system_agent", "cpu": "system_agent",
    "memory": "system_agent", "disk": "system_agent",
    "stats": "system_agent", "resources": "system_agent",
    "browser": "browser_agent", "web": "browser_agent",
    "website": "browser_agent", "url": "browser_agent",
    "search": "browser_agent", "internet": "browser_agent",
    "online": "browser_agent", "download": "browser_agent",
    "google": "browser_agent", "bing": "browser_agent",
    "code": "code_agent", "python": "code_agent", "script": "code_agent",
    "program": "code_agent", "debug": "code_agent", "fix": "code_agent",
    "develop": "code_agent", "javascript": "code_agent",
    "app": "application_agent", "application": "application_agent",
    "window": "application_agent", "click": "application_agent",
    "type": "application_agent", "press": "application_agent",
    "open": "application_agent", "close": "application_agent",
    "launch": "application_agent", "paint": "application_agent",
    "notepad": "application_agent", "draw": "application_agent",
    "sketch": "application_agent", "diagram": "application_agent",
    "art": "application_agent", "image": "application_agent",
    "picture": "application_agent",
    "look": "vision_agent", "see": "vision_agent",
    "screen": "vision_agent", "find": "vision_agent",
    "locate": "vision_agent", "identify": "vision_agent",
    "analyze": "vision_agent",
}

DRAWING_KEYWORDS: frozenset = frozenset([
    "draw", "paint", "sketch", "create", "make", "generate",
    "illustrate", "depict", "render", "design",
])
DRAWING_APP_KEYWORDS: frozenset = frozenset([
    "ms paint", "mspaint", "paint", "paintbrush",
])

KNOWN_APP_NAMES: List[str] = [
    "word", "excel", "powerpoint", "outlook", "onenote", "access", "visio",
    "chrome", "google chrome", "firefox", "edge", "microsoft edge", "opera", "brave",
    "notepad", "wordpad", "calculator", "calc",
    "file explorer", "explorer",
    "vlc", "spotify", "media player",
    "vs code", "vscode", "visual studio code", "visual studio",
    "teams", "microsoft teams", "slack", "discord", "zoom", "skype",
    "steam", "obs", "obs studio",
    "cmd", "command prompt", "powershell", "terminal",
    "snipping tool", "snip",
]

_DEPENDENCY_NORMALIZERS = {
    list: lambda value: value,
    tuple: lambda value: list(value),
    set: lambda value: list(value),
}


class TaskParser:
    """
    Intelligent task parser. LLM as primary NLU, rule-based fallback.
    All keyword routing uses O(1) dict/frozenset lookups — no if-elif chains.
    """

    def __init__(self):
        self.router = get_router()
        self._system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return """You are NovaMind's Task Parser. Convert user requests into structured JSON task plans.

AGENTS AVAILABLE:
- file_agent       — read/write/copy/move/delete/search/organize files
- system_agent     — run commands, monitor CPU/RAM/disk, manage processes
- browser_agent    — open URLs, search web, extract content, fill forms
- code_agent       — write/execute/fix/analyze Python and JavaScript
- application_agent — control desktop apps, click/type/draw in MS Paint
- vision_agent     — describe screen, find UI elements, OCR text

RESPOND ONLY WITH VALID JSON:
{
  "task_type": "file_operation|system_command|browser_action|code_execution|application_control|drawing|vision_analysis|multi_step|information",
  "summary": "one-sentence description",
  "estimated_duration": "short|medium|long",
  "risk_assessment": "safe|low|medium|high|critical",
  "requires_user_confirm": false,
  "context_needed": [],
  "steps": [
    {
      "step_number": 1,
      "description": "What this step does",
      "agent": "agent_name",
      "action": "action_name",
      "parameters": {"key": "value"},
      "verification_method": "how to confirm success",
      "requires_confirmation": false,
      "risk_level": "safe",
      "depends_on": []
    }
  ]
}

DEPENDENCY RULES:
- Use "depends_on": [step_numbers] to specify which steps MUST complete before this one starts.
- If a step is independent, use "depends_on": [].
- If steps must run sequentially, step 2 depends on [1], step 3 on [2], etc.
- If steps can run in parallel (e.g. searching 3 different websites), they all have "depends_on": [].

DRAWING RULES — when the user wants to draw something in MS Paint:
  Use ONE step with agent="application_agent", action="execute_paint_task"
  parameters must include:
    - subject: what to draw (e.g. "blue sports car")
    - color: the main color name (e.g. "blue")
    - save_path: null (or a file path if user specified one)
  Example:
    {"step_number":1,"description":"Draw a blue sports car in MS Paint",
     "agent":"application_agent","action":"execute_paint_task",
     "parameters":{"subject":"realistic blue sports car","color":"blue","save_path":null},
     "verification_method":"Verify MS Paint is open and drawing is visible",
     "risk_level":"safe"}

APPLICATION TASK RULES — when the user wants to do ANY task in a desktop app:
  Use ONE step with agent="application_agent", action="do_task_in_app"
  parameters must include:
    - app_name: the exact app name string
    - task_description: full natural language description
    - max_steps: 10 for simple, 15 for medium, 20 for complex

GENERAL RULES:
1. Each step must have a clear verification_method.
2. Mark destructive operations as requires_confirmation=true.
3. For multi-step tasks ensure sequential order is correct.
4. Never add fake or placeholder steps.
"""

    def parse(self, user_request: str, context: Dict = None) -> TaskPlan:
        context = context or {}

        if self._is_drawing_request(user_request):
            return self._build_drawing_plan(user_request)

        app_task = self._detect_app_task(user_request)
        if app_task:
            return self._build_app_task_plan(user_request, app_task)

        context_str = ""
        if context.get("screen_description"):
            context_str += f"\nScreen: {context['screen_description'][:300]}\n"
        if context.get("active_window"):
            context_str += f"Active window: {context['active_window']}\n"
        if context.get("past_experiences"):
            exps = context["past_experiences"][:2]
            context_str += f"Relevant past: {json.dumps(exps, default=str)[:400]}\n"

        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user",   "content": f"{context_str}\nUser request: {user_request}"},
        ]

        result = self.router.send_message(
            messages=messages,
            task_type="general",
            temperature=0.2,
            max_tokens=3000,
        )

        if result["success"] and result.get("content"):
            try:
                parsed = self._extract_json(result["content"])
                return self._create_task_plan(user_request, parsed)
            except Exception as exc:
                logger.warning(f"LLM JSON parse failed ({exc}), using fallback")
        else:
            logger.warning("LLM returned None or failed — using fallback parse")

        return self._fallback_parse(user_request)

    # ──────────────────────────────────────────────────────
    #  Fast-path helpers
    # ──────────────────────────────────────────────────────

    def _detect_app_task(self, request: str) -> Optional[str]:
        lowered = request.lower()
        in_patterns = (" in ", " using ", " with ", " on ", " via ")
        for app in KNOWN_APP_NAMES:
            for prep in in_patterns:
                if prep + app in lowered or lowered.startswith(app + " "):
                    return app
            for verb in ("open ", "launch ", "start ", "run "):
                if verb + app in lowered:
                    return app
        return None

    def _build_app_task_plan(self, user_request: str, app_name: str) -> TaskPlan:
        words = len(user_request.split())
        max_steps = 10 if words < 15 else (15 if words < 30 else 20)
        return TaskPlan(
            original_request=user_request,
            task_type=TaskType.APPLICATION_CONTROL,
            summary=f"Perform task in {app_name.title()}: {user_request[:80]}",
            steps=[TaskStep(
                step_number=1,
                description=f"Perform task in {app_name}: {user_request}",
                agent="application_agent",
                action="do_task_in_app",
                parameters={
                    "app_name": app_name,
                    "task_description": user_request,
                    "max_steps": max_steps,
                },
                verification_method=f"Confirm {app_name} completed the requested task",
                risk_level=RiskLevel.LOW,
                requires_confirmation=False,
            )],
            estimated_duration="medium",
            risk_assessment=RiskLevel.LOW,
        )

    def _is_drawing_request(self, request: str) -> bool:
        rl = request.lower()
        has_draw = any(kw in rl for kw in DRAWING_KEYWORDS)
        has_paint = any(kw in rl for kw in DRAWING_APP_KEYWORDS)
        return has_draw and has_paint

    def _build_drawing_plan(self, request: str) -> TaskPlan:
        subject, color = self._extract_drawing_details(request)
        save_path_match = re.search(
            r'save\s+(?:to\s+|as\s+)?["\']?([^\s"\']+\.(png|jpg|bmp))["\']?',
            request, re.IGNORECASE,
        )
        save_path = save_path_match.group(1) if save_path_match else None

        steps = [TaskStep(
            step_number=1,
            description=f"Draw '{subject}' in MS Paint using real mouse control",
            agent="application_agent",
            action="execute_paint_task",   # routes to StepExecutor pipeline
            parameters={"subject": subject, "color": color, "save_path": save_path},
            verification_method="MS Paint is open and the drawing is visible on the canvas",
            risk_level=RiskLevel.SAFE,
        )]
        if save_path:
            steps.append(TaskStep(
                step_number=2,
                description=f"Verify saved file exists at {save_path}",
                agent="file_agent",
                action="info",
                parameters={"path": save_path},
                verification_method="File exists and size > 0",
                risk_level=RiskLevel.SAFE,
            ))

        return TaskPlan(
            original_request=request,
            task_type=TaskType.DRAWING,
            summary=f"Draw a {subject} in MS Paint",
            steps=steps,
            estimated_duration="medium",
            requires_user_confirm=False,
            risk_assessment=RiskLevel.SAFE,
        )

    def _extract_drawing_details(self, request: str) -> tuple:
        rl = request.lower()
        colors = [
            "red", "blue", "green", "yellow", "orange", "purple", "pink",
            "black", "white", "brown", "gray", "grey", "cyan", "magenta",
            "gold", "silver", "crimson", "navy", "teal", "lime", "violet",
            "indigo", "maroon", "olive", "turquoise", "skyblue", "dark blue",
            "light blue", "dark red", "dark green",
        ]
        detected_color = "blue"
        for c in sorted(colors, key=len, reverse=True):
            if c in rl:
                detected_color = c
                break

        subject = re.sub(
            r'\b(draw|paint|sketch|create|make|generate|illustrate|depict|render)\b',
            "", rl, flags=re.IGNORECASE,
        )
        subject = re.sub(
            r'\b(in\s+)?(ms\s+paint|mspaint|paint|microsoft paint)\b',
            "", subject, flags=re.IGNORECASE,
        )
        subject = re.sub(
            r'\b(a|an|the|please|can you|could you|i want|i need)\b',
            "", subject, flags=re.IGNORECASE,
        )
        subject = subject.replace(detected_color, "")
        subject = " ".join(subject.split()).strip(" .,!?")
        return (subject or "sports car"), detected_color

    # ──────────────────────────────────────────────────────
    #  Fallback (rule-based, no LLM)
    # ──────────────────────────────────────────────────────

    # O(1) action/parameter template per agent — replaces action="execute" fallback
    _FALLBACK_ACTION_MAP = {
        "application_agent": {"action": "open_and_draw",   "param_key": "description"},
        "file_agent":        {"action": "read_file",        "param_key": "path"},
        "system_agent":      {"action": "run_command",      "param_key": "command_line"},
        "browser_agent":     {"action": "navigate",         "param_key": "url"},
        "code_agent":        {"action": "execute_code",     "param_key": "code"},
    }
    _FALLBACK_DEFAULT   = {"action": "run_command", "param_key": "command_line"}

    def _fallback_parse(self, user_request: str) -> TaskPlan:
        """
        Rule-based parse used when LLM is unavailable or returns invalid JSON.
        Uses per-agent action/parameter templates — never action='execute'.
        Multi-step detection via O(1) regex, dispatch via dict lookup.
        """
        rl        = user_request.lower()
        task_type = self._detect_task_type_fast(rl)
        risk      = _assess_risk_fast(rl)
        agent     = self._detect_agent_fast(rl)

        _is_multi   = {True: lambda: TaskType.MULTI_STEP}
        _multi_type = _is_multi.get(bool(re.search(r"\band\b|\bthen\b", rl)))
        task_type   = _multi_type() if _multi_type else task_type

        _steps_fn = {
            True:  lambda: self._break_into_subtasks(user_request, agent, risk),
            False: lambda: [self._make_fallback_step(1, user_request, agent, risk)],
        }
        steps = _steps_fn[bool(_multi_type)]()

        return TaskPlan(
            original_request=user_request,
            task_type=task_type,
            summary=f"Execute: {user_request}",
            steps=steps,
            requires_user_confirm=risk in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            risk_assessment=risk,
        )

    def _make_fallback_step(self, number: int, description: str,
                             agent: str, risk) -> "TaskStep":
        """Build a single TaskStep using the per-agent action template."""
        tmpl      = self._FALLBACK_ACTION_MAP.get(agent, self._FALLBACK_DEFAULT)
        action    = tmpl["action"]
        param_key = tmpl["param_key"]
        return TaskStep(
            step_number=number,
            description=description,
            agent=agent,
            action=action,
            parameters={param_key: description},
            verification_method="Verify the desired outcome was achieved",
            requires_confirmation=risk in (RiskLevel.HIGH, RiskLevel.CRITICAL),
            risk_level=risk,
        )

    def _detect_task_type_fast(self, request: str) -> TaskType:
        """O(words) with O(1) per-word lookup — replaces O(n*k) if-elif chain."""
        for word in request.split():
            task_type = WORD_TO_TASK_TYPE.get(word)
            if task_type:
                return task_type
        return TaskType.UNKNOWN

    def _detect_agent_fast(self, request: str) -> str:
        """O(words) with O(1) per-word dict lookup."""
        for word in request.split():
            agent = AGENT_MAPPING.get(word)
            if agent:
                return agent
        return "system_agent"

    def _break_into_subtasks(self, request: str, default_agent: str,
                              risk: RiskLevel) -> List[TaskStep]:
        """
        Split a multi-step request and build per-agent action steps.
        Uses _make_fallback_step() — never action='execute'.
        """
        parts = re.split(r"\s+(?:and|then|after that|next)\s+", request)
        return [
            self._make_fallback_step(
                i + 1,
                p.strip(),
                self._detect_agent_fast(p.lower()) or default_agent,
                risk,
            )
            for i, p in enumerate(parts) if p.strip()
        ]

    # ──────────────────────────────────────────────────────
    #  JSON helpers
    # ──────────────────────────────────────────────────────

    @staticmethod
    def _extract_json(content: str) -> Dict:
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return json.loads(content)

    @staticmethod
    def _create_task_plan(original: str, parsed: Dict) -> TaskPlan:
        steps = []
        for s in parsed.get("steps", []):
            try:
                risk = RiskLevel(s.get("risk_level", "safe").lower())
            except ValueError:
                risk = RiskLevel.SAFE
            steps.append(TaskStep(
                step_number=s.get("step_number", len(steps) + 1),
                description=s.get("description", ""),
                agent=s.get("agent", "system_agent"),
                action=s.get("action", "execute"),
                parameters=s.get("parameters", {}),
                verification_method=s.get("verification_method", ""),
                rollback_action=s.get("rollback_action", ""),
                requires_confirmation=s.get("requires_confirmation", False),
                risk_level=risk,
                depends_on=TaskParser._coerce_depends_on(s.get("depends_on", [])),
            ))

        try:
            task_type = TaskType(parsed.get("task_type", "unknown").lower())
        except ValueError:
            task_type = TaskType.UNKNOWN

        try:
            risk = RiskLevel(parsed.get("risk_assessment", "safe").lower())
        except ValueError:
            risk = RiskLevel.SAFE

        return TaskPlan(
            original_request=original,
            task_type=task_type,
            summary=parsed.get("summary", ""),
            steps=steps,
            estimated_duration=parsed.get("estimated_duration", "unknown"),
            requires_user_confirm=parsed.get("requires_user_confirm", False),
            risk_assessment=risk,
            context_needed=parsed.get("context_needed", []),
        )

    @staticmethod
    def _coerce_depends_on(value: Any) -> List[int]:
        raw_values = _DEPENDENCY_NORMALIZERS.get(type(value), lambda item: [item])(value)
        step_numbers: List[int] = []
        for raw_value in raw_values:
            try:
                step_numbers.append(int(raw_value))
            except (TypeError, ValueError):
                continue
        return step_numbers

    def quick_classify(self, request: str) -> Dict[str, Any]:
        rl = request.lower()
        return {
            "task_type":     self._detect_task_type_fast(rl).value,
            "agent":         self._detect_agent_fast(rl),
            "risk":          _assess_risk_fast(rl).value,
            "is_drawing":    self._is_drawing_request(request),
            "is_multi_step": bool(re.search(r"\band\b|\bthen\b", rl)),
            "needs_vision":  any(w in rl for w in
                                 ("screen", "look", "see", "find", "click", "draw")),
        }
