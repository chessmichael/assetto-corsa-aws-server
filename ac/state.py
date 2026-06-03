"""Local, on-disk state for the ac CLI.

Stored at <project-root>/.ac/state.json (gitignored). Holds the detected AC
install path and the terraform outputs (bucket, instance id, region, IP) so the
other commands don't have to re-discover them every run.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

STATE_DIR = ".ac"
STATE_FILE = "state.json"


def find_project_root(start: Optional[Path] = None) -> Path:
    """Walk upward from `start` (default cwd) until we find the repo root.

    The root is the directory that contains the `terraform/` folder (or, failing
    that, a pyproject.toml). Falls back to cwd.
    """
    start = (start or Path.cwd()).resolve()
    for d in [start, *start.parents]:
        if (d / "terraform").is_dir() or (d / "pyproject.toml").is_file():
            return d
    return start


def _state_path(root: Optional[Path] = None) -> Path:
    root = root or find_project_root()
    return root / STATE_DIR / STATE_FILE


def load_state(root: Optional[Path] = None) -> Dict[str, Any]:
    p = _state_path(root)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_state(state: Dict[str, Any], root: Optional[Path] = None) -> Path:
    p = _state_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


# --- convenience accessors -------------------------------------------------

def require(state: Dict[str, Any], key: str) -> Any:
    """Fetch a terraform output, with a friendly error if `ac init` hasn't run."""
    tf = state.get("terraform") or {}
    if key not in tf:
        raise SystemExit(
            f"Missing '{key}'. Run `ac init` first (after `terraform apply`)."
        )
    return tf[key]


def ac_install(state: Dict[str, Any]) -> Path:
    p = state.get("ac_install")
    if not p:
        raise SystemExit("AC install path unknown. Run `ac init` first.")
    return Path(p)
