import os
import tempfile
from pathlib import Path

# Keep tests away from ~/.kinenix/kinenix.env: a Hub saved there by `kinenix connect` would receive every
# test run. Set before any test imports kinenix; subprocesses started by tests inherit it.
os.environ["KINENIX_SETTINGS_FILE"] = str(Path(tempfile.mkdtemp(prefix="kinenix-tests-")) / "kinenix.env")


import pytest  # noqa: E402


@pytest.fixture(scope="session")
def chromium():
    """
    Tests that drive a real browser use this. Without Chromium they are skipped on a developer's machine,
    but they fail in CI (CI=true), where Chromium is installed, so a broken install cannot hide them.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception as e:
        if os.environ.get("CI"):
            pytest.fail(f"Chromium must be available in CI: {e}")
        pytest.skip(f"Chromium not available: {e}")
    return True


@pytest.fixture(autouse=True)
def _own_outbox(tmp_path, monkeypatch):
    """Each test gets its own outbox for runs that did not reach the Hub, so one test's kept runs never reach another's mock."""
    from kinenix.engine import outbox
    monkeypatch.setattr(outbox, "outbox_dir", lambda: tmp_path / "outbox")
