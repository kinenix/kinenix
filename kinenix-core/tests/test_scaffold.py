"""`kinenix init` and the example bundles shipped in the package."""
import csv
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from kinenix import scaffold
from kinenix.engine.interpreter import FlowInterpreter
from kinenix.engine.logger import ExecutionLogger
from kinenix.engine.markdown import load_flow, markdown_to_flow
from kinenix.engine.validation import validate_flow

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_examples_are_listed_with_the_default_first():
    examples = scaffold.available_examples()
    names = [name for name, _, _ in examples]
    assert names[0] == scaffold.DEFAULT_EXAMPLE == "hello"
    assert {"hello", "bot_fx_rate", "quote_requests"} <= set(names)
    assert "rpachallenge" not in names  # moved to kinenix/examples: it needs a third-party website
    needs_browser = {name: nb for name, _, nb in examples}
    assert needs_browser["hello"] is False
    assert needs_browser["bot_fx_rate"] is True and needs_browser["quote_requests"] is True
    assert all(description for _, description, _ in examples)


def test_hello_project_is_created_and_runs(tmp_path):
    project = scaffold.create_project(tmp_path / "my-bot")
    assert sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()) == [
        "README.md", "config/config.json", "flow.md", "requirements.md", "subflows/make_greeting.md",
    ]

    flow = load_flow(project / "flow.md")
    ctx = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs")).run_flow(
        flow, initial_vars={"__flow_dir__": str(project)}
    )
    assert not ctx.has_error
    # csv.write adds a byte order mark so Excel shows Thai text correctly
    with open(project / "output" / "greetings.csv", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    assert rows[0] == {"Name": "Somchai", "Greeting": "Hello, Somchai!"}
    assert len(rows) == 3


def test_empty_names_stop_with_a_business_error(tmp_path):
    project = scaffold.create_project(tmp_path / "empty")
    (project / "config" / "config.json").write_text('{"names": [], "greeting": "Hi", "output_path": "./out.csv"}',
                                                    encoding="utf-8")
    ctx = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs")).run_flow(
        load_flow(project / "flow.md"), initial_vars={"__flow_dir__": str(project)}
    )
    assert ctx.has_error
    assert ctx.failure_details.error_type == "Business"
    assert not (project / "out.csv").exists()


