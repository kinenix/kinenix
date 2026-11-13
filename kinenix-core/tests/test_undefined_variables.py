"""#162: kinenix validate reports ${names} that nothing sets. A name close to a defined one is a problem (a
misspelling); any other is a hint, because it may come from --vars."""
import json
import os
import subprocess
import sys

from kinenix.engine.markdown import markdown_to_flow
from kinenix.engine.validation import validate_flow, validate_subflows

ISSUE_FLOW = """# Send Report

## Variables
- `customer_email`: a@b.co

## Steps

### 1. Build Subject (`logic.set_variable`)
- **name:** `to`
- **value:** ${custmer_email}
"""


def _check(markdown, bundle):
    bundle.mkdir(exist_ok=True)
    hints = []
    problems = [p for p in validate_flow(markdown_to_flow(markdown), bundle, hints)
                if "older workers" not in p and "requires kinenix" not in p]
    return problems, hints


def test_a_misspelled_variable_is_a_problem_with_the_name_it_meant(tmp_path):
    problems, hints = _check(ISSUE_FLOW, tmp_path)
    assert problems == ["Step 'step_1' (Build Subject), line 8: ${custmer_email} is never set, so it is empty when "
                        "the step runs. Did you mean 'customer_email'?"]
    assert hints == []


def test_a_name_like_no_other_is_a_hint_until_it_is_declared(tmp_path):
    flow = ISSUE_FLOW.replace("${custmer_email}", "${report_date}")
    problems, hints = _check(flow, tmp_path)
    assert problems == []
    assert len(hints) == 1 and "${report_date} is not set anywhere" in hints[0] and "--vars" in hints[0]
    assert "- `report_date`:" in hints[0]
    declared = flow.replace("## Steps", "- `report_date`:\n\n## Steps")
    assert _check(declared, tmp_path) == ([], [])


def test_without_the_bundle_folder_names_are_not_checked():
    # Config keys are variables too, so without the folder the check would guess
    assert validate_flow(markdown_to_flow(ISSUE_FLOW)) == []


SETS_EVERYTHING = """# Everything Set
> Requires: kinenix>=1.1.0

## Variables
- `rows`: []

## Steps

### 1. Read (`csv.read`)
- **file_path:** ${input_file}
- **output_var:** `orders`

### 2. Each Order (`logic.loop`)
- **items:** ${orders}
- **item_var:** order
- **Sub-steps:**
  - Total (`logic.set_variable`):
    - **name:** total
    - **value:** ${round(order.price * order.qty, 2)}
  - Keep (`logic.append`):
    - **target:** kept
    - **item:** {"n": "${order_index}", "name": "${order.First Name}", "total": "${total}"}

### 3. Pages (`logic.loop`)
- **times:** 2
- **Sub-steps:**
  - Wait (`logic.delay`):
    - **seconds:** ${item}

### 4. Call (`flow.call`)
- **flow:** ./subflows/missing.md
- **outputs:** {"answer": "reply"}

### 5. Report (`file.write_text`)
- **path:** ./output/${run.id}/${trigger_file_name}.txt
- **content:** ${len(kept)} ${reply} ${website} ${config.input_file} ${env.HOME} ${default(rows, 'none')} ${'quoted'}
- **condition:** `${len(kept)} > 0`

## On Error

### 1. Note (`file.write_text`)
- **path:** ./output/error.txt
- **content:** ${error.message}
"""


def test_names_set_by_steps_config_loops_and_kinenix_are_known(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({"input_file": "a.csv", "target_url": "x"}))
    assert _check(SETS_EVERYTHING, tmp_path) == ([], [])


def test_conditions_and_error_messages_are_checked_and_each_name_is_reported_once(tmp_path):
    flow = """# Checks

## Variables
- `status`: ok

## Steps

### 1. One (`logic.delay`)
- **seconds:** 0
- **condition:** `${stauts} == ok`

### 2. Two (`logic.delay`)
- **seconds:** ${stauts}
- **on_error:** continue
- **error_message:** Failed: ${eror.message}
"""
    problems, hints = _check(flow, tmp_path)
    assert len(problems) == 2
    assert "Step 'step_1' (One)" in problems[0] and "${stauts}" in problems[0]
    assert "Did you mean 'status'?" in problems[0] and "also used in 1 other step(s)" in problems[0]
    assert "${eror}" in problems[1] and "Did you mean 'error'?" in problems[1]
    assert hints == []


def test_subflows_are_checked_with_the_bundle_config(tmp_path):
    (tmp_path / "subflows").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.json").write_text(json.dumps({"base_url": "https://x"}))
    (tmp_path / "subflows" / "one.md").write_text("""# One

## Variables
- `req`: {}

## Steps

### 1. Open (`web.open`)
- **url:** ${base_url}/${req.id}/${reqq.page}/${lang}
""", encoding="utf-8")
    flow = markdown_to_flow("""# Main

## Steps

### 1. Call (`flow.call`)
- **flow:** ./subflows/one.md
- **inputs:** {"req": {"id": 1}}
""")
    hints = []
    problems = validate_subflows(flow, tmp_path, hints=hints)
    assert len(problems) == 1 and problems[0].startswith("Subflow './subflows/one.md': ")
    assert "${reqq}" in problems[0] and "Did you mean 'req'?" in problems[0]
    assert len(hints) == 1 and hints[0].startswith("Subflow './subflows/one.md': ") and "${lang}" in hints[0]


def _cli(tmp_path, *args):
    env = {**os.environ, "KINENIX_FLOWS_DIR": str(tmp_path)}
    return subprocess.run([sys.executable, "-m", "kinenix.cli", *args], cwd=tmp_path, env=env,
                          capture_output=True, text=True, encoding="utf-8")


def test_validate_fails_on_a_misspelling_and_passes_with_only_hints(tmp_path):
    (tmp_path / "typo").mkdir()
    (tmp_path / "typo" / "flow.md").write_text(ISSUE_FLOW, encoding="utf-8")
    result = _cli(tmp_path, "validate", "typo")
    assert result.returncode == 4 and "Warning: Step 'step_1'" in result.stderr and "Did you mean" in result.stderr

    (tmp_path / "hint").mkdir()
    (tmp_path / "hint" / "flow.md").write_text(ISSUE_FLOW.replace("custmer_email", "report_date"), encoding="utf-8")
    result = _cli(tmp_path, "validate", "hint")
    assert result.returncode == 0, result.stderr
    assert "Hint: Step 'step_1'" in result.stderr and "problem(s)" not in result.stderr
    assert result.stdout.startswith("OK:")
