"""One reader for `.env` and settings files (#171)."""
import pytest

from kinenix.envfile import parse_line, read_env_file


@pytest.mark.parametrize("line, expected", [
    ("NAME=value", ("NAME", "value")),
    ("  NAME = value  ", ("NAME", "value")),
    ("export NAME=value", ("NAME", "value")),
    ("export\tNAME=value", ("NAME", "value")),
    ("exported=yes", ("exported", "yes")),
    ("NAME=two # note", ("NAME", "two")),
    ("NAME=two\t# note", ("NAME", "two")),
    ("PASSWORD=abc#123", ("PASSWORD", "abc#123")),
    ("NAME='quoted # not a comment'", ("NAME", "quoted # not a comment")),
    ('NAME="quoted"  # note', ("NAME", "quoted")),
    ("NAME='it''s'", ("NAME", "it")),
    ("NAME='unclosed", ("NAME", "'unclosed")),
    ("NAME=", ("NAME", "")),
    ("NAME=a=b", ("NAME", "a=b")),
    ("URL=https://example.com/#top", ("URL", "https://example.com/#top")),
    ("", None),
    ("# comment", None),
    ("no equals sign", None),
    ("=value", None),
])
def test_parse_line(line, expected):
    assert parse_line(line) == expected


def test_settings_files_keep_a_space_and_hash_in_a_value():
    assert parse_line(r"KINENIX_FLOWS_DIR=C:\Work #2\flows", inline_comments=False) == \
        ("KINENIX_FLOWS_DIR", r"C:\Work #2\flows")


def test_read_env_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("\ufeff# secrets\nexport EXP_A=one\nEXP_B=two # note\nEXP_A=three\n", encoding="utf-8")
    assert read_env_file(env) == {"EXP_A": "three", "EXP_B": "two"}
    assert read_env_file(tmp_path / "missing.env") == {}


def test_a_flow_reads_export_lines_and_inline_comments_from_its_env(tmp_path, monkeypatch):
    from kinenix.engine.interpreter import FlowInterpreter
    from kinenix.engine.logger import ExecutionLogger
    from kinenix.models.flow import FlowDefinition, Step

    monkeypatch.delenv("KX_EXPORTED", raising=False)
    monkeypatch.delenv("KX_COMMENTED", raising=False)
    (tmp_path / ".env").write_text("export KX_EXPORTED=one\nKX_COMMENTED=two # note\n", encoding="utf-8")
    flow = FlowDefinition(name="Env Check", steps=[Step(
        id="s1", name="Keep Values", action="logic.set_variable", output_var="pair",
        parameters={"name": "pair", "value": "${env.KX_EXPORTED}-${env.KX_COMMENTED}"})])
    ctx = FlowInterpreter(logger=ExecutionLogger(log_dir=None)).run_flow(
        flow, initial_vars={"__flow_dir__": str(tmp_path)})
    assert ctx.get_variable("pair") == "one-two"
