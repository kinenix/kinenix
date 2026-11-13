"""#151: kinenix validate hints when a loop mixes on_error: next_item with sub-steps that stop the whole loop."""
import os
import subprocess
import sys

from kinenix.engine.markdown import markdown_to_flow
from kinenix.engine.validation import validate_flow

LOOP = """# Quotes
> Requires: kinenix>=0.4.0b1

## Steps

### 1. Quote Each Vehicle (`logic.loop`)
- **items:** []
- **item_var:** car
- **Sub-steps:**
  - Check Row (`flow.fail`):
    - **condition:** `${car.model} is empty`
    - **message:** no model
    - **on_error:** next_item
  - Keep Name (`logic.set_variable`):
    - **name:** model
    - **value:** ${car.model}
  - Open Page (`web.open`):
    - **url:** https://example.com
{extra}  - Choose Brand (`web.choose`):
    - **selector:** #brand
    - **option:** ${car.brand}
  - Choose Model (`web.choose`):
    - **selector:** #model
    - **option:** ${car.model}
"""
CLOSE_POPUP = "  - Close Popup (`web.click`):\n    - **selector:** #x\n    - **optional:** true\n"


def _loop(extra=""):
    return LOOP.replace("{extra}", extra)


def _hints(markdown):
    hints = []
    validate_flow(markdown_to_flow(markdown), hints=hints)
    return hints


def test_a_loop_with_next_item_and_steps_that_stop_it_gets_one_hint():
    assert _hints(_loop()) == [
        "Step 'step_1' (Quote Each Vehicle), line 6: 3 sub-steps that may fail stop the whole loop when they fail "
        "('Open Page' line 17, 'Choose Brand' line 19, 'Choose Model' line 22), while 'Check Row' line 10 uses "
        "on_error: next_item. Add on_error: next_item to the steps that may fail for one item, or write "
        "on_error: fail on those where one failure should stop the run."]


def test_more_than_three_steps_are_counted_and_one_step_reads_in_the_singular():
    extra = "".join(f"  - Type {n} (`web.type`):\n    - **selector:** #f{n}\n    - **text:** x\n" for n in range(2))
    hint = _hints(_loop(extra))[0]
    assert "5 sub-steps" in hint and ", and 2 more)" in hint
    one = _loop().split("  - Choose Brand")[0]
    assert "1 sub-step that may fail stops the whole loop when it fails ('Open Page' line 17)" in _hints(one)[0]


def test_no_hint_when_every_step_that_may_fail_has_a_policy():
    # on_error: fail written out means one failure should stop the run; logic.* steps need no policy
    decided = (_loop().replace("https://example.com\n", "https://example.com\n    - **on_error:** fail\n")
               .replace("${car.brand}\n", "${car.brand}\n    - **on_error:** next_item\n")
               + "    - **on_error:** continue\n")
    assert _hints(decided) == []


def test_optional_counts_as_a_policy():
    hints = _hints(_loop().split("  - Choose Brand")[0] + CLOSE_POPUP)
    assert len(hints) == 1 and "Close Popup" not in hints[0]


def test_no_hint_without_next_item():
    assert _hints(_loop().replace("    - **on_error:** next_item\n", "")) == []


def test_steps_in_a_logic_if_belong_to_the_loop_and_a_nested_loop_is_checked_on_its_own():
    flow = """# Nested

## Steps

### 1. Outer (`logic.loop`)
- **items:** []
- **Sub-steps:**
  - Branch (`logic.if`):
    - **condition:** `${item} == a`
    - **Sub-steps:**
      - Read (`csv.read`):
        - **file_path:** ./a.csv
        - **on_error:** next_item
    - **Else-steps:**
      - Write (`file.write_text`):
        - **path:** ./b.txt
        - **content:** x
  - Inner (`logic.loop`):
    - **items:** []
    - **item_var:** row
    - **Sub-steps:**
      - Click (`web.click`):
        - **selector:** #x
"""
    hints = _hints(flow)
    assert len(hints) == 1
    assert hints[0].startswith("Step 'step_1' (Outer)") and "'Write'" in hints[0] and "Click" not in hints[0]


def test_without_a_hints_list_nothing_changes():
    assert validate_flow(markdown_to_flow(_loop())) == []


def test_validate_prints_the_hint_and_passes(tmp_path):
    (tmp_path / "quotes").mkdir()
    (tmp_path / "quotes" / "flow.md").write_text(_loop(), encoding="utf-8")
    env = {**os.environ, "KINENIX_FLOWS_DIR": str(tmp_path)}
    result = subprocess.run([sys.executable, "-m", "kinenix.cli", "validate", "quotes"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "Hint: Step 'step_1' (Quote Each Vehicle)" in result.stderr and "problem(s)" not in result.stderr
