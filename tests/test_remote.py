"""Tests for the SSM remote-control layer, using a fake SSM client (no AWS)."""
from __future__ import annotations

from ac import remote


class FakeSSM:
    class exceptions:
        InvocationDoesNotExist = type("InvocationDoesNotExist", (Exception,), {})

    def __init__(self, online=True, status="Success", out="hello\n", err=""):
        self._online, self._status, self._out, self._err = online, status, out, err
        self.last_send = None

    def send_command(self, **kwargs):
        self.last_send = kwargs
        return {"Command": {"CommandId": "c1"}}

    def get_command_invocation(self, **kwargs):
        return {"Status": self._status,
                "StandardOutputContent": self._out,
                "StandardErrorContent": self._err}

    def describe_instance_information(self, **kwargs):
        lst = [{"PingStatus": "Online"}] if self._online else []
        return {"InstanceInformationList": lst}


class FakeSession:
    def __init__(self, ssm):
        self._ssm = ssm

    def client(self, name):
        return self._ssm


def _patch(monkeypatch, ssm):
    monkeypatch.setattr(remote.awsio, "session", lambda region: FakeSession(ssm))


def test_run_returns_output(monkeypatch):
    _patch(monkeypatch, FakeSSM(out="done\n"))
    status, out, err = remote.run("us-east-1", "i-1", ["echo done"])
    assert status == "Success"
    assert out == "done\n"


def test_is_managed(monkeypatch):
    _patch(monkeypatch, FakeSSM(online=True))
    assert remote.is_managed("us-east-1", "i-1") is True
    _patch(monkeypatch, FakeSSM(online=False))
    assert remote.is_managed("us-east-1", "i-1") is False


def test_update_invokes_ac_update(monkeypatch):
    ssm = FakeSSM()
    _patch(monkeypatch, ssm)
    remote.update("us-east-1", "i-1")
    cmds = ssm.last_send["Parameters"]["commands"]
    assert any("ac-update" in c for c in cmds)


def test_logs_picks_acserver_unit(monkeypatch):
    ssm = FakeSSM()
    _patch(monkeypatch, ssm)
    remote.logs("us-east-1", "i-1", backend="acserver", lines=50)
    cmds = ssm.last_send["Parameters"]["commands"]
    assert any("journalctl -u acserver" in c for c in cmds)
