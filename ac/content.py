"""Discover the local Assetto Corsa install and compute the *minimal* set of
server-side files (plus content hashes) for each car and track.

Key idea: the server only needs the small data/checksum files, never the heavy
visuals. For a car that's `data.acd` (+ an unpacked `data/` folder if present)
and `ui/ui_car.json`. For a track it's everything except the big mesh files
(`*.kn5`) and AI splines. A SHA-256 manifest of those files lets `ac sync`
upload only what changed.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Locating the AC install
# ---------------------------------------------------------------------------

_AC_SUBPATH = Path("steamapps") / "common" / "assettocorsa"


def _steam_roots() -> List[Path]:
    roots: List[Path] = []
    # Windows registry is the most reliable source.
    try:
        import winreg  # type: ignore

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as k:
                    val, _ = winreg.QueryValueEx(k, "SteamPath")
                    roots.append(Path(val))
            except OSError:
                pass
    except ImportError:
        pass

    # Common fixed locations as a fallback.
    import os

    for env in ("ProgramFiles(x86)", "ProgramFiles"):
        base = os.environ.get(env)
        if base:
            roots.append(Path(base) / "Steam")
    roots += [Path(r"C:\Steam"), Path.home() / ".steam" / "steam",
              Path.home() / ".local" / "share" / "Steam"]
    # De-dup while preserving order.
    seen, out = set(), []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _library_paths(steam_root: Path) -> List[Path]:
    """All Steam library roots, parsed from libraryfolders.vdf."""
    libs = [steam_root]
    vdf = steam_root / "steamapps" / "libraryfolders.vdf"
    if vdf.is_file():
        text = vdf.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r'"(?:path|\d+)"\s+"([^"]+)"', text):
            libs.append(Path(m.group(1).replace("\\\\", "\\")))
    return libs


def detect_ac_install() -> Optional[Path]:
    """Return the assettocorsa folder if we can find it, else None."""
    for root in _steam_roots():
        for lib in _library_paths(root):
            cand = lib / _AC_SUBPATH
            if (cand / "content").is_dir():
                return cand
    return None


def validate_install(path: Path) -> bool:
    return (path / "content" / "cars").is_dir() and (path / "content" / "tracks").is_dir()


# ---------------------------------------------------------------------------
# Reading display names
# ---------------------------------------------------------------------------

def _read_name(json_path: Path, fallback: str) -> str:
    try:
        data = json.loads(json_path.read_text(encoding="utf-8-sig"))
        name = data.get("name")
        if name:
            return str(name).strip()
    except (OSError, ValueError):
        # Some mod jsons are malformed; salvage the name field by regex.
        try:
            txt = json_path.read_text(encoding="utf-8-sig", errors="ignore")
            m = re.search(r'"name"\s*:\s*"([^"]+)"', txt)
            if m:
                return m.group(1).strip()
        except OSError:
            pass
    return fallback


# ---------------------------------------------------------------------------
# Enumerating cars and tracks
# ---------------------------------------------------------------------------

def list_cars(install: Path) -> Dict[str, Dict]:
    cars: Dict[str, Dict] = {}
    base = install / "content" / "cars"
    if not base.is_dir():
        return cars
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        if not ((d / "data.acd").is_file() or (d / "data").is_dir()):
            continue  # not a real car folder
        cars[d.name] = {
            "id": d.name,
            "name": _read_name(d / "ui" / "ui_car.json", d.name),
            "path": d,
        }
    return cars


def list_skins(install: Path, car_id: str) -> List[str]:
    """Available skin (livery / color) folder names for a car. These are the
    values you put in a car's `skins:` list in server.yml. Empty `skins:` lets
    each player pick their own color when they join."""
    base = install / "content" / "cars" / car_id / "skins"
    if not base.is_dir():
        return []
    return [d.name for d in sorted(base.iterdir()) if d.is_dir()]


def list_tracks(install: Path) -> Dict[str, Dict]:
    tracks: Dict[str, Dict] = {}
    base = install / "content" / "tracks"
    if not base.is_dir():
        return tracks
    for d in sorted(base.iterdir()):
        if not d.is_dir():
            continue
        ui = d / "ui"
        layouts: List[str] = []
        name = d.name
        if ui.is_dir():
            sub = [s for s in sorted(ui.iterdir())
                   if s.is_dir() and (s / "ui_track.json").is_file()]
            if sub:
                layouts = [s.name for s in sub]
                name = _read_name(sub[0] / "ui_track.json", d.name)
            else:
                name = _read_name(ui / "ui_track.json", d.name)
        if not (ui.is_dir() or (d / "models.ini").is_file()
                or list(d.glob("models_*.ini"))):
            continue  # not a track folder
        tracks[d.name] = {"id": d.name, "name": name, "layouts": layouts, "path": d}
    return tracks


# ---------------------------------------------------------------------------
# Minimal server-side file sets
# ---------------------------------------------------------------------------

_TRACK_SKIP_EXT = {".kn5"}


def car_server_files(install: Path, car_id: str, full: bool = False) -> List[Path]:
    base = install / "content" / "cars" / car_id
    if not base.is_dir():
        return []
    if full:
        return [p for p in base.rglob("*") if p.is_file()]
    out: List[Path] = []
    if (base / "data.acd").is_file():
        out.append(base / "data.acd")
    if (base / "data").is_dir():
        out += [p for p in (base / "data").rglob("*") if p.is_file()]
    if (base / "ui" / "ui_car.json").is_file():
        out.append(base / "ui" / "ui_car.json")
    return out


def track_server_files(install: Path, track_id: str, full: bool = False) -> List[Path]:
    base = install / "content" / "tracks" / track_id
    if not base.is_dir():
        return []
    out: List[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        rel_parts = p.relative_to(base).parts
        if not full:
            if p.suffix.lower() in _TRACK_SKIP_EXT:
                continue  # skip heavy mesh files
            if "ai" in rel_parts:
                continue  # skip AI splines (only needed for AI traffic)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# Hashing / manifest
# ---------------------------------------------------------------------------

def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hash_item(base: Path, files: List[Path]) -> Dict:
    """Return {'hash', 'files'} for a content item.

    `files` are relative-to-base paths (posix style) paired with per-file hashes;
    the item hash is a SHA-256 over the sorted (relpath, filehash) list so any
    add/remove/modify changes it.
    """
    entries = []
    for p in files:
        rel = p.relative_to(base).as_posix()
        entries.append((rel, _sha256_file(p)))
    entries.sort()
    roll = hashlib.sha256()
    for rel, fh in entries:
        roll.update(rel.encode())
        roll.update(fh.encode())
    return {"hash": roll.hexdigest(), "files": [rel for rel, _ in entries]}


def build_car_entry(install: Path, car_id: str, full: bool = False) -> Dict:
    base = install / "content" / "cars" / car_id
    return hash_item(base, car_server_files(install, car_id, full))


def build_track_entry(install: Path, track_id: str, full: bool = False) -> Dict:
    base = install / "content" / "tracks" / track_id
    return hash_item(base, track_server_files(install, track_id, full))
