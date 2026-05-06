"""Config module loads and validates config.yaml."""

from pathlib import Path

import pytest
import yaml

from readwise_review.config import Config, load_config


def test_load_config_reads_all_fields(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "highlights_per_email": 5,
        "to_email": "to@example.com",
        "from_email": "from@example.com",
        "bootstrap_book_id": 42,
        "timezone": "America/Chicago",
    }))

    cfg = load_config(cfg_file)

    assert cfg == Config(
        highlights_per_email=5,
        to_email="to@example.com",
        from_email="from@example.com",
        bootstrap_book_id=42,
        timezone="America/Chicago",
    )


def test_load_config_defaults_bootstrap_book_id_to_none(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "highlights_per_email": 8,
        "to_email": "to@example.com",
        "from_email": "from@example.com",
        "timezone": "America/Chicago",
    }))

    cfg = load_config(cfg_file)

    assert cfg.bootstrap_book_id is None


def test_load_config_rejects_missing_required_field(tmp_path: Path) -> None:
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(yaml.safe_dump({
        "highlights_per_email": 8,
        # missing to_email
        "from_email": "from@example.com",
        "timezone": "America/Chicago",
    }))

    with pytest.raises(KeyError):
        load_config(cfg_file)
