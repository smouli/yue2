import os
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from yue2.config import Settings
from yue2.models.fake import write_profile


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    base = Settings.from_env()
    s = replace(base, home=tmp_path, storage="local", storage_dir=tmp_path / "storage", models="fake",
                melody_dir=tmp_path / "melody", llm_api_key="", writer_model="fake", weave_project="", takes=2)
    write_profile(s.melody_dir)
    return s


PARAGRAPH = (
    "The precise start and end of the Industrial Revolution is debated among historians, as is the pace of "
    "economic and social changes. Rapid adoption of mechanized textiles spinning occurred in Britain in the 1780s, "
    "and high rates of growth in steam power and iron production occurred after 1800."
)
