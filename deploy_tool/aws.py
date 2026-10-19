"""AWS S3 deployment, release history, status, and rollback."""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def boto3_session(config: dict[str, Any]):
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 is required. Install the CLI with `pip install -e .`.") from exc
    aws = config.get("aws", {})
    return boto3.Session(profile_name=aws.get("profile") or None, region_name=aws.get("region", "us-east-1"))


def bucket_name(config: dict[str, Any], account_id: str) -> str:
    project = re.sub(r"[^a-z0-9-]+", "-", config["project"]["name"].lower()).strip("-")[:28]
    environment = config.get("environment", "production")
    region = config.get("aws", {}).get("region", "us-east-1")
    return f"{project}-{environment}-{account_id}-{region}"[:63].strip("-")


def provision(project_dir: Path, config: dict[str, Any], bucket: str) -> None:
    template_dir = Path(__file__).parent / "terraform"
    if not (template_dir / "main.tf").exists():
        raise RuntimeError("Terraform configuration is missing from the CLI installation.")
    if not shutil_which("terraform"):
        raise RuntimeError("Terraform was not found. Install Terraform and add it to PATH.")
    terraform_dir = project_dir / ".deploy-tool" / "terraform" / config.get("environment", "production")
    terraform_dir.mkdir(parents=True, exist_ok=True)
    for template in template_dir.glob("*.tf"):
        shutil.copy2(template, terraform_dir / template.name)
    env = dict(__import__("os").environ)
    profile = config.get("aws", {}).get("profile", "")
    if profile:
        env["AWS_PROFILE"] = profile
    command = ["terraform", "-chdir=" + str(terraform_dir), "init", "-input=false"]
    subprocess.run(command, check=True, env=env)
    apply = ["terraform", "-chdir=" + str(terraform_dir), "apply", "-input=false", "-auto-approve", f"-var=bucket_name={bucket}", f"-var=aws_region={config.get('aws', {}).get('region', 'us-east-1')}"]
    subprocess.run(apply, check=True, cwd=project_dir, env=env)


def shutil_which(program: str) -> bool:
    import shutil
    return shutil.which(program) is not None


def website_url(bucket: str, region: str) -> str:
    return f"http://{bucket}.s3-website-{region}.amazonaws.com"


def _history(s3, bucket: str) -> list[dict[str, Any]]:
    key = "_deploy-tool/history.json"
    try:
        response = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(response["Body"].read().decode("utf-8"))
    except s3.exceptions.NoSuchKey:
        return []
    except Exception as exc:
        if getattr(exc, "response", {}).get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
            return []
        raise


def _put_file(s3, bucket: str, key: str, path: Path) -> None:
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    extra = {"ContentType": content_type}
    if path.suffix == ".html":
        extra["CacheControl"] = "no-cache"
    elif path.suffix in {".js", ".css", ".svg", ".png", ".jpg", ".woff2"}:
        extra["CacheControl"] = "public, max-age=31536000, immutable"
    s3.upload_file(str(path), bucket, key, ExtraArgs=extra)


def _files(directory: Path):
    for path in directory.rglob("*"):
        if path.is_file():
            yield path, path.relative_to(directory).as_posix()


def deploy(project_dir: Path, config: dict[str, Any], output: Path) -> tuple[str, str]:
    session = boto3_session(config)
    account_id = session.client("sts").get_caller_identity()["Account"]
    bucket = bucket_name(config, account_id)
    provision(project_dir, config, bucket)
    s3 = session.client("s3")
    release_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    files = list(_files(output))
    if not files or not any(name == "index.html" for _, name in files):
        raise RuntimeError("Build output must contain index.html to deploy as a static website.")
    print(f"Uploading {len(files)} files to {bucket}...")
    for path, name in files:
        _put_file(s3, bucket, f"_deploy-tool/releases/{release_id}/{name}", path)
    # S3 website hosting serves objects at the bucket root.
    desired = {name for _, name in files}
    stale = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.startswith("_deploy-tool/") and key not in desired:
                stale.append({"Key": key})
    for start in range(0, len(stale), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": stale[start:start + 1000], "Quiet": True})
    for path, name in files:
        _put_file(s3, bucket, name, path)
    history = _history(s3, bucket)
    release = {"id": release_id, "created_at": datetime.now(timezone.utc).isoformat(), "file_count": len(files)}
    history.append(release)
    s3.put_object(Bucket=bucket, Key="_deploy-tool/history.json", Body=json.dumps(history, indent=2).encode(), ContentType="application/json", CacheControl="no-cache")
    return bucket, website_url(bucket, config.get("aws", {}).get("region", "us-east-1"))


def status(config: dict[str, Any]) -> None:
    session = boto3_session(config)
    account_id = session.client("sts").get_caller_identity()["Account"]
    bucket = bucket_name(config, account_id)
    history = _history(session.client("s3"), bucket)
    print(f"Environment: {config.get('environment', 'production')}")
    print(f"Bucket:      {bucket}")
    if history:
        latest = history[-1]
        print(f"Deployment:  {latest['id']} ({latest.get('file_count', '?')} files)")
        print(f"Website:     {website_url(bucket, config.get('aws', {}).get('region', 'us-east-1'))}")
    else:
        print("No deployments found yet.")


def rollback(config: dict[str, Any]) -> None:
    session = boto3_session(config)
    account_id = session.client("sts").get_caller_identity()["Account"]
    bucket = bucket_name(config, account_id)
    s3 = session.client("s3")
    history = _history(s3, bucket)
    if len(history) < 2:
        raise RuntimeError("There is no earlier deployment to restore.")
    previous = history[-2]
    prefix = f"_deploy-tool/releases/{previous['id']}/"
    paginator = s3.get_paginator("list_objects_v2")
    archived = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        archived.extend(page.get("Contents", []))
    if not archived:
        raise RuntimeError("The earlier release files could not be found in S3.")

    # Remove files introduced by later releases so the restored site is exact.
    keep = {obj["Key"][len(prefix):] for obj in archived}
    stale = []
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.startswith("_deploy-tool/") and key not in keep:
                stale.append({"Key": key})
    for start in range(0, len(stale), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": stale[start:start + 1000], "Quiet": True})

    restored = 0
    for item in archived:
        key = item["Key"]
        target = key[len(prefix):]
        s3.copy_object(Bucket=bucket, Key=target, CopySource={"Bucket": bucket, "Key": key})
        restored += 1
    history.append({"id": previous["id"], "created_at": datetime.now(timezone.utc).isoformat(), "file_count": restored, "restored_from": history[-1]["id"]})
    s3.put_object(Bucket=bucket, Key="_deploy-tool/history.json", Body=json.dumps(history, indent=2).encode(), ContentType="application/json", CacheControl="no-cache")
    print(f"Restored deployment {previous['id']} to {website_url(bucket, config.get('aws', {}).get('region', 'us-east-1'))}")
