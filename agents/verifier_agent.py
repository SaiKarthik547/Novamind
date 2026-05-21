"""
VerifierAgent — THE most critical agent.
Runs after every tool execution. Uses an isolated LLM call to check
whether the actual output satisfied the goal. Never shares context
with producing agents (prevents collective delusion).
Pattern: Coordinator/Implementor/Verifier from Augment Code architecture.
"""
import json
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from core.llm_router import get_router
from core.base_agent import BaseAgent

logger = logging.getLogger("VerifierAgent")

VERIFICATION_PROMPT = """You are an independent verification agent.
You were NOT involved in producing this output. Evaluate objectively.

Task Goal: {task_description}
Tool Used: {tool_name}
Expected Output Pattern: {expected_output}
Actual Output: {actual_output}

Respond in JSON ONLY. No prose. No markdown.
{{
  "satisfied": true_or_false,
  "confidence": 0.0_to_1.0,
  "issues": ["list", "of", "problems"],
  "evidence": "what specifically proves success or failure",
  "next_action": "continue|retry|escalate|abort",
  "retry_strategy": "if retry: what to do differently"
}}"""


@dataclass
class VerificationResult:
    satisfied: bool
    confidence: float
    issues: List[str]
    evidence: str
    next_action: str
    retry_strategy: str
    raw_response: str = ""

    @property
    def should_retry(self) -> bool:
        return not self.satisfied and self.confidence < 0.7

    @property
    def should_escalate(self) -> bool:
        return not self.satisfied and self.confidence < 0.4

    def to_dict(self) -> Dict:
        return {
            "satisfied": self.satisfied,
            "confidence": self.confidence,
            "issues": self.issues,
            "evidence": self.evidence,
            "next_action": self.next_action,
            "retry_strategy": self.retry_strategy,
        }


class VerifierAgent(BaseAgent):
    """
    Independent output verifier.
    Isolated from all producing agents — shares NO context with them.
    Every tool result passes through here before being marked complete.
    """

    CONFIDENCE_RETRY_THRESHOLD     = 0.7
    CONFIDENCE_ESCALATE_THRESHOLD  = 0.4

    def __init__(self, memory_system=None, event_bus=None):
        super().__init__()
        self.router = get_router()
        self.memory = memory_system
        self.event_bus = event_bus

        self.handlers = {
            "verify":     lambda **p: {"success": True, **self.verify(**p).to_dict()},
            "verify_gui": lambda **p: {"success": True, **self.verify_gui_action(**p).to_dict()},
        }

    def verify(self, task_description: str, tool_name: str,
               expected_output: Any, actual_output: Any,
               task_id: str = None) -> VerificationResult:
        """
        Main verification entry point. LLM-based, fully isolated.
        Never skip this. Never assume success without confidence >= 0.7.
        """
        prompt = VERIFICATION_PROMPT.format(
            task_description=task_description,
            tool_name=tool_name,
            expected_output=json.dumps(expected_output, default=str)[:500],
            actual_output=json.dumps(actual_output, default=str)[:1500],
        )

        response = self.router.quick_request(prompt, task_type="quick")
        result = self._parse_verification(response)

        if self.memory and task_id:
            try:
                self.memory.log_error(
                    error_msg=f"Verification: satisfied={result.satisfied} "
                              f"confidence={result.confidence:.2f} "
                              f"issues={result.issues}",
                    task_id=task_id,
                    agent="verifier_agent",
                    action="verify",
                    severity="low" if result.satisfied else "medium",
                )
            except Exception:
                pass

        if self.event_bus:
            event_data = {
                "task_id": task_id,
                "tool": tool_name,
                "satisfied": result.satisfied,
                "confidence": result.confidence,
                "next_action": result.next_action,
            }
            self.event_bus.emit_sync(
                "task_completed" if result.satisfied else "task_failed",
                event_data,
            )

        level = ("✓" if result.satisfied else "✗")
        logger.info(
            f"[Verifier] {level} {tool_name} "
            f"conf={result.confidence:.2f} action={result.next_action}"
        )
        return result

    def verify_gui_action(self, description: str, before_path: str,
                          after_path: str, task_id: str = None) -> VerificationResult:
        """
        Visual verification for GUI tasks (MS Paint, clicks, typing).
        Takes before/after screenshots and checks if the canvas changed.
        """
        try:
            from vision.vision_system import VisionSystem
            vision = VisionSystem()
            compare = vision.compare_images(before_path, after_path)
            changed = compare.get("images_differ", False)
            similarity = compare.get("similarity", 1.0)

            actual = {
                "changed": changed,
                "similarity": similarity,
                "changed_percent": compare.get("changed_percent"),
            }
            return self.verify(
                task_description=description,
                tool_name="gui_visual_verify",
                expected_output={"changed": True, "similarity_lt": 0.99},
                actual_output=actual,
                task_id=task_id,
            )
        except Exception as exc:
            logger.warning(f"GUI visual verify failed: {exc}")
            return VerificationResult(
                satisfied=False,
                confidence=0.3,
                issues=[str(exc)],
                evidence="Visual comparison failed",
                next_action="retry",
                retry_strategy="Re-attempt the GUI action",
            )

    def _parse_verification(self, raw: str) -> VerificationResult:
        """Parse LLM JSON response. Never trust satisfied=true w/o confidence."""
        import re
        defaults = VerificationResult(
            satisfied=False,
            confidence=0.5,
            issues=["Verification parse failed"],
            evidence=raw[:200],
            next_action="retry",
            retry_strategy="Retry with same approach",
            raw_response=raw,
        )
        try:
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                return defaults
            data = json.loads(match.group())

            satisfied = bool(data.get("satisfied", False))
            confidence = float(data.get("confidence", 0.5))
            if confidence < 0.0 or confidence > 1.0:
                confidence = max(0.0, min(1.0, confidence))

            if satisfied and confidence < self.CONFIDENCE_RETRY_THRESHOLD:
                satisfied = False

            next_action = data.get("next_action", "retry")
            if next_action not in ("continue", "retry", "escalate", "abort"):
                next_action = "continue" if satisfied else "retry"

            return VerificationResult(
                satisfied=satisfied,
                confidence=confidence,
                issues=data.get("issues", []),
                evidence=data.get("evidence", ""),
                next_action=next_action,
                retry_strategy=data.get("retry_strategy", ""),
                raw_response=raw,
            )
        except Exception as exc:
            logger.warning(f"Verification parse error: {exc}")
            return defaults


