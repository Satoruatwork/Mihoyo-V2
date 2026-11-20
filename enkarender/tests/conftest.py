"""Shared fixtures. Points the engine's cache/asset/font dirs at a tmp path so tests never
touch the real ``~/.enkarender`` home and stay hermetic."""

from __future__ import annotations

import pytest

from enkarender.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    s = Settings(home=tmp_path)
    s.ensure_dirs()
    return s
