"""Local workspace fixture; no global tmp_path/ACL override."""
from pathlib import Path
from uuid import uuid4
import pytest


@pytest.fixture
def workspace():
    root = Path(__file__).resolve().parents[2] / 'test-workspaces' / uuid4().hex
    root.mkdir(parents=True)
    return root
