import os
import tempfile
from pathlib import Path

import pytest

# Keep tests away from ~/.kinenix/kinenix.env: a Hub saved there by `kinenix connect` would receive every
# test run. Set before any test imports kinenix; subprocesses started by tests inherit it.
os.environ["KINENIX_SETTINGS_FILE"] = str(Path(tempfile.mkdtemp(prefix="kinenix-tests-")) / "kinenix.env")


@pytest.fixture(autouse=True)
def _own_outbox(tmp_path, monkeypatch):
    """Each test gets its own outbox for runs that did not reach the Hub, so one test's kept runs never reach another's mock."""
    from kinenix.engine import outbox
    monkeypatch.setattr(outbox, "outbox_dir", lambda: tmp_path / "outbox")
