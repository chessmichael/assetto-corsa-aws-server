"""Interactive `ac config` — a menu-driven editor.

Instead of walking every question each time, you pick the section you want to
change (track, cars, sessions, rules, …); everything else is left as-is. Editing
cars lets you keep/add/remove rather than re-entering them. Only offers content
that's actually installed locally.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

import questionary
from rich.console import Console

from . import content, render

console = Console()


# ---------------------------------------------------------------------------
# small input helpers
# ---------------------------------------------------------------------------

def _pick_one(label: str, items: Dict[str, Dict], allow_empty=False) -> Optional[str]:
    """Autocomplete over 'Name  [id]' strings; returns the chosen id."""
    display_to_id = {f"{v['name']}  [{k}]": k for k, v in items.items()}
    choices = sorted(display_to_id.keys(), key=str.lower)
    ans = questionary.autocomplete(
        label, choices=choices,
        validate=lambda t: (allow_empty and t == "") or t in display_to_id,
        ignore_case=True, match_middle=True,
    ).ask()
    if not ans:
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


def _text(label: str, default: str = "") -> str:
    return questionary.text(label, default=default).ask() or default


# ---------------------------------------------------------------------------
# section editors (each mutates cfg in place)
# ---------------------------------------------------------------------------

def _edit_identity(cfg: Dict) -> None:
    cfg["name"] = _text("Server name?", cfg.get("name", "My AC Server"))
    cfg["password"] = _text("Join password (blank = public)?", cfg.get("password", ""))
    cfg["admin_password"] = _text("Admin password (/admin in chat)?",
                                  cfg.get("admin_password", ""))
    cfg["register_to_lobby"] = _yesno("Show in the public lobby?",
                                      cfg.get("register_to_lobby", True))


def _edit_backend(cfg: Dict) -> None:
    b = questionary.select(
        "Server backend?",
        choices=[
            questionary.Choice("AssettoServer — freeroam / practice / drift / AI",
                               "assettoserver"),
            questionary.Choice("acServer (vanilla) — structured race / qualify / booking",
                               "acserver"),
        ],
        default=cfg.get("backend", "assettoserver"),
    ).ask()
    if b:
        cfg["backend"] = b


def _edit_track(tracks: Dict, cfg: Dict) -> None:
    tid = _pick_one("Track (type to search):", tracks)
    if not tid:
        console.print("[yellow]No track chosen — keeping current.[/yellow]")
        return
    layout = ""
    layouts = tracks[tid].get("layouts") or []
    if layouts:
        layout = questionary.select("Layout?", choices=layouts).ask() or ""
    cfg["track"] = {"id": tid, "layout": layout}


def _edit_cars(cars: Dict, cfg: Dict) -> None:
    current = list(cfg.get("cars", []))
    if current:
        console.print("Current cars: " +
                      ", ".join(f"{c['id']} x{c.get('count', 1)}" for c in current))
        action = questionary.select("Cars —", choices=[
            "Keep as-is", "Add more cars", "Remove a car", "Clear and pick fresh",
        ]).ask()
        if action in (None, "Keep as-is"):
            return
        if action == "Clear and pick fresh":
            current = []
        elif action == "Remove a car":
            rm = questionary.checkbox(
                "Select cars to remove:", choices=[c["id"] for c in current]).ask() or []
            cfg["cars"] = [c for c in current if c["id"] not in rm]
            return
        # "Add more cars" falls through, keeping `current`

    console.print("[dim]Add cars one at a time; leave blank to finish.[/dim]")
    while True:
        cid = _pick_one(f"Add car ({len(current)} so far, blank to finish):",
                        cars, allow_empty=True)
        if not cid:
            break
        count = _int(f"  grid slots for '{cars[cid]['name']}'?", 2)
        current.append({"id": cid, "count": count, "skins": []})
    if current:
        cfg["cars"] = current


def _edit_sessions(cfg: Dict) -> None:
    s = cfg.get("sessions", {})
    p, q, r = s.get("practice", {}), s.get("qualify", {}), s.get("race", {})

    if _yesno("Enable PRACTICE (open practice / hotlapping)?", p.get("enabled", True)):
        s["practice"] = {"enabled": True, "name": "Practice",
                         "time": _int("  practice minutes (0 = unlimited)", p.get("time", 0)),
                         "is_open": True}
    else:
        s["practice"] = {"enabled": False}

    if _yesno("Enable QUALIFY (timed laps)?", q.get("enabled", False)):
        s["qualify"] = {"enabled": True, "name": "Qualify",
                        "time": _int("  qualify minutes", q.get("time", 15)),
                        "is_open": _yesno("  allow joining mid-qualify?", q.get("is_open", True))}
    else:
        s["qualify"] = {"enabled": False}

    if _yesno("Enable RACE?", r.get("enabled", False)):
        s["race"] = {"enabled": True, "name": "Race",
                     "laps": _int("  race laps (0 to use a time limit)", r.get("laps", 10)),
                     "time": _int("  race time-limit minutes (0 = use laps)", r.get("time", 0)),
                     "wait_time": _int("  grid wait seconds", r.get("wait_time", 60)),
                     "is_open": _yesno("  allow joining mid-race (pickup)?", r.get("is_open", True))}
    else:
        s["race"] = {"enabled": False}

    if cfg.get("backend") == "acserver":
        b = s.get("booking", {})
        if _yesno("Enable BOOKING (vanilla only)?", b.get("enabled", False)):
            s["booking"] = {"enabled": True, "name": "Booking",
                            "time": _int("  booking minutes", b.get("time", 10))}
        else:
            s["booking"] = {"enabled": False}
    else:
        s.setdefault("booking", {"enabled": False})
    cfg["sessions"] = s


def _edit_rules(cfg: Dict) -> None:
    r = cfg.get("rules", {})
    # defaults are 0 = most forgiving (no damage / fuel use / wear)
    r["damage"] = _int("damage % (0 = off, 100 = full)", r.get("damage", 0))
    r["fuel_rate"] = _int("fuel/gas use % (0 = none)", r.get("fuel_rate", 0))
    r["tyre_wear"] = _int("tyre wear % (0 = none)", r.get("tyre_wear", 0))
    r["tyre_blankets"] = _yesno("tyre warmers (start on hot tyres)?",
                                r.get("tyre_blankets", True))
    r["abs"] = questionary.select("ABS allowed?", choices=["factory", "off", "on"],
                                  default=str(r.get("abs", "factory"))).ask() or "factory"
    r["traction_control"] = questionary.select(
        "Traction control allowed?", choices=["factory", "off", "on"],
        default=str(r.get("traction_control", "factory"))).ask() or "factory"
    cfg["rules"] = r


def _edit_handicaps(cfg: Dict) -> None:
    handicaps = list(cfg.get("handicaps", []))
    if handicaps:
        console.print("Current: " + ", ".join(
            f"{h.get('name') or h.get('guid')} ({h.get('restrictor', 0)}%)" for h in handicaps))
        action = questionary.select("Handicaps —", choices=[
            "Keep as-is", "Add one", "Remove all"]).ask()
        if action in (None, "Keep as-is"):
            return
        if action == "Remove all":
            cfg["handicaps"] = []
            return
    guid = _text("Target Steam ID (17 digits; `ac players` lists them)?")
    if guid.strip():
        handicaps.append({
            "guid": guid.strip(),
            "restrictor": _int("  intake restrictor % (less power; ~12 is subtle)", 12),
            "ballast": _int("  added weight kg (0 = none)", 0),
            "name": _text("  label (optional)?"),
        })
        cfg["handicaps"] = handicaps


_SECTIONS = {
    "identity": lambda inst, cars, tracks, cfg: _edit_identity(cfg),
    "backend": lambda inst, cars, tracks, cfg: _edit_backend(cfg),
    "track": lambda inst, cars, tracks, cfg: _edit_track(tracks, cfg),
    "cars": lambda inst, cars, tracks, cfg: _edit_cars(cars, cfg),
    "sessions": lambda inst, cars, tracks, cfg: _edit_sessions(cfg),
    "rules": lambda inst, cars, tracks, cfg: _edit_rules(cfg),
    "handicaps": lambda inst, cars, tracks, cfg: _edit_handicaps(cfg),
}


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------

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

    # seed sensible defaults so a new config isn't empty
    cfg.setdefault("backend", "assettoserver")
    cfg.setdefault("name", "My AC Server")
    cfg.setdefault("password", "")
    cfg.setdefault("sessions", {
        "practice": {"enabled": True, "name": "Practice", "time": 0, "is_open": True},
        "qualify": {"enabled": False}, "race": {"enabled": False},
        "booking": {"enabled": False}})

    if existing is None:
        console.print("[dim]New server — set a Track and Cars at least, then Save.[/dim]\n")

    while True:
        t = cfg.get("track", {})
        enabled = [k for k, v in (cfg.get("sessions") or {}).items() if v.get("enabled")]
        layout = f"/{t['layout']}" if t.get("layout") else ""
        choice = questionary.select(
            "What do you want to edit?  (pick a section, or Save)",
            choices=[
                questionary.Choice(f"Name / passwords    · {cfg.get('name', '?')}", "identity"),
                questionary.Choice(f"Backend             · {cfg.get('backend')}", "backend"),
                questionary.Choice(f"Track               · {(t.get('id') or '(not set)')}{layout}", "track"),
                questionary.Choice(f"Cars                · {len(cfg.get('cars', []))} selected", "cars"),
                questionary.Choice(f"Sessions            · {', '.join(enabled) or '(none)'}", "sessions"),
                questionary.Choice("Rules               · damage / fuel / tyres / assists", "rules"),
                questionary.Choice(f"Handicaps (prank)   · {len(cfg.get('handicaps', []))} set", "handicaps"),
                questionary.Separator(),
                questionary.Choice("Save & exit", "save"),
                questionary.Choice("Cancel (discard changes)", "cancel"),
            ],
        ).ask()

        if choice in (None, "cancel"):
            console.print("[yellow]Cancelled — nothing written.[/yellow]")
            return None
        if choice == "save":
            problems = render.validate(cfg)
            if problems:
                for p in problems:
                    console.print(f"[red]• {p}[/red]")
                if not _yesno("Save anyway?", False):
                    continue
            return cfg

        _SECTIONS[choice](install, cars, tracks, cfg)
        console.print()
