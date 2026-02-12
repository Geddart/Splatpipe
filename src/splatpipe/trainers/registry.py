"""Trainer registry: maps trainer names to implementations."""

from .base import Trainer
from .postshot import PostshotTrainer
from .lichtfeld import LichtfeldTrainer

TRAINERS: dict[str, type[Trainer]] = {
    "postshot": PostshotTrainer,
    "lichtfeld": LichtfeldTrainer,
}


def get_trainer(name: str, config: dict) -> Trainer:
    """Get a trainer instance by name.

    Raises KeyError if the trainer name is unknown.
    """
    cls = TRAINERS.get(name)
    if cls is None:
        available = ", ".join(TRAINERS.keys())
        raise KeyError(f"Unknown trainer: {name!r}. Available: {available}")
    return cls(config)


def list_trainers() -> list[str]:
    """Return available trainer names."""
    return list(TRAINERS.keys())
