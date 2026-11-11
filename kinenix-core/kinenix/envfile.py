"""Reading KEY=VALUE files: a flow bundle's `.env` and the settings files in ~/.kinenix.

One parser for all of them, so `export NAME=value`, quotes, and comments mean the same everywhere (#171).
"""
from pathlib import Path
from typing import Dict, Optional, Tuple

_QUOTES = ("'", '"')


def parse_line(line: str, inline_comments: bool = True) -> Optional[Tuple[str, str]]:
    """
    (key, value) of one line, or None for an empty line, a comment, or a line without `=`.

    - `export NAME=value` is read as `NAME=value`, as a shell would.
    - A value in matching quotes is the text between them, `#` included; anything after the closing quote is ignored.
    - With `inline_comments`, `NAME=value  # note` gives `value`: a `#` after a space or tab starts a comment.
      `#` without a space before it stays part of the value, as in `PASSWORD=abc#123`.
    """
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export") and line[6:7] in (" ", "\t"):
        line = line[6:].lstrip()
    key, value = line.split("=", 1)
    key = key.strip()
    if not key:
        return None
    value = value.strip()
    if value[:1] in _QUOTES:
        end = value.find(value[0], 1)
        if end != -1:
            return key, value[1:end]
    if inline_comments:
        for marker in (" #", "\t#"):
            cut = value.find(marker)
            if cut != -1:
                value = value[:cut]
        value = value.rstrip()
    return key, value


def read_env_file(path: Path, inline_comments: bool = True) -> Dict[str, str]:
    """Every KEY=VALUE pair of a file, in order; a later line wins. An empty dict when the file does not exist."""
    values: Dict[str, str] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            pair = parse_line(line, inline_comments)
            if pair:
                values[pair[0]] = pair[1]
    return values
