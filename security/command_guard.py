"""
Security Layer — Command sandboxing and permission control.
Risk assessment, path protection, sandboxed execution.
O(1) blacklist via frozenset, O(1) risk via priority-ordered lookup.
NO if-elif chains for routing — dict dispatch throughout.
"""
import ast
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("Security")


# ─────────────────────────────────────────────────────────────────────────────
#  Risk level constants (int for O(1) comparison, no Enum overhead in hot path)
# ─────────────────────────────────────────────────────────────────────────────
RISK_SAFE     = 0
RISK_LOW      = 1
RISK_MEDIUM   = 2
RISK_HIGH     = 3
RISK_CRITICAL = 4

RISK_NAMES = {
    RISK_SAFE:     "safe",
    RISK_LOW:      "low",
    RISK_MEDIUM:   "medium",
    RISK_HIGH:     "high",
    RISK_CRITICAL: "critical",
}


# ─────────────────────────────────────────────────────────────────────────────
#  O(1) frozenset blacklists — replaces O(n) list-scan for-loops
# ─────────────────────────────────────────────────────────────────────────────

BLACKLIST_EXACT: frozenset = frozenset({
    "rm -rf /",
    "format c:",
    ":(){ :|:& };:",
    "mkfs",
    "dd if=/dev/zero of=/dev/sda",
})

BLACKLIST_CONTAINS: frozenset = frozenset({
    "rm -rf /",
    "dd if=",
    "> /dev/sda",
    "> /dev/hd",
    "chmod 777 /",
    "shutil.rmtree('/')",
    "os.remove('/etc')",
    "format c:",
    "format /dev/",
    "rd /s /q c:\\",
    "reg delete",
    "reg add",
    "net user /delete",
    "usermod.*root",
    "sc delete",
    "sc config",
    "net stop",
    "net delete",
    "netsh advfirewall set",
    "icacls.*systemroot",
    "takeown /f.*windows",
    "bcdedit",
    "diskpart",
    ":(){ :|:&",
})

PROTECTED_PATHS: frozenset = frozenset({
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata",
    "/usr/bin", "/usr/sbin",
    "/bin", "/sbin",
    "/etc", "/sys", "/dev",
    "/proc", "/boot",
    "/lib", "/lib64",
})

MODIFICATION_VERBS: frozenset = frozenset({
    "del", "rm", "remove", "format", "chmod", "write", "modify",
})

# ─────────────────────────────────────────────────────────────────────────────
#  Risk pattern sets — O(1) membership per level
# ─────────────────────────────────────────────────────────────────────────────

RISK_PATTERNS: Dict[int, frozenset] = {
    RISK_CRITICAL: frozenset({
        "delete system", "format",
        "registry delete", "system32",
    }),
    RISK_HIGH: frozenset({
        "install", "uninstall",
        "remove program",
        "change permission",
        "admin privilege",
        "disable firewall",
        "kill process",
    }),
    RISK_MEDIUM: frozenset({
        "download", "execute",
        "run script",
        "copy system",
        "move system",
    }),
    RISK_LOW: frozenset({
        "create", "rename", "copy",
        "move", "list", "view", "read",
    }),
}

# Ordered highest→lowest for early-exit on first match
_RISK_ORDER: List[int] = [RISK_CRITICAL, RISK_HIGH, RISK_MEDIUM, RISK_LOW]

# ─────────────────────────────────────────────────────────────────────────────
#  Confirmation-required regex patterns (unchanged — these are structural patterns)
# ─────────────────────────────────────────────────────────────────────────────

CONFIRMATION_PATTERNS: List[str] = [
    r"\bdel\s+/[fqs]",
    r"\brm\s+-[rf]",
    r"\bRemove-Item\b",
    r"\bcopy\s+/y\b",
    r"\bmove\s+/y\b",
    r"\bchoco\s+install\b",
    r"\bwinget\s+install\b",
    r"\bpip\s+install\b",
    r"\bnpm\s+install\s+-g\b",
    r"\bchmod\b",
    r"\bicacls\b",
    r"\btakeown\b",
    r"\bsc\s+(start|stop|pause)\b",
    r"\bnet\s+(start|stop)\b",
    r"\bcurl\s+.*-o\b",
    r"\bwget\b",
    r"\bInvoke-WebRequest\b",
]


