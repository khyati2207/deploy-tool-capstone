"""Project configuration helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CONFIG_NAME = "deploy-tool.json"


def config_path(project_dir: Path) -> Path:
    return project_dir / CONFIG_NAME


def load_config(project_dir: Path) -> dict[str, Any]:
    path = config_path(project_dir)
    if not path.exists():
        raise RuntimeError(f"No {CONFIG_NAME} found. Run `deploy-tool init` first.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{CONFIG_NAME} must contain a JSON object.")
    return data


def save_config(project_dir: Path, config: dict[str, Any]) -> None:
    config_path(project_dir).write_text(
        json.dumps(config, indent=2) + "\n", encoding="utf-8"
    )


def slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    return re.sub(r"-+", "-", value) or "react-site"


def init_project(project_dir: Path) -> Path:
    package_json = project_dir / "package.json"
    if not package_json.exists():
        raise RuntimeError("No package.json found. Run this inside a React project.")
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"package.json is invalid: {exc}") from exc
    name = slug(package.get("name", project_dir.name))
    config = {
        "project": {"name": name, "build_command": "", "output_dir": ""},
        "aws": {"region": "us-east-1", "profile": ""},
        "environment": "production",
        "environments": {"development": {}, "staging": {}, "production": {}},
        "build": {"docker_image": "node:20-alpine", "use_docker": True},
    }
    path = config_path(project_dir)
    if path.exists():
        raise RuntimeError(f"{path.name} already exists; refusing to overwrite it.")
    save_config(project_dir, config)
    return path


def set_environment(project_dir: Path, environment: str) -> None:
    if environment not in {"development", "staging", "production"}:
        raise RuntimeError("Environment must be development, staging, or production.")
    config = load_config(project_dir)
    config["environment"] = environment
    save_config(project_dir, config)
