"""Progress event protocol for CLI and web streaming."""

from dataclasses import dataclass, field
from typing import Generator


@dataclass
class ProgressEvent:
    """A progress update yielded by long-running operations.

    Used by both CLI (Rich progress bars) and web (SSE streaming).
    """
    step: str
    progress: float  # 0.0 to 1.0
    message: str = ""
    detail: str = ""
    sub_step: str = ""  # e.g. LOD name within training
    sub_progress: float = 0.0  # 0.0 to 1.0 within sub_step


@dataclass
class StepResult:
    """Result of a completed step."""
    step: str
    success: bool
    summary: dict = field(default_factory=dict)
    error: str | None = None
    debug_path: str | None = None


# Type alias for generator functions that yield progress and return a result
ProgressGenerator = Generator[ProgressEvent, None, StepResult]
