"""Tests for content discovery, minimal-file selection, and hashing."""
from __future__ import annotations

from pathlib import Path

from ac import content


def _relset(install: Path, base: Path, files):
    return {p.relative_to(base).as_posix() for p in files}


def test_validate_install(ac_install, tmp_path):
    assert content.validate_install(ac_install)
    assert not content.validate_install(tmp_path / "nope")


def test_list_cars(ac_install):
    cars = content.list_cars(ac_install)
    assert set(cars) == {"car_a", "car_b"}
    assert cars["car_a"]["name"] == "Car A"
    assert cars["car_b"]["name"] == "Car B"


def test_list_tracks_and_layouts(ac_install):
    tracks = content.list_tracks(ac_install)
    assert set(tracks) == {"track_a", "track_multi"}
    assert tracks["track_a"]["layouts"] == []
    assert tracks["track_a"]["name"] == "Track A"
    assert tracks["track_multi"]["layouts"] == ["layout1", "layout2"]


def test_car_server_files_packed(ac_install):
    base = ac_install / "content" / "cars" / "car_a"
    files = content.car_server_files(ac_install, "car_a")
    rel = _relset(ac_install, base, files)
    assert rel == {"data.acd", "ui/ui_car.json"}
    # heavy files must be excluded
    assert not any(p.suffix == ".kn5" for p in files)


def test_car_server_files_unpacked(ac_install):
    base = ac_install / "content" / "cars" / "car_b"
    rel = _relset(ac_install, base, content.car_server_files(ac_install, "car_b"))
    assert rel == {"data/engine.ini", "ui/ui_car.json"}


def test_track_server_files_excludes_kn5_and_ai(ac_install):
    base = ac_install / "content" / "tracks" / "track_a"
    files = content.track_server_files(ac_install, "track_a")
    rel = _relset(ac_install, base, files)
    assert rel == {"data/surfaces.ini", "models.ini", "map.png", "ui/ui_track.json"}
    assert "track.kn5" not in rel
    assert not any("ai" in p.relative_to(base).parts for p in files)


def test_track_server_files_full_includes_everything(ac_install):
    base = ac_install / "content" / "tracks" / "track_a"
    rel = _relset(ac_install, base, content.track_server_files(ac_install, "track_a", full=True))
    assert "track.kn5" in rel
    assert "ai/fast_lane.ai" in rel


def test_parse_geotag_formats():
    assert abs(content._parse_geotag("39° 32′ 23″ N") - 39.5397) < 0.01
    assert content._parse_geotag("122° 20′ 55″ W") < 0      # west = negative
    assert content._parse_geotag("39.54") == 39.54
    assert content._parse_geotag("nope") is None


def test_track_geotags(ac_install):
    lat, lon = content.track_geotags(ac_install, "track_a")
    assert abs(lat - 39.5397) < 0.01
    assert abs(lon + 122.3486) < 0.01                       # ~ -122.35
    # a track with no geotags returns None
    assert content.track_geotags(ac_install, "track_multi") is None


def test_list_skins(ac_install):
    assert content.list_skins(ac_install, "car_a") == ["red"]
    assert content.list_skins(ac_install, "car_b") == []  # no skins folder


def test_hash_is_deterministic_and_change_sensitive(ac_install):
    base = ac_install / "content" / "cars" / "car_a"
    files = content.car_server_files(ac_install, "car_a")
    h1 = content.hash_item(base, files)
    h2 = content.hash_item(base, files)
    assert h1["hash"] == h2["hash"]
    assert set(h1["files"]) == {"data.acd", "ui/ui_car.json"}

    # changing a file changes the hash
    (base / "data.acd").write_bytes(b"DIFFERENT-PHYSICS")
    files2 = content.car_server_files(ac_install, "car_a")
    assert content.hash_item(base, files2)["hash"] != h1["hash"]