def test_existing_folder_rules(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert scaffold.create_project(empty, "bot_fx_rate") == empty.resolve()  # an empty folder is fine

    used = tmp_path / "used"
    used.mkdir()
    (used / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(FileExistsError):
        scaffold.create_project(used)
    assert (used / "notes.txt").read_text(encoding="utf-8") == "keep me"

    with pytest.raises(ValueError, match="Available: hello"):
        scaffold.create_project(tmp_path / "x", "nope")


def test_every_example_creates_a_valid_project(tmp_path, monkeypatch):
    # Examples describe the version being developed, which their `> Requires:` may name
    from kinenix.engine import requires
    monkeypatch.setattr(requires, "__version__", "999.0")
    for name, _, _ in scaffold.available_examples():
        project = scaffold.create_project(tmp_path / name, name)
        assert validate_flow(load_flow(project / "flow.md")) == [], name
        assert not (project / "flow.json").exists()
    assert not list(tmp_path.rglob("output/*.*"))  # outputs are not shipped


def test_packaged_examples_match_flows_examples():
    """The package copies must equal flows/examples (run .github/scripts/sync_examples.py after editing)."""
    sync = runpy.run_path(str(REPO_ROOT / ".github" / "scripts" / "sync_examples.py"))
    assert sync["problems"]() == []


@pytest.mark.parametrize("title, folder", [
    ("Get stock data", "get_stock_data"),
    ("ดึงราคาหุ้น SET50", "ดึงราคาหุ้น_set50"),          # Thai vowels and tone marks stay with their letters
    ("  Daily FX - report (v2)! ", "daily_fx_report_v2"),
])
def test_project_folder_name(title, folder):
    assert scaffold.project_folder_name(title) == folder


def test_project_folder_name_needs_letters():
    with pytest.raises(ValueError, match="letters or digits"):
        scaffold.project_folder_name("!!!")


def test_new_project_has_everything_for_the_requirements_to_flow_workflow(tmp_path):
    project = scaffold.create_new_project("Get stock data", tmp_path / "get_stock_data")
    files = sorted(p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file())
    assert files == [".env.example", ".gitignore", "AGENTS.md", "CLAUDE.md", "README.md",
                     "config/config.json", "flow.md", "requirements.md"]

    for name in ("requirements.md", "flow.md", "AGENTS.md", "README.md"):
        text = (project / name).read_text(encoding="utf-8")
        assert "Get stock data" in text, name
        assert "{{title}}" not in text, name
    assert (project / "CLAUDE.md").read_text(encoding="utf-8").strip() == "@AGENTS.md"
    assert ".env" in (project / ".gitignore").read_text(encoding="utf-8").split()
    assert "kinenix validate" in (project / "AGENTS.md").read_text(encoding="utf-8")

    flow = load_flow(project / "flow.md")
    assert flow.name == "Get stock data"
    assert validate_flow(flow) == []
    ctx = FlowInterpreter(logger=ExecutionLogger(log_dir=tmp_path / "logs")).run_flow(
        flow, initial_vars={"__flow_dir__": str(project)}
    )
    assert not ctx.has_error


def test_new_project_uses_the_folder_from_the_name(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = scaffold.create_new_project("Daily FX report")
    assert project == (tmp_path / "daily_fx_report").resolve()
    with pytest.raises(FileExistsError):
        scaffold.create_new_project("Daily FX report")


def test_packaged_example_files_are_not_git_ignored():
    """A file that exists locally but is ignored by git would pass locally and be missing from CI and the wheel."""
    import shutil
    if not shutil.which("git"):
        pytest.skip("git is not available")
    files = [str(p.relative_to(REPO_ROOT)) for folder in (scaffold.EXAMPLES_DIR, scaffold.NEW_PROJECT_TEMPLATE)
             for p in folder.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    result = subprocess.run(["git", "check-ignore", "--no-index", *files], cwd=REPO_ROOT,
                            capture_output=True, text=True)
    assert result.stdout.strip() == "", f"Ignored by .gitignore: {result.stdout.split()}"


def test_packaged_examples_are_not_discovered_as_runnable_flows():
    from kinenix.cli import discover_flows

    for path, _ in discover_flows().values():
        assert scaffold.EXAMPLES_DIR not in path.resolve().parents
        assert scaffold.NEW_PROJECT_TEMPLATE not in path.resolve().parents


def _kinenix_in(tmp_path):
    """Run the CLI with the flows folder set to tmp_path, never the real ~/kinenix-flows."""
    import os
    env = {**os.environ, "KINENIX_FLOWS_DIR": str(tmp_path)}

    def kinenix(*args):
        return subprocess.run([sys.executable, "-m", "kinenix.cli", *args], cwd=tmp_path, env=env,
                              capture_output=True, text=True, timeout=120)
    return kinenix


def test_init_command(tmp_path):
    kinenix = _kinenix_in(tmp_path)

    listing = kinenix("init", "--list")
    assert listing.returncode == 0 and "hello" in listing.stdout and "needs a browser" in listing.stdout

    created = kinenix("init", "fx", "--example", "bot_fx_rate")
    assert created.returncode == 0
    assert "kinenix install-browsers" in created.stdout and "kinenix run fx" in created.stdout
    assert (tmp_path / "fx" / "flow.md").is_file()

    again = kinenix("init", "fx", "--example", "hello")
    assert again.returncode == 2 and "not empty" in again.stderr

    # With --example the folder name is used as typed, so the documented `init my-bot` then `run my-bot` works
    assert kinenix("init", "my-bot", "--example", "hello").returncode == 0
    assert (tmp_path / "my-bot" / "flow.md").is_file()
    run = kinenix("run", "my-bot")
    assert run.returncode == 0, run.stderr
    assert "Hello, Somchai!" in (tmp_path / "my-bot" / "output" / "greetings.csv").read_text(encoding="utf-8")

    new = kinenix("init", "Get stock data")
    assert new.returncode == 0 and "requirements.md" in new.stdout and "kinenix validate get_stock_data" in new.stdout
    assert (tmp_path / "get_stock_data" / "requirements.md").is_file()

    nameless = kinenix("init")
    assert nameless.returncode == 2 and 'kinenix init "Get stock data"' in nameless.stderr


def test_actions_command(tmp_path):
    kinenix = _kinenix_in(tmp_path)

    every = kinenix("actions")
    assert every.returncode == 0
    click = next(line for line in every.stdout.splitlines() if line.strip().startswith("web.click "))
    assert "wait_for_response" in click and "selector" in click
    assert "on_error" in every.stdout

    web = kinenix("actions", "web")
    assert "web.get_table" in web.stdout and "csv.write" not in web.stdout
    assert kinenix("actions", "nothing").returncode == 7


def test_list_names_a_flow_by_its_folder_also_from_inside_it(tmp_path, monkeypatch):
    # #108: run inside a bundle, the flow was listed as "."; flat *_flow.md files are no longer flows
    from kinenix.cli import discover_flows
    bundle = tmp_path / "flows" / "tiph_test"
    bundle.mkdir(parents=True)
    flow = "# {}\n\n## Steps\n\n### 1. A (`logic.delay`)\n- **seconds:** 0\n"
    (bundle / "flow.md").write_text(flow.format("TIPH Test"), encoding="utf-8")
    (tmp_path / "flows" / "old_flow.md").write_text(flow.format("Old"), encoding="utf-8")
    monkeypatch.setenv("KINENIX_FLOWS_DIR", str(tmp_path / "flows"))
    monkeypatch.chdir(bundle)
    flows = discover_flows()
    assert "." not in flows and "old" not in flows
    assert flows["tiph_test"][0] == bundle / "flow.md"


def test_every_example_has_requirements_with_the_template_sections():
    # Each example shows the requirements it does, in the sections a new project's requirements.md has
    import re
    template = (scaffold.NEW_PROJECT_TEMPLATE / "requirements.md").read_text(encoding="utf-8")
    sections = re.findall(r"^## (.+)$", template, re.M)
    examples = Path(__file__).resolve().parents[2] / "flows" / "examples"
    bundles = sorted(p for p in examples.iterdir() if (p / "flow.md").is_file())
    assert bundles
    for bundle in bundles:
        text = (bundle / "requirements.md").read_text(encoding="utf-8")
        assert re.findall(r"^## (.+)$", text, re.M) == sections, bundle.name
        assert "<" not in re.sub(r"`[^`]*`", "", text), f"{bundle.name}: a template hint was left in"
        assert "requirements.md" in (bundle / "README.md").read_text(encoding="utf-8"), bundle.name


def test_a_new_project_names_the_kinenix_it_was_made_with(tmp_path):
    """Adding ## Finally, expressions, or next_item does not make kinenix validate ask for > Requires: (#196)."""
    from kinenix import __version__
    project = scaffold.create_new_project("Get stock data", tmp_path / "get_stock_data")
    text = (project / "flow.md").read_text(encoding="utf-8")
    assert f"> Requires: kinenix>={__version__}" in text and "{{version}}" not in text
    with_finally = text + "\n## Finally\n\n### 2. Done (`logic.set_variable`)\n- **name:** `done`\n- **value:** ${len('ok')}\n"
    assert validate_flow(markdown_to_flow(with_finally)) == []
