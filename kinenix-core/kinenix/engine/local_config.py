"""config/local.json: the values of a flow that differ per machine (docs/project_bundles.md, Machine settings).

It is merged over config/config.json key by key, the way `kinenix run --config` merges, and read by every run
of every flow, so a change takes effect at the next run. A package (.kinx) never carries it, and an update
of a deployed flow keeps it (docs/design/flow-deploy.md, section 7). Secrets still belong in .env.
"""
import json
from pathlib import Path
from typing import Any, Dict, Optional

LOCAL_CONFIG = Path("config") / "local.json"


class LocalConfigError(ValueError):
    """config/local.json exists but cannot be used; the run stops instead of using the shared values."""


def local_config_path(flow_dir: Path) -> Path:
    return Path(flow_dir) / LOCAL_CONFIG


def read_local_config(flow_dir: Path) -> Optional[Dict[str, Any]]:
    """The settings of config/local.json, None when the file does not exist.

    A file that exists but is not a JSON object raises LocalConfigError: running with the shared values
    instead could reach the wrong site or folder, so the run must not go on silently.
    """
    path = local_config_path(flow_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise LocalConfigError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise LocalConfigError(f"{path} must hold a JSON object of settings, like config/config.json.")
    return data
