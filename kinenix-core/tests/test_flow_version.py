"""> Version: in flow.md, and validate reporting a flow that changed since its version was packed (#234)."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kinenix.engine.flow_content import (
    PACKED_FILE,
    bundle_files,
    changed_since_packed,
    content_files,
    content_hash,
    read_packed,
    record_packed,
    version_problem,
)
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import flow_to_markdown, load_flow, markdown_to_flow
from kinenix.engine.validation import packed_issues, validate_flow

FLOW = """# Versioned
> Version: 1.3.0

## Steps

### 1. Say Hello (`logic.set_variable`)
- **name:** greeting
- **value:** Hello
"""

SHARED_CALL = """
### 2. Send (`flow.call`)
- **flow:** @shared/notify.md
"""

SHARED = """# Notify

## Steps

### 1. Done (`logic.set_variable`)
- **name:** sent
- **value:** yes
"""


def make_bundle(root: Path, flow_text: str = FLOW) -> Path:
    bundle = root / "flows" / "versioned"
    (bundle / "config").mkdir(parents=True)
    (bundle / "flow.md").write_text(flow_text, encoding="utf-8")
    (bundle / "config" / "config.json").write_text('{"site": "https://test.example"}', encoding="utf-8")
    return bundle


def pack(bundle: Path) -> None:
    """What kinenix pack records after building (#235)."""
    flow = load_flow(bundle / "flow.md")
    record_packed(bundle, flow.version, content_files(flow, bundle))


# Parsing

def test_version_is_read_from_flow_md():
    assert markdown_to_flow(FLOW).version == "1.3.0"


def test_flow_without_version_has_none_and_exports_without_one():
    flow = markdown_to_flow(FLOW.replace("> Version: 1.3.0\n", ""))
    assert flow.version is None
    assert "> Version:" not in flow_to_markdown(flow)
    assert "> Version: 1.3.0" in flow_to_markdown(markdown_to_flow(FLOW))


@pytest.mark.parametrize("version", ["1.3.0", "0.1.0", "2.0.0a1", "1.3.0b2", "1.3.0rc1", "10.20.30"])
def test_accepted_versions(version):
    assert version_problem(version) is None


@pytest.mark.parametrize("version", ["1.3", "1", "v1.3.0", "1.3.0.1", "1.3.0.dev1", "latest", "1.3.0-beta"])
def test_versions_validate_reports(version):
    assert version_problem(version)
    issues = validate_flow(markdown_to_flow(FLOW.replace("1.3.0", version)))
    assert any("> Version:" in issue for issue in issues)


def test_run_log_records_flow_version(tmp_path):
    bundle = make_bundle(tmp_path)
    interpreter = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs"))
    ctx = interpreter.run_flow(load_flow(bundle / "flow.md"), initial_vars={"__flow_dir__": str(bundle)})
    assert ctx.flow_version == "1.3.0"
    log = json.loads(next((tmp_path / "logs").rglob("*.json")).read_text(encoding="utf-8"))
    assert log["flow_version"] == "1.3.0"


# Content of a version

def test_left_out_files_are_not_content(tmp_path):
    bundle = make_bundle(tmp_path)
    for rel in (".env", "config/local.json", "output/result.csv", "logs/run.json", "tests/check.md",
                ".git/HEAD", "assets/__pycache__/x.pyc", "notes/draft.txt", "assets/big.tmp"):
        (bundle / rel).parent.mkdir(parents=True, exist_ok=True)
        (bundle / rel).write_text("x", encoding="utf-8")
    (bundle / "assets" / "logo.png").write_bytes(b"\x89PNG\0data")
    (bundle / ".kinenixignore").write_text("# drafts\nnotes/\n*.tmp\n", encoding="utf-8")
    assert sorted(bundle_files(bundle)) == ["assets/logo.png", "config/config.json", "flow.md"]


def test_line_ends_do_not_change_the_content(tmp_path):
    lf = make_bundle(tmp_path / "lf")
    crlf = make_bundle(tmp_path / "crlf")
    (crlf / "flow.md").write_bytes(FLOW.replace("\n", "\r\n").encode("utf-8"))
    flow = load_flow(lf / "flow.md")
    assert content_hash(content_files(flow, lf)) == content_hash(content_files(flow, crlf))


def test_shared_subflows_are_content(tmp_path):
    bundle = make_bundle(tmp_path, FLOW + SHARED_CALL)
    (tmp_path / "flows" / "@shared").mkdir()
    (tmp_path / "flows" / "@shared" / "notify.md").write_text(SHARED, encoding="utf-8")
    files = content_files(load_flow(bundle / "flow.md"), bundle)
    assert "@shared/notify.md" in files


# Changed since packed

def test_no_record_means_no_issue(tmp_path):
    bundle = make_bundle(tmp_path)
    assert read_packed(bundle) == {}
    assert packed_issues(load_flow(bundle / "flow.md"), bundle) == []


def test_unchanged_flow_has_no_issue(tmp_path):
    bundle = make_bundle(tmp_path)
    pack(bundle)
    (bundle / "config" / "local.json").write_text('{"site": "https://prod.example"}', encoding="utf-8")
    (bundle / "output").mkdir()
    (bundle / "output" / "result.csv").write_text("a,b", encoding="utf-8")
    assert packed_issues(load_flow(bundle / "flow.md"), bundle) == []


def test_changed_flow_with_same_version_is_reported_with_its_files(tmp_path):
    bundle = make_bundle(tmp_path)
    pack(bundle)
    (bundle / "config" / "config.json").write_text('{"site": "https://other.example"}', encoding="utf-8")
    (bundle / "assets").mkdir()
    (bundle / "assets" / "new.txt").write_text("new", encoding="utf-8")
    issues = packed_issues(load_flow(bundle / "flow.md"), bundle)
    assert len(issues) == 1
    assert "version 1.3.0 was packed" in issues[0] and "raise `> Version:`" in issues[0]
    assert "config/config.json changed" in issues[0] and "assets/new.txt added" in issues[0]


def test_raising_the_version_clears_the_issue(tmp_path):
    bundle = make_bundle(tmp_path)
    pack(bundle)
    text = FLOW.replace("1.3.0", "1.3.1").replace("Hello", "Hi")
    (bundle / "flow.md").write_text(text, encoding="utf-8")
    assert packed_issues(load_flow(bundle / "flow.md"), bundle) == []
    pack(bundle)
    assert list(read_packed(bundle)) == ["1.3.0", "1.3.1"]


def test_changed_shared_subflow_is_reported(tmp_path):
    bundle = make_bundle(tmp_path, FLOW + SHARED_CALL)
    shared = tmp_path / "flows" / "@shared" / "notify.md"
    shared.parent.mkdir()
    shared.write_text(SHARED, encoding="utf-8")
    pack(bundle)
    shared.write_text(SHARED.replace("yes", "no"), encoding="utf-8")
    issues = packed_issues(load_flow(bundle / "flow.md"), bundle)
    assert issues and "@shared/notify.md changed" in issues[0]


def test_flow_without_version_is_not_compared(tmp_path):
    bundle = make_bundle(tmp_path)
    pack(bundle)
    (bundle / "flow.md").write_text(FLOW.replace("> Version: 1.3.0\n", ""), encoding="utf-8")
    flow = load_flow(bundle / "flow.md")
    assert changed_since_packed(flow, bundle) is None


def test_unreadable_record_is_reported(tmp_path):
    bundle = make_bundle(tmp_path)
    (bundle / PACKED_FILE).write_text("{oops", encoding="utf-8")
    issues = packed_issues(load_flow(bundle / "flow.md"), bundle)
    assert issues and PACKED_FILE in issues[0]


def _cli(args, tmp_path):
    env = {**os.environ, "KINENIX_SETTINGS_FILE": str(tmp_path / "kinenix.env"), "KINENIX_HUB_URL": "",
           "KINENIX_NO_UPDATE_CHECK": "1", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, "-m", "kinenix.cli", *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", timeout=120)


def test_cli_validate_shows_the_version_and_reports_a_changed_flow(tmp_path):
    bundle = make_bundle(tmp_path)
    result = _cli(["validate", str(bundle)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert "version 1.3.0" in result.stdout
    pack(bundle)
    (bundle / "flow.md").write_text(FLOW.replace("Hello", "Hi"), encoding="utf-8")
    result = _cli(["validate", str(bundle)], tmp_path)
    assert result.returncode == 4
    assert "flow.md changed" in result.stderr
