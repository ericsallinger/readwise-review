"""Loads and validates config.yaml."""

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Config:
    highlights_per_email: int
    to_email: str
    from_email: str
    timezone: str
    bootstrap_book_id: int | None = None


def load_config(path: Path | str = "config.yaml") -> Config:
    raw = yaml.safe_load(Path(path).read_text())
    return Config(
        highlights_per_email=raw["highlights_per_email"],
        to_email=raw["to_email"],
        from_email=raw["from_email"],
        timezone=raw["timezone"],
        bootstrap_book_id=raw.get("bootstrap_book_id"),
    )
