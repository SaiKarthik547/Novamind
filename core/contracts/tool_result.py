"""
Tool Result Contract + Tool Registry.
Every tool returns a ToolResult. No silent failures.
TOOL_REGISTRY uses decorator pattern — O(1) lookup, zero if-else routing.
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Type

logger = logging.getLogger("ToolRegistry")


@dataclass
class ToolResult:
    success: bool
    output: Any
    error: Optional[str]
    execution_time_ms: int
    tool_name: str
    metadata: Dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.success

    def to_dict(self) -> Dict:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "execution_time_ms": self.execution_time_ms,
            "tool_name": self.tool_name,
            "metadata": self.metadata,
        }


class Tool(ABC):
    name: str = ""
    description: str = ""
    input_schema: Dict = field(default_factory=dict)
    output_schema: Dict = field(default_factory=dict)
    risk_level: int = 0
    timeout_seconds: int = 30
    max_retries: int = 3

    @abstractmethod
    async def execute(self, args: Dict) -> ToolResult:
        """Implementation stub"""

    def _result(self, success: bool, output: Any = None,
                error: str = None, start_ms: float = None,
                **metadata) -> ToolResult:
        elapsed = int((time.time() - start_ms) * 1000) if start_ms else 0
        return ToolResult(
            success=success,
            output=output,
            error=error,
            execution_time_ms=elapsed,
            tool_name=self.name,
            metadata=metadata,
        )


TOOL_REGISTRY: Dict[str, Type[Tool]] = {}


def register_tool(name: str):
    """
    Decorator that auto-registers a Tool subclass.
    O(1) routing — zero if-else ever needed in dispatch.

    Usage:
        @register_tool("browser_navigate")
        class BrowserNavigateTool(Tool):
            ...
    """
    def decorator(cls: Type[Tool]) -> Type[Tool]:
        cls.name = name
        TOOL_REGISTRY[name] = cls
        logger.debug(f"Tool registered: {name}")
        return cls
    return decorator


def get_tool(name: str) -> Tool:
    """O(1) dict lookup — replaces every tool-routing if-else."""
    cls = TOOL_REGISTRY.get(name)
    if cls is None:
        raise KeyError(f"Unknown tool: '{name}'. "
                       f"Registered: {list(TOOL_REGISTRY)}")
    return cls()


class ToolNotFoundError(KeyError):
    """Implementation stub"""