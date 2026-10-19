"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .aws import deploy as aws_deploy, rollback as aws_rollback, status as aws_status
from .build import build
from .config import init_project, load_config, save_config, set_environment


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="deploy-tool", description="Deploy React websites to AWS S3.")
    root.add_argument("--version", action="version", version=f"deploy-tool {__version__}")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Initialize deployment configuration in a React project")
    config = commands.add_parser("config", help="View or update project deployment settings")
    config.add_argument("--environment", choices=["development", "staging", "production"])
    commands.add_parser("deploy", help="Build the React project and publish it to AWS")
    commands.add_parser("status", help="Show the latest deployment")
    commands.add_parser("rollback", help="Restore the previous deployment")
    return root


def main() -> None:
    args = parser().parse_args()
    project_dir = Path.cwd()
    try:
        if args.command == "init":
            path = init_project(project_dir)
            print(f"Created {path.name}. Edit AWS region and build settings before deploying.")
        elif args.command == "config":
            config = load_config(project_dir)
            if args.environment:
                set_environment(project_dir, args.environment)
                print(f"Active environment set to {args.environment}.")
            else:
                print(json.dumps(config, indent=2))
        elif args.command == "deploy":
            config = load_config(project_dir)
            output, framework = build(project_dir, config)
            print(f"Built {framework} into {output.name}.")
            bucket, url = aws_deploy(project_dir, config, output)
            print(f"Deployment complete. Bucket: {bucket}\nWebsite: {url}")
        elif args.command == "status":
            aws_status(load_config(project_dir))
        elif args.command == "rollback":
            aws_rollback(load_config(project_dir))
    except KeyboardInterrupt:
        print("\nDeployment cancelled.", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
