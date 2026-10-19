"""React project detection and isolated production builds."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def detect_project(project_dir: Path) -> tuple[str, str, str]:
    package_path = project_dir / "package.json"
    if not package_path.exists():
        raise RuntimeError("package.json is missing. Run the CLI from a React project.")
    try:
        package: dict[str, Any] = json.loads(package_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"package.json is invalid: {exc}") from exc
    dependencies = {**package.get("dependencies", {}), **package.get("devDependencies", {})}
    if "vite" in dependencies or (project_dir / "vite.config.ts").exists() or (project_dir / "vite.config.js").exists():
        framework, default_output = "Vite", "dist"
    elif "react-scripts" in dependencies:
        framework, default_output = "Create React App", "build"
    else:
        raise RuntimeError("Could not identify CRA or Vite. Add Vite or react-scripts to package.json.")
    scripts = package.get("scripts", {})
    if "build" not in scripts:
        raise RuntimeError("package.json has no 'build' script.")
    if (project_dir / "package-lock.json").exists():
        install = "npm ci"
    elif (project_dir / "yarn.lock").exists():
        install = "yarn install --frozen-lockfile"
    elif (project_dir / "pnpm-lock.yaml").exists():
        install = "corepack enable && pnpm install --frozen-lockfile"
    else:
        install = "npm install"
    return framework, install, default_output


def build(project_dir: Path, config: dict[str, Any]) -> tuple[Path, str]:
    framework, install, default_output = detect_project(project_dir)
    project = config.get("project", {})
    build_command = project.get("build_command") or "npm run build"
    output_dir = project.get("output_dir") or default_output
    output_path = (project_dir / output_dir).resolve()
    try:
        output_path.relative_to(project_dir.resolve())
    except ValueError as exc:
        raise RuntimeError("The configured output directory must stay inside the project.") from exc

    if config.get("build", {}).get("use_docker", True):
        if not shutil.which("docker"):
            raise RuntimeError("Docker was not found. Install Docker Desktop or disable Docker in deploy-tool.json.")
        image = config.get("build", {}).get("docker_image", "node:20-alpine")
        shell_command = f"{install} && {build_command}"
        command = [
            "docker", "run", "--rm", "--mount", "type=volume,source=deploy-tool-npm-cache,target=/root/.npm",
            "-v", f"{project_dir.resolve().as_posix()}:/workspace",
            "-w", "/workspace", image, "sh", "-lc", shell_command,
        ]
    else:
        package_manager = "yarn" if install.startswith("yarn") else "npm"
        if not shutil.which(package_manager):
            raise RuntimeError(f"{package_manager} was not found. Install Node.js and the package manager.")
        print(f"Installing dependencies with: {install}")
        install_result = subprocess.run(install, cwd=project_dir, shell=True, check=False)
        if install_result.returncode:
            raise RuntimeError(f"Dependency installation failed with exit code {install_result.returncode}.")
        command = ["cmd", "/c", build_command] if __import__("os").name == "nt" else ["sh", "-lc", build_command]
    print(f"Detected {framework}. Building with {command[0]}...")
    result = subprocess.run(command, cwd=project_dir, check=False)
    if result.returncode:
        raise RuntimeError(f"Build failed with exit code {result.returncode}. Review the build output above.")
    if not output_path.is_dir():
        raise RuntimeError(f"Build completed, but output folder '{output_dir}' was not found.")
    return output_path, framework
