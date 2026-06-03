"""Thin wrappers over boto3 (S3 / SSM / EC2) and `terraform output`.

Credentials and region resolution come from the standard AWS chain — the same
config the AWS CLI uses. Nothing here opens an inbound port; every call is an
outbound request to an AWS API.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import boto3
from botocore.exceptions import ClientError


# ---------------------------------------------------------------------------
# Terraform outputs
# ---------------------------------------------------------------------------

def terraform_outputs(project_root: Path) -> Dict[str, object]:
    """Run `terraform output -json` in the project's terraform/ dir."""
    tf_dir = project_root / "terraform"
    try:
        proc = subprocess.run(
            ["terraform", f"-chdir={tf_dir}", "output", "-json"],
            capture_output=True, text=True, check=True,
        )
    except FileNotFoundError:
        raise SystemExit("terraform not found on PATH. Install it, then re-run `ac init`.")
    except subprocess.CalledProcessError as e:
        raise SystemExit(
            "Could not read terraform outputs. Have you run `terraform apply`?\n"
            + (e.stderr or "")
        )
    raw = json.loads(proc.stdout or "{}")
    return {k: v.get("value") for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------

def session(region: str) -> boto3.Session:
    return boto3.Session(region_name=region)


# ---------------------------------------------------------------------------
# S3
# ---------------------------------------------------------------------------

def get_json(region: str, bucket: str, key: str) -> Optional[dict]:
    s3 = session(region).client("s3")
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return json.loads(obj["Body"].read())
    except s3.exceptions.NoSuchKey:
        return None
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "NoSuchBucket", "404"):
            return None
        raise


def put_json(region: str, bucket: str, key: str, obj: dict) -> None:
    s3 = session(region).client("s3")
    s3.put_object(Bucket=bucket, Key=key,
                  Body=json.dumps(obj, indent=2).encode(),
                  ContentType="application/json")


def put_text(region: str, bucket: str, key: str, text: str) -> None:
    s3 = session(region).client("s3")
    s3.put_object(Bucket=bucket, Key=key, Body=text.encode("utf-8"))


def upload_files(region: str, bucket: str, items: List[Tuple[Path, str]],
                 progress=None) -> None:
    """Upload (local_path, s3_key) pairs."""
    s3 = session(region).client("s3")
    for i, (local, key) in enumerate(items, 1):
        s3.upload_file(str(local), bucket, key)
        if progress:
            progress(i, len(items), key)


def delete_prefix(region: str, bucket: str, prefix: str) -> int:
    """Delete all objects under a prefix. Returns count removed."""
    s3 = session(region).client("s3")
    paginator = s3.get_paginator("list_objects_v2")
    to_delete: List[dict] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            to_delete.append({"Key": obj["Key"]})
    n = 0
    for i in range(0, len(to_delete), 1000):
        batch = to_delete[i:i + 1000]
        s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
        n += len(batch)
    return n


# ---------------------------------------------------------------------------
# EC2 start/stop
# ---------------------------------------------------------------------------

def instance_state(region: str, instance_id: str) -> str:
    ec2 = session(region).client("ec2")
    r = ec2.describe_instances(InstanceIds=[instance_id])
    return r["Reservations"][0]["Instances"][0]["State"]["Name"]


def start_instance(region: str, instance_id: str) -> None:
    session(region).client("ec2").start_instances(InstanceIds=[instance_id])


def stop_instance(region: str, instance_id: str) -> None:
    session(region).client("ec2").stop_instances(InstanceIds=[instance_id])