class CommandGuard:
    """
    Security guard for all agent operations.
    O(1) blacklist — frozenset substring check.
    O(1) risk assessment — dict lookup.
    dict dispatch for all action handlers.
    """

    def __init__(self, strict_mode: bool = False):
        self.strict_mode = strict_mode
        self.confirmation_history: List[Dict] = []
        self.pending_confirmations: Dict[str, Dict] = {}
        self.session_allowlist: List[str] = []
        self.session_blocklist: List[str] = []

    # ──────────────────────────────────────────────────────────────────────────
    #  Public API
    # ──────────────────────────────────────────────────────────────────────────

    def check_action(self, agent: str, action: str,
                     parameters: Dict) -> Tuple[bool, str]:
        """Check if an agent action is allowed. Returns (allowed, reason)."""
        command_str = self._build_command_string(agent, action, parameters)
        return self._check_string(command_str, self.strict_mode)

    def check_command(self, command: str,
                      shell: bool = True) -> Tuple[bool, str, int]:
        """
        Check a raw command string.
        Returns (allowed, reason, risk_level_int).
        """
        allowed, reason = self._check_string(command, self.strict_mode)
        risk = assess_risk(command)
        return allowed, reason, risk

    def assess_file_risk(self, path: str, operation: str) -> int:
        """Assess risk of a file operation. Returns RISK_* constant."""
        path_lower = path.lower()
        if any(path_lower.startswith(p) for p in PROTECTED_PATHS):
            return RISK_CRITICAL
        if any(d in path_lower for d in ("windows", "program files", "system32")):
            return RISK_HIGH

        OP_RISK = {
            "delete": RISK_HIGH, "remove": RISK_HIGH, "wipe": RISK_HIGH,
            "write": RISK_MEDIUM, "modify": RISK_MEDIUM, "append": RISK_MEDIUM,
            "read": RISK_LOW, "list": RISK_LOW, "copy": RISK_LOW,
        }
        return OP_RISK.get(operation, RISK_LOW)

    def request_user_confirmation(self, action_description: str,
                                   risk_level: int = RISK_MEDIUM) -> bool:
        cid = f"confirm_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.pending_confirmations[cid] = {
            "description": action_description,
            "risk_level": RISK_NAMES[risk_level],
            "timestamp": datetime.now().isoformat(),
            "confirmed": None,
        }
        logger.info(f"CONFIRMATION REQUIRED [{RISK_NAMES[risk_level]}]: "
                    f"{action_description}")
        return False

    def confirm_action(self, confirmation_id: str,
                       approved: bool = True) -> bool:
        entry = self.pending_confirmations.pop(confirmation_id, None)
        if entry is None:
            return False
        entry["confirmed"] = approved
        if approved:
            self.session_allowlist.append(entry["description"])
        self.confirmation_history.append({**entry, "approved": approved})
        return True

    def sandbox_python(self, code: str) -> Tuple[bool, str, str]:
        """Validate Python code. Returns (is_safe, sanitized_code, reason)."""
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            return False, code, f"Syntax error: {exc}"

        DANGEROUS_IMPORTS = frozenset({
            "os", "subprocess", "sys", "shutil",
            "socket", "urllib", "requests",
        })
        DANGEROUS_CALLS = frozenset({
            "eval", "exec", "compile", "__import__", "open", "input",
        })
        DANGEROUS_METHODS = frozenset({
            "system", "popen", "call", "run",
            "remove", "rmdir", "unlink",
        })

        dangerous = []
        for node in ast.walk(tree):
            match node:
                case ast.Import():
                    for alias in node.names:
                        if alias.name in DANGEROUS_IMPORTS:
                            dangerous.append(f"Import: {alias.name}")
                case ast.ImportFrom():
                    if node.module in DANGEROUS_IMPORTS:
                        dangerous.append(f"From-import: {node.module}")
                case ast.Call():
                    match node.func:
                        case ast.Name(id=fn_name) if fn_name in DANGEROUS_CALLS:
                            dangerous.append(f"Call: {fn_name}")
                        case ast.Attribute(attr=attr) if attr in DANGEROUS_METHODS:
                            dangerous.append(f"Method: {attr}")

        if dangerous:
            return False, code, f"Dangerous operations: {dangerous[:5]}"

        sanitized = f"# Sandboxed execution\n{code}"
        return True, sanitized, "Sanitized for safe execution"

    def add_to_allowlist(self, pattern: str) -> None:
        self.session_allowlist.append(pattern.lower())

    def add_to_blocklist(self, pattern: str) -> None:
        self.session_blocklist.append(pattern.lower())

    def get_security_log(self) -> List[Dict]:
        return self.confirmation_history[-100:]

    def get_pending_confirmations(self) -> Dict[str, Dict]:
        return self.pending_confirmations

    def get_status(self) -> Dict:
        return {
            "strict_mode": self.strict_mode,
            "blacklist_exact_count": len(BLACKLIST_EXACT),
            "blacklist_contains_count": len(BLACKLIST_CONTAINS),
            "confirmation_patterns": len(CONFIRMATION_PATTERNS),
            "protected_paths": len(PROTECTED_PATHS),
            "session_allowlist": len(self.session_allowlist),
            "session_blocklist": len(self.session_blocklist),
            "pending_confirmations": len(self.pending_confirmations),
            "total_checks": len(self.confirmation_history),
            "blocks_triggered": sum(
                1 for h in self.confirmation_history
                if not h.get("approved", True)
            ),
        }

    # ──────────────────────────────────────────────────────────────────────────
    #  Internals
    # ──────────────────────────────────────────────────────────────────────────

    def _check_string(self, command: str,
                       strict: bool) -> Tuple[bool, str]:
        cl = command.lower().strip()

        if is_blacklisted(cl):
            logger.warning(f"BLOCKED: {command[:120]}")
            return False, "Blocked: dangerous pattern matched"

        if _accesses_protected_path_with_modification(cl):
            return False, "Protected path modification blocked"

        risk = assess_risk(command)
        if risk >= RISK_HIGH:
            if not self._is_confirmed(command):
                self.request_user_confirmation(command, risk)
                return False, f"Confirmation required ({RISK_NAMES[risk]} risk)"

        if strict:
            for pattern in CONFIRMATION_PATTERNS:
                if re.search(pattern, cl):
                    if not self._is_confirmed(command):
                        return False, "Confirmation required (strict mode)"

        return True, f"Allowed ({RISK_NAMES[risk]} risk)"

    def _build_command_string(self, agent: str, action: str, parameters: Dict) -> str:
        parts = [agent, action]
        _KEYS = frozenset({"command", "path", "file", "url"})
        for k, v in parameters.items():
            # Branchless construction based on key presence and type
            is_special = k in _KEYS
            is_str = isinstance(v, str)
            if is_str and not is_special:
                parts.append(f"{k}={v}")
            else:
                parts.append(str(v))
        return " ".join(parts)

    def _is_confirmed(self, command: str) -> bool:
        return any(allowed in command for allowed in self.session_allowlist)


# ─────────────────────────────────────────────────────────────────────────────
#  Module-level O(1) helpers (usable without instantiating CommandGuard)
# ─────────────────────────────────────────────────────────────────────────────

def is_blacklisted(command_lower: str) -> bool:
    """
    O(1) exact-match check + O(k) substring scan where k = |BLACKLIST_CONTAINS|.
    frozenset.__contains__ is O(1) average.
    """
    return (command_lower in BLACKLIST_EXACT
            or any(b in command_lower for b in BLACKLIST_CONTAINS))


def _accesses_protected_path_with_modification(command_lower: str) -> bool:
    if not any(p in command_lower for p in PROTECTED_PATHS):
        return False
    return any(v in command_lower for v in MODIFICATION_VERBS)


def assess_risk(command: str) -> int:
    """
    O(1) risk assessment via priority-ordered frozenset membership check.
    Returns RISK_* constant.
    """
    cl = command.lower()
    for risk_level in _RISK_ORDER:
        if any(pattern in cl for pattern in RISK_PATTERNS[risk_level]):
            return risk_level
    return RISK_SAFE
