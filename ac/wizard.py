"""Interactive `ac config` wizard. Builds/edits a server.yml using only the
content actually installed locally, so you can never pick a car/track the server
won't have.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import questionary
from rich.console import Console

from . import content

console = Console()


def _pick_one(label: str, items: Dict[str, Dict], allow_empty=False) -> Optional[str]:
    """Autocomplete over 'Name  [id]' strings; returns the chosen id."""
    display_to_id = {f"{v['name']}  [{k}]": k for k, v in items.items()}
    choices = sorted(display_to_id.keys(), key=str.lower)
    ans = questionary.autocomplete(
        label, choices=choices,
        validate=lambda t: (allow_empty and t == "") or t in display_to_id,
        ignore_case=True, match_middle=True,
    ).ask()
    if ans is None or ans == "":
        return None
    return display_to_id.get(ans)


def _yesno(label: str, default: bool) -> bool:
    return bool(questionary.confirm(label, default=default).ask())


def _int(label: str, default: int) -> int:
    ans = questionary.text(
        label, default=str(default),
        validate=lambda t: t.isdigit() or "Enter a whole number",
    ).ask()
    return int(ans) if ans is not None else default


def run_wizard(install: Path, existing: Optional[Dict] = None) -> Optional[Dict]:
    cfg: Dict = existing.copy() if existing else {}

    console.print("[bold]Scanning your Assetto Corsa content…[/bold]")
    cars = content.list_cars(install)
    tracks = content.list_tracks(install)
    console.print(f"  found [cyan]{len(cars)}[/cyan] cars, "
                  f"[cyan]{len(tracks)}[/cyan] tracks\n")
    if not cars or not tracks:
        console.print("[red]No cars/tracks found. Is the AC install path correct?[/red]")
        return None

    # --- backend ---
    backend = questionary.select(
        "Server backend?",
        choices=[
            questionary.Choice("AssettoServer — freeroam / open practice / drift / AI",
                               value="assettoserver"),
            questionary.Choice("acServer (vanilla) — structured race / qualify / booking",
                               value="acserver"),
        ],
        default="assettoserver" if cfg.get("backend") != "acserver" else "acserver",
    ).ask()
    if backend is None:
        return None
    cfg["backend"] = backend

    # --- identity ---
    cfg["name"] = questionary.text(
        "Server name (as shown in the list)?",
        default=cfg.get("name", "My AC Server"),
    ).ask()
    cfg["password"] = questionary.text(
        "Join password (blank = public)?", default=cfg.get("password", "")
    ).ask()
    cfg["admin_password"] = questionary.text(
        "Admin password (for /admin in chat)?",
        default=cfg.get("admin_password", ""),
    ).ask()

    # --- track ---
    console.print("\n[bold]Track[/bold] (type to search)")
    track_id = _pick_one("Track:", tracks)
    if not track_id:
        console.print("[red]A track is required.[/red]")
        return None
    layout = ""
    layouts = tracks[track_id].get("layouts") or []
    if layouts:
        layout = questionary.select("Layout?", choices=layouts).ask() or ""
    cfg["track"] = {"id": track_id, "layout": layout}

    # --- cars ---
    console.print("\n[bold]Cars[/bold] — add one at a time; leave blank to finish")
    selected: List[Dict] = []
    while True:
        cid = _pick_one(f"Add car ({len(selected)} so far, blank to finish):",
                        cars, allow_empty=True)
        if not cid:
            break
        count = _int(f"  grid slots for '{cars[cid]['name']}'?", 1)
        selected.append({"id": cid, "count": count, "skins": []})
    if not selected:
        console.print("[red]At least one car is required.[/red]")
        return None
    cfg["cars"] = selected

    # --- sessions ---
    console.print("\n[bold]Sessions[/bold]")
    sessions: Dict[str, Dict] = cfg.get("sessions", {})

    if _yesno("Enable PRACTICE (open practice / hotlapping)?", True):
        sessions["practice"] = {
            "enabled": True, "name": "Practice",
            "time": _int("  practice minutes (0 = unlimited)", 0),
            "is_open": True,
        }
    else:
        sessions["practice"] = {"enabled": False}

    if _yesno("Enable QUALIFY (timed laps / time-trial style)?", False):
        sessions["qualify"] = {
            "enabled": True, "name": "Qualify",
            "time": _int("  qualify minutes", 15),
            "is_open": _yesno("  allow joining mid-qualify?", True),
        }
    else:
        sessions["qualify"] = {"enabled": False}

    if _yesno("Enable RACE?", False):
        sessions["race"] = {
            "enabled": True, "name": "Race",
            "laps": _int("  race laps (0 to use a time limit)", 10),
            "time": _int("  race time limit minutes (0 = use laps)", 0),
            "wait_time": _int("  pre-race wait seconds", 60),
            "is_open": _yesno("  allow joining mid-race (pickup)?", True),
        }
    else:
        sessions["race"] = {"enabled": False}

    if backend == "acserver":
        if _yesno("Enable BOOKING (vanilla only)?", False):
            sessions["booking"] = {"enabled": True, "name": "Booking",
                                   "time": _int("  booking minutes", 10)}
        else:
            sessions["booking"] = {"enabled": False}
    else:
        sessions["booking"] = {"enabled": False}

    cfg["sessions"] = sessions
    return cfg
