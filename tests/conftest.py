"""Shared pytest fixtures.

The star fixture is `ac_install`: a synthetic Assetto Corsa content tree on disk,
so the content-discovery and sync logic can be tested with zero real game files.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def _write(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")


@pytest.fixture
def ac_install(tmp_path: Path) -> Path:
    """A fake .../assettocorsa folder with two cars and two tracks.

    Cars:   car_a (packed data.acd)   car_b (unpacked data/ folder)
    Tracks: track_a (single layout)   track_multi (layout1 + layout2)
    Includes a .kn5 and an ai/ spline that the minimal-file logic must EXCLUDE.
    """
    root = tmp_path / "assettocorsa"
    cars = root / "content" / "cars"
    tracks = root / "content" / "tracks"

    # car_a — packed physics, plus heavy files that must NOT be synced
    _write(cars / "car_a" / "data.acd", b"ACD-CAR-A-PHYSICS")
    _write(cars / "car_a" / "ui" / "ui_car.json", json.dumps({"name": "Car A"}))
    _write(cars / "car_a" / "car_a.kn5", b"\x00" * 4096)          # model: excluded
    _write(cars / "car_a" / "skins" / "red" / "livery.dds", b"\x00" * 4096)  # excluded

    # car_b — unpacked data/ folder instead of a data.acd
    _write(cars / "car_b" / "data" / "engine.ini", "[ENGINE]\nPOWER=300\n")
    _write(cars / "car_b" / "ui" / "ui_car.json", json.dumps({"name": "Car B"}))

    # track_a — single layout
    _write(tracks / "track_a" / "data" / "surfaces.ini", "[SURFACE_0]\nKEY=ROAD\n")
    _write(tracks / "track_a" / "models.ini", "[MODEL_0]\nFILE=track.kn5\n")
    _write(tracks / "track_a" / "map.png", b"\x89PNG\r\n")
    _write(tracks / "track_a" / "ui" / "ui_track.json", json.dumps({"name": "Track A"}))
    _write(tracks / "track_a" / "track.kn5", b"\x00" * 8192)       # mesh: excluded
    _write(tracks / "track_a" / "ai" / "fast_lane.ai", b"\x00" * 8192)  # AI: excluded

    # track_multi — two layouts under ui/
    _write(tracks / "track_multi" / "data" / "surfaces.ini", "[SURFACE_0]\nKEY=ROAD\n")
    _write(tracks / "track_multi" / "models_layout1.ini", "[MODEL_0]\nFILE=a.kn5\n")
    _write(tracks / "track_multi" / "models_layout2.ini", "[MODEL_0]\nFILE=b.kn5\n")
    _write(tracks / "track_multi" / "ui" / "layout1" / "ui_track.json",
           json.dumps({"name": "Multi (Layout 1)"}))
    _write(tracks / "track_multi" / "ui" / "layout2" / "ui_track.json",
           json.dumps({"name": "Multi (Layout 2)"}))

    return root


@pytest.fixture
def sample_cfg() -> dict:
    """A representative server.yml as a dict."""
    return {
        "name": "Test Server",
        "backend": "assettoserver",
        "password": "",
        "admin_password": "pw",
        "track": {"id": "track_a", "layout": ""},
        "cars": [
            {"id": "car_a", "count": 2, "skins": []},
            {"id": "car_b", "count": 1},
        ],
        "sessions": {
            "practice": {"enabled": True, "name": "Practice", "time": 0, "is_open": True},
            "qualify": {"enabled": False},
            "race": {"enabled": False},
            "booking": {"enabled": False},
        },
    }


@pytest.fixture
def aws_credentials(monkeypatch):
    """Dummy creds/region so boto3 is happy under moto."""
    for k, v in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SECURITY_TOKEN": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(k, v)
