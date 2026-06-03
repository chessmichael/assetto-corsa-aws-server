"""Mocked-AWS tests for the S3 content sync and EC2 controls (via moto)."""
from __future__ import annotations

import boto3
from moto import mock_aws

from ac import awsio, cli

BUCKET = "test-content-bucket"


def _state():
    return {"terraform": {"region": "us-east-1",
                          "content_bucket": BUCKET, "instance_id": "i-abc"}}


def _keys(s3):
    resp = s3.list_objects_v2(Bucket=BUCKET)
    return {o["Key"] for o in resp.get("Contents", [])}


def test_sync_is_incremental(ac_install, aws_credentials):
    with mock_aws():
        s3 = boto3.client("s3", "us-east-1")
        s3.create_bucket(Bucket=BUCKET)
        st = _state()

        # first run: both items upload
        assert cli._sync_targets(st, ac_install, ["car_a"], ["track_a"], full=False) == 2
        keys = _keys(s3)
        assert "server/content/cars/car_a/data.acd" in keys
        assert "server/content/tracks/track_a/data/surfaces.ini" in keys
        assert "manifest.json" in keys
        # excluded heavy files never reached S3
        assert "server/content/tracks/track_a/track.kn5" not in keys

        # second run: nothing changed
        assert cli._sync_targets(st, ac_install, ["car_a"], ["track_a"], full=False) == 0

        # change one file: only that item re-syncs
        (ac_install / "content" / "cars" / "car_a" / "data.acd").write_bytes(b"NEW-PHYSICS")
        assert cli._sync_targets(st, ac_install, ["car_a"], ["track_a"], full=False) == 1


def test_sync_skips_missing_content(ac_install, aws_credentials):
    with mock_aws():
        boto3.client("s3", "us-east-1").create_bucket(Bucket=BUCKET)
        # a car id that doesn't exist locally is skipped, not uploaded
        assert cli._sync_targets(_state(), ac_install, ["car_ghost"], [], full=False) == 0


def test_get_put_json(aws_credentials):
    with mock_aws():
        boto3.client("s3", "us-east-1").create_bucket(Bucket=BUCKET)
        assert awsio.get_json("us-east-1", BUCKET, "missing.json") is None
        awsio.put_json("us-east-1", BUCKET, "m.json", {"a": 1})
        assert awsio.get_json("us-east-1", BUCKET, "m.json") == {"a": 1}


def test_ec2_start_stop(aws_credentials):
    with mock_aws():
        ec2 = boto3.client("ec2", "us-east-1")
        r = ec2.run_instances(ImageId="ami-12345678", MinCount=1, MaxCount=1,
                              InstanceType="t3.medium")
        iid = r["Instances"][0]["InstanceId"]
        assert awsio.instance_state("us-east-1", iid) == "running"
        awsio.stop_instance("us-east-1", iid)
        assert awsio.instance_state("us-east-1", iid) in {"stopping", "stopped"}
        awsio.start_instance("us-east-1", iid)
        assert awsio.instance_state("us-east-1", iid) in {"pending", "running"}
