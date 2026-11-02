"""Use ordinary workspace directories: pytest's Windows mode-0700 temp ACL fails on J:."""
from pathlib import Path
import uuid

import pytest


@pytest.fixture
def tmp_path():
    directory = Path(__file__).resolve().parents[1] / "test-workspaces" / uuid.uuid4().hex
    directory.mkdir(mode=0o777, parents=True)
    return directory
