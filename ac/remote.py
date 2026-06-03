"""Run commands on the instance over AWS Systems Manager (no SSH, no open port).

`ssm send-command` with the AWS-RunShellScript document, then poll
`get_command_invocation` for the result. The interactive session-manager-plugin
is not required for this.
"""
from __future__ import annotations

import time
from typing import List, Tuple

from . import awsio

_TERMINAL = {"Success", "Cancelled", "TimedOut", "Failed"}


def is_managed(region: str, instance_id: str) -> bool:
    """True if the instance is registered with SSM and online."""
    ssm = awsio.session(region).client("ssm")
    r = ssm.describe_instance_information(
        Filters=[{"Key": "InstanceIds", "Values": [instance_id]}]
    )
    info = r.get("InstanceInformationList", [])
    return bool(info) and info[0].get("PingStatus") == "Online"


def run(region: str, instance_id: str, commands: List[str],
        timeout: int = 180) -> Tuple[str, str, str]:
    """Execute shell commands; return (status, stdout, stderr)."""
    ssm = awsio.session(region).client("ssm")
    resp = ssm.send_command(
        InstanceIds=[instance_id],
        DocumentName="AWS-RunShellScript",
        Parameters={"commands": commands},
        TimeoutSeconds=timeout,
    )
    command_id = resp["Command"]["CommandId"]

    deadline = time.time() + timeout + 30
    while True:
        try:
            inv = ssm.get_command_invocation(
                CommandId=command_id, InstanceId=instance_id
            )
        except ssm.exceptions.InvocationDoesNotExist:
            time.sleep(1)
            if time.time() > deadline:
                return ("TimedOut", "", "invocation never registered")
            continue

        status = inv["Status"]
        if status in _TERMINAL:
            return (status, inv.get("StandardOutputContent", ""),
                    inv.get("StandardErrorContent", ""))
        if time.time() > deadline:
            return ("TimedOut", inv.get("StandardOutputContent", ""),
                    inv.get("StandardErrorContent", ""))
        time.sleep(2)


# --- high-level operations -------------------------------------------------

def update(region: str, instance_id: str) -> Tuple[str, str, str]:
    """Pull latest content/config from S3 and restart the selected backend."""
    return run(region, instance_id, ["sudo /usr/local/bin/ac-update"], timeout=240)


def status(region: str, instance_id: str) -> Tuple[str, str, str]:
    return run(region, instance_id, [
        "echo '== backend =='; cat /opt/ac/server/.backend 2>/dev/null || echo '(none deployed)'",
        "echo '== services =='; systemctl is-active assettoserver acserver 2>/dev/null || true",
        "echo '== listening =='; (ss -lntu | grep -E '9600|8081') || echo '(nothing on game ports yet)'",
    ])


def logs(region: str, instance_id: str, backend: str = "assettoserver",
         lines: int = 200) -> Tuple[str, str, str]:
    unit = "acserver" if backend == "acserver" else "assettoserver"
    return run(region, instance_id,
               [f"journalctl -u {unit} -n {int(lines)} --no-pager"])


def restart(region: str, instance_id: str) -> Tuple[str, str, str]:
    return run(region, instance_id, [
        "B=$(tr -d '[:space:]' < /opt/ac/server/.backend 2>/dev/null || echo assettoserver)",
        "sudo systemctl restart \"$B\" && echo restarted \"$B\"",
    ])
