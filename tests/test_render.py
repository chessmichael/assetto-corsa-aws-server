"""Tests for rendering server.yml -> server_cfg.ini / entry_list.ini."""
from __future__ import annotations

from ac import render


def test_server_cfg_basic_fields(sample_cfg):
    out = render.render_server_cfg(sample_cfg)
    assert "NAME=Test Server" in out
    assert "CARS=car_a;car_b" in out
    assert "TRACK=track_a" in out
    assert "ADMIN_PASSWORD=pw" in out
    # 2 + 1 grid slots -> MAX_CLIENTS=3
    assert "MAX_CLIENTS=3" in out
    # only practice is enabled
    assert "[PRACTICE]" in out
    assert "[RACE]" not in out
    assert "[QUALIFY]" not in out


def test_server_cfg_layout(sample_cfg):
    sample_cfg["track"]["layout"] = "endurance"
    assert "CONFIG_TRACK=endurance" in render.render_server_cfg(sample_cfg)


def test_server_cfg_ports_override(sample_cfg):
    out = render.render_server_cfg(sample_cfg, {"tcp": 9700, "udp": 9700, "http": 8090})
    assert "TCP_PORT=9700" in out
    assert "UDP_PORT=9700" in out
    assert "HTTP_PORT=8090" in out


def test_race_session_fields(sample_cfg):
    sample_cfg["sessions"]["race"] = {
        "enabled": True, "name": "GP", "laps": 12, "time": 0,
        "wait_time": 45, "is_open": False,
    }
    out = render.render_server_cfg(sample_cfg)
    assert "[RACE]" in out
    assert "LAPS=12" in out
    assert "WAIT_TIME=45" in out
    assert "IS_OPEN=0" in out


def test_entry_list_slot_counts(sample_cfg):
    out = render.render_entry_list(sample_cfg)
    assert out.count("[CAR_") == 3
    assert out.count("MODEL=car_a") == 2
    assert out.count("MODEL=car_b") == 1
    # slots are numbered contiguously from 0
    assert "[CAR_0]" in out and "[CAR_2]" in out


def test_entry_list_skin_cycling(sample_cfg):
    sample_cfg["cars"] = [{"id": "car_a", "count": 3, "skins": ["red", "blue"]}]
    out = render.render_entry_list(sample_cfg)
    assert out.count("SKIN=red") == 2   # slots 0 and 2
    assert out.count("SKIN=blue") == 1  # slot 1


def test_validate_catches_problems():
    problems = render.validate({"cars": [], "track": {}, "sessions": {}})
    joined = " ".join(problems)
    assert "track" in joined.lower()
    assert "car" in joined.lower()
    assert "session" in joined.lower()


def test_validate_booking_requires_acserver(sample_cfg):
    sample_cfg["backend"] = "assettoserver"
    sample_cfg["sessions"]["booking"] = {"enabled": True}
    assert any("booking" in p.lower() for p in render.validate(sample_cfg))
    # valid on acserver
    sample_cfg["backend"] = "acserver"
    assert not any("booking" in p.lower() for p in render.validate(sample_cfg))


def test_content_refs(sample_cfg):
    cars, tracks = render.content_refs(sample_cfg)
    assert cars == ["car_a", "car_b"]
    assert tracks == [("track_a", "")]
