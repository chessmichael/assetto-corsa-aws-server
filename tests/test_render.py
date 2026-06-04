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


def test_practice_time_zero_renders_as_unlimited(sample_cfg):
    # time:0 must NOT emit TIME=0 — that loops the session ~continuously and
    # "shakes" cars. It should become a large finite minute count.
    out = render.render_server_cfg(sample_cfg)  # sample practice time is 0
    practice = out.split("[PRACTICE]")[1].split("\n[")[0]
    assert "TIME=0" not in practice
    assert f"TIME={render.UNLIMITED_MINUTES}" in practice


def test_practice_positive_time_is_preserved(sample_cfg):
    sample_cfg["sessions"]["practice"]["time"] = 30
    out = render.render_server_cfg(sample_cfg)
    practice = out.split("[PRACTICE]")[1].split("\n[")[0]
    assert "TIME=30" in practice


def test_rules_damage_warmers_wear(sample_cfg):
    sample_cfg["rules"] = {"damage": 0, "tyre_blankets": True, "tyre_wear": 50,
                           "fuel_rate": 75}
    out = render.render_server_cfg(sample_cfg)
    assert "DAMAGE_MULTIPLIER=0" in out
    assert "TYRE_BLANKETS_ALLOWED=1" in out
    assert "TYRE_WEAR_RATE=50" in out
    assert "FUEL_RATE=75" in out


def test_rules_assist_mapping(sample_cfg):
    sample_cfg["rules"] = {"abs": "off", "traction_control": "on"}
    out = render.render_server_cfg(sample_cfg)
    assert "ABS_ALLOWED=0" in out
    assert "TC_ALLOWED=2" in out


def test_rules_legal_tyres(sample_cfg):
    sample_cfg["rules"] = {"legal_tyres": ["SM", "SH"]}
    assert "LEGAL_TYRES=SM;SH" in render.render_server_cfg(sample_cfg)


def test_rules_defaults_when_absent(sample_cfg):
    out = render.render_server_cfg(sample_cfg)  # no rules block
    assert "DAMAGE_MULTIPLIER=0" in out         # forgiving defaults: 0
    assert "FUEL_RATE=0" in out
    assert "TYRE_WEAR_RATE=0" in out
    assert "ABS_ALLOWED=1" in out
    assert "LEGAL_TYRES" not in out  # omitted unless restricted


def test_legacy_toplevel_keys_still_work(sample_cfg):
    sample_cfg["damage"] = 50  # old-style top-level key
    assert "DAMAGE_MULTIPLIER=50" in render.render_server_cfg(sample_cfg)


def test_handicap_reserved_slot(sample_cfg):
    sample_cfg["handicaps"] = [
        {"guid": "76561198000000001", "restrictor": 15, "name": "Dave"}]
    out = render.render_entry_list(sample_cfg)
    assert out.count("[CAR_") == 4          # 3 open (2+1) + 1 reserved
    assert "GUID=76561198000000001" in out
    assert "RESTRICTOR=15" in out
    assert "DRIVERNAME=Dave" in out
    reserved = out.split("[CAR_3]")[1]      # the reserved slot
    assert "MODEL=car_a" in reserved        # defaults to the first car


def test_handicap_counts_toward_max_clients(sample_cfg):
    sample_cfg["handicaps"] = [{"guid": "76561198000000001", "restrictor": 10}]
    assert "MAX_CLIENTS=4" in render.render_server_cfg(sample_cfg)  # 3 + 1


def test_no_handicaps_leaves_slots_open(sample_cfg):
    out = render.render_entry_list(sample_cfg)
    assert out.count("[CAR_") == 3
    assert "GUID=\n" in out or "GUID=" in out  # open slots have empty GUID
    assert "RESTRICTOR=0" in out


def test_render_track_params():
    out = render.render_track_params("sometrack", 39.5, -122.3, "Etc/GMT+8")
    assert "[sometrack]" in out
    assert "LATITUDE=39.5" in out
    assert "LONGITUDE=-122.3" in out
    assert "TIMEZONE=Etc/GMT+8" in out


def test_estimate_timezone():
    assert render.estimate_timezone(-122) == "Etc/GMT+8"   # UTC-8
    assert render.estimate_timezone(0) == "Etc/UTC"


def test_content_refs(sample_cfg):
    cars, tracks = render.content_refs(sample_cfg)
    assert cars == ["car_a", "car_b"]
    assert tracks == [("track_a", "")]
