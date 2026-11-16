"""The new-release notice of the CLI (kinenix/update_check.py). No test reaches the network."""
import io
import json
import sys
import time

import pytest
import requests

from kinenix import cli, update_check


class Terminal(io.StringIO):
    def isatty(self):
        return True


class Pipe(io.StringIO):
    def isatty(self):
        return False


def pypi_answer(*versions, yanked=()):
    return {"releases": {v: [{"yanked": v in yanked}] for v in versions}}


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KINENIX_SETTINGS_FILE", str(tmp_path / "kinenix.env"))
    monkeypatch.delenv("KINENIX_NO_UPDATE_CHECK", raising=False)
    monkeypatch.delenv("CI", raising=False)

    def no_network(*args, **kwargs):
        raise AssertionError("the test reached the network")

    monkeypatch.setattr(update_check.requests, "get", no_network)
    return tmp_path


def serve(monkeypatch, data, calls=None):
    def fake_get(url, timeout, headers):
        assert url == update_check.PYPI_URL
        assert timeout <= update_check.TIMEOUT
        if calls is not None:
            calls.append(url)
        return FakeResponse(data)

    monkeypatch.setattr(update_check.requests, "get", fake_get)


def test_versions_sort_with_prereleases_before_the_final_release():
    order = ["1.0.0a1", "1.0.0b2", "1.0.0rc1", "1.0.0", "1.0.1", "1.10.0"]
    keys = [update_check.parse_version(v) for v in order]
    assert keys == sorted(keys)
    assert update_check.parse_version("1.2.0.dev3") is None
    assert update_check.parse_version("1.2.0+local") is None


def test_newer_version():
    assert update_check.newer_version("1.2.0", "1.3.0") == "1.3.0"
    assert update_check.newer_version("1.2.0", "1.2.0") is None
    assert update_check.newer_version("1.3.0", "1.2.0") is None
    assert update_check.newer_version("1.3.0rc1", "1.3.0") == "1.3.0"
    assert update_check.newer_version("1.2.0", None) is None
    assert update_check.newer_version("1.2.0.dev1", "1.3.0") is None


def test_latest_skips_prereleases_unless_asked_and_skips_yanked():
    data = pypi_answer("1.1.0", "1.2.0", "1.3.0rc1", "1.2.1", yanked=("1.2.1",))
    assert update_check.latest_from_pypi(data, include_prereleases=False) == "1.2.0"
    assert update_check.latest_from_pypi(data, include_prereleases=True) == "1.3.0rc1"
    assert update_check.latest_from_pypi({}, include_prereleases=False) is None


def test_should_check_only_for_a_person_at_a_terminal(monkeypatch):
    assert update_check.should_check(["list"], Terminal())
    assert not update_check.should_check(["list"], Pipe())
    assert not update_check.should_check(["hub", "query", "v_runs", "--format", "json"], Terminal())
    assert not update_check.should_check(["hub", "query", "--format=json"], Terminal())
    assert not update_check.should_check(["run", "hello", "--json"], Terminal())
    assert not update_check.should_check(["hub"], Terminal())
    assert not update_check.should_check(["hub", "start"], Terminal())
    assert not update_check.should_check(["orchestrator"], Terminal())
    assert update_check.should_check(["hub", "status"], Terminal())
    monkeypatch.setenv("CI", "true")
    assert not update_check.should_check(["list"], Terminal())


@pytest.mark.parametrize("value, checks", [("1", False), ("true", False), ("0", True), ("", True)])
def test_opt_out_variable(monkeypatch, value, checks):
    monkeypatch.setenv("KINENIX_NO_UPDATE_CHECK", value)
    assert update_check.should_check(["list"], Terminal()) is checks


def test_notice_after_a_check_and_answer_cached(monkeypatch, isolated):
    calls = []
    serve(monkeypatch, pypi_answer("1.2.0", "1.3.0"), calls)
    out = Terminal()
    check = update_check.UpdateCheck("1.2.0")
    check.start()
    check.finish(out)
    assert "A new Kinenix release is available: 1.2.0 -> 1.3.0" in out.getvalue()
    assert "pip install --upgrade" in out.getvalue()
    assert "KINENIX_NO_UPDATE_CHECK=1" in out.getvalue()
    cache = json.loads((isolated / "update_check.json").read_text(encoding="utf-8"))
    assert cache["latest"] == "1.3.0"

    # The next command within a day reads the saved answer without asking PyPI
    again = Terminal()
    second = update_check.UpdateCheck("1.2.0")
    second.start()
    second.finish(again)
    assert len(calls) == 1
    assert "1.3.0" in again.getvalue()


def test_no_notice_when_up_to_date(monkeypatch):
    serve(monkeypatch, pypi_answer("1.1.0", "1.2.0"))
    out = Terminal()
    check = update_check.UpdateCheck("1.2.0")
    check.start()
    check.finish(out)
    assert out.getvalue() == ""


def test_asks_again_after_a_day(monkeypatch, isolated):
    (isolated / "update_check.json").write_text(json.dumps(
        {"checked_at": time.time() - update_check.CHECK_INTERVAL - 1, "latest": "1.2.0", "prereleases": False}),
        encoding="utf-8")
    serve(monkeypatch, pypi_answer("1.4.0"))
    out = Terminal()
    check = update_check.UpdateCheck("1.2.0")
    check.start()
    check.finish(out)
    assert "1.2.0 -> 1.4.0" in out.getvalue()


def test_pypi_not_reachable_is_silent(monkeypatch, isolated):
    def offline(*args, **kwargs):
        raise requests.ConnectionError("no network")

    monkeypatch.setattr(update_check.requests, "get", offline)
    out = Terminal()
    check = update_check.UpdateCheck("1.2.0")
    check.start()
    check.finish(out)
    assert out.getvalue() == ""
    assert not (isolated / "update_check.json").exists()


def test_broken_cache_is_ignored(monkeypatch, isolated):
    (isolated / "update_check.json").write_text("not json", encoding="utf-8")
    serve(monkeypatch, pypi_answer("1.3.0"))
    out = Terminal()
    check = update_check.UpdateCheck("1.2.0")
    check.start()
    check.finish(out)
    assert "1.3.0" in out.getvalue()


def test_prerelease_user_sees_the_next_prerelease(monkeypatch):
    serve(monkeypatch, pypi_answer("1.2.0", "1.3.0rc1", "1.3.0rc2"))
    out = Terminal()
    check = update_check.UpdateCheck("1.3.0rc1")
    check.start()
    check.finish(out)
    assert "1.3.0rc1 -> 1.3.0rc2" in out.getvalue()


def test_cli_prints_the_notice_after_the_command(monkeypatch, capsys):
    serve(monkeypatch, pypi_answer("99.0.0"))
    monkeypatch.setattr(sys, "argv", ["kinenix", "flows-dir"])
    monkeypatch.setattr(update_check, "should_check", lambda argv, stream=None: True)
    out = Terminal()
    original_finish = update_check.UpdateCheck.finish
    monkeypatch.setattr(update_check.UpdateCheck, "finish", lambda self, stream=None: original_finish(self, out))
    try:
        cli.main()
    except SystemExit:
        pass
    assert "-> 99.0.0" in out.getvalue()


def test_cli_skips_the_check_when_not_at_a_terminal(monkeypatch):
    # isolated() makes any request fail the test; under pytest stderr is not a terminal
    monkeypatch.setattr(sys, "argv", ["kinenix", "flows-dir"])
    try:
        cli.main()
    except SystemExit:
        pass
