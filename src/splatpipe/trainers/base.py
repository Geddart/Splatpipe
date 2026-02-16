"""Abstract trainer interface for Gaussian splatting backends."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Generator

from ..core.events import ProgressEvent


@dataclass
class TrainResult:
    """Result of training a single LOD."""
    lod_name: str
    max_splats: int
    success: bool
    command: list[str] = field(default_factory=list)
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0
    output_dir: str = ""
    output_ply: str = ""
    warning: str = ""


class Trainer(ABC):
    """Abstract base for training backends (Postshot, LichtFeld, etc.)."""

    def __init__(self, config: dict):
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier for this trainer."""

    @abstractmethod
    def train_lod(
        self,
        source_dir: Path,
        output_dir: Path,
        lod_name: str,
        max_splats: int,
        *,
        num_images: int = 0,
        **kwargs,
    ) -> Generator[ProgressEvent, None, TrainResult]:
        """Train a single LOD level, yielding progress events.

        Args:
            source_dir: COLMAP directory or other input
            output_dir: Where to write training outputs
            lod_name: e.g. "lod0"
            max_splats: Maximum number of Gaussians
            num_images: Number of input images (for auto-step computation)

        Yields:
            ProgressEvent with training progress (0.0 to 1.0)

        Returns:
            TrainResult with full diagnostics
        """

    @abstractmethod
    def validate_environment(self) -> tuple[bool, str]:
        """Check that the trainer's dependencies are available.

        Returns:
            (ok, message) — ok=True if ready, message explains why not
        """

    def parse_progress(self, line: str) -> float | None:
        """Parse a stdout line for progress information.

        Returns float 0.0-1.0 if progress was found, None otherwise.
        Override in subclasses for trainer-specific parsing.
        """
        return None

    def compute_training_steps(self, num_images: int) -> int:
        """Compute the number of training steps/iterations.

        Default: max(50, round(image_count * 52 / 1000)) kSteps for Postshot.
        Override for other trainers.
        """
        return max(50, round(num_images * 52 / 1000))
