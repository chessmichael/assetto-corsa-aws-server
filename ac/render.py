"""Render a server.yml definition into the files the AC server consumes:
server_cfg.ini and entry_list.ini. Both AssettoServer and vanilla acServer read
this same format, so the renderer is backend-agnostic (the only backend-specific
bit is the BOOKING session, which is vanilla-only).
"""
from __future__ import annotations

from typing import Dict, List, Tuple

DEFAULT_PORTS = {"tcp": 9600, "udp": 9600, "http": 8081}

# AC has no true "unlimited" session length. TIME=0 makes a time-based session
# (practice/qualify) end instantly and — with loop mode — loop several times a
# second, which resets connected cars repeatedly (they appear to "shake" and
# can't be driven). So map a 0/blank practice or qualify time to a very large
# minute count, i.e. effectively unlimited.
UNLIMITED_MINUTES = 9999


def _session_minutes(minutes) -> int:
    m = int(minutes or 0)
    return m if m > 0 else UNLIMITED_MINUTES


def _assist(val) -> int:
    """ABS/TC allowance for server_cfg: 0 = not allowed, 1 = factory (as the car
    allows), 2 = forced on. Accepts those ints, a bool, or off/factory/on."""
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, int):
        return val
    return {"off": 0, "no": 0, "factory": 1, "default": 1,
            "on": 2, "forced": 2, "yes": 2}.get(str(val).strip().lower(), 1)


def _unique(seq: List[str]) -> List[str]:
    seen, out = set(), []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _kv(lines: List[str], key: str, val) -> None:
    lines.append(f"{key}={val}")


def total_slots(cfg: Dict) -> int:
    cars = sum(int(c.get("count", 1)) for c in cfg.get("cars", []))
    return cars + len(cfg.get("handicaps") or [])


def car_ids(cfg: Dict) -> List[str]:
    return _unique([c["id"] for c in cfg.get("cars", [])])


def render_server_cfg(cfg: Dict, ports: Dict[str, int] = None) -> str:
    ports = ports or DEFAULT_PORTS
    track = cfg.get("track", {})
    sessions = cfg.get("sessions", {})
    slots = total_slots(cfg) or 1
    max_clients = int(cfg.get("max_clients") or slots)

    L: List[str] = ["[SERVER]"]
    _kv(L, "NAME", cfg.get("name", "Assetto Corsa Server"))
    _kv(L, "PASSWORD", cfg.get("password", ""))
    _kv(L, "ADMIN_PASSWORD", cfg.get("admin_password", ""))
    _kv(L, "CARS", ";".join(car_ids(cfg)))
    _kv(L, "TRACK", track.get("id", ""))
    _kv(L, "CONFIG_TRACK", track.get("layout", "") or "")
    _kv(L, "MAX_CLIENTS", max_clients)
    _kv(L, "UDP_PORT", ports["udp"])
    _kv(L, "TCP_PORT", ports["tcp"])
    _kv(L, "HTTP_PORT", ports["http"])
    _kv(L, "REGISTER_TO_LOBBY", 1 if cfg.get("register_to_lobby", True) else 0)
    _kv(L, "PICKUP_MODE_ENABLED", 1)
    _kv(L, "LOOP_MODE", 1)
    _kv(L, "SLEEP_TIME", 1)
    _kv(L, "CLIENT_SEND_INTERVAL_HZ", 18)
    _kv(L, "SEND_BUFFER_SIZE", 0)
    _kv(L, "RECV_BUFFER_SIZE", 0)
    _kv(L, "KICK_QUORUM", 85)
    _kv(L, "VOTING_QUORUM", 80)
    _kv(L, "VOTE_DURATION", 20)
    _kv(L, "BLACKLIST_MODE", 1)

    # --- race rules / realism (the optional `rules:` block; legacy top-level
    #     fuel_rate/damage/tyre_wear keys are still honored for back-compat) ---
    rules = cfg.get("rules") or {}

    def rule(key, default):
        if key in rules:
            return rules[key]
        return cfg.get(key, default)

    _kv(L, "FUEL_RATE", int(rule("fuel_rate", 0)))                  # "gas" use % (default off)
    _kv(L, "DAMAGE_MULTIPLIER", int(rule("damage", 0)))            # default 0 = damage off
    _kv(L, "TYRE_WEAR_RATE", int(rule("tyre_wear", 0)))            # default 0 = no wear
    _kv(L, "ALLOWED_TYRES_OUT", int(rule("tyres_out", 2)))
    _kv(L, "ABS_ALLOWED", _assist(rule("abs", "factory")))
    _kv(L, "TC_ALLOWED", _assist(rule("traction_control", "factory")))
    _kv(L, "STABILITY_ALLOWED", int(rule("stability_control", 0)))
    _kv(L, "AUTOCLUTCH_ALLOWED", 1 if rule("autoclutch", True) else 0)
    _kv(L, "TYRE_BLANKETS_ALLOWED", 1 if rule("tyre_blankets", False) else 0)  # warmers
    _kv(L, "FORCE_VIRTUAL_MIRROR", 1 if rule("force_virtual_mirror", True) else 0)
    legal = rule("legal_tyres", [])
    if legal:
        _kv(L, "LEGAL_TYRES", ";".join(str(t) for t in legal))      # allowed compounds
    _kv(L, "RESULT_SCREEN_TIME", 60)
    _kv(L, "RACE_GAS_PENALTY_DISABLED", 0)
    _kv(L, "MAX_BALLAST_KG", 150)

    # --- sessions (emit only the enabled ones) ---
    p = sessions.get("practice", {})
    if p.get("enabled"):
        L += ["", "[PRACTICE]"]
        _kv(L, "NAME", p.get("name", "Practice"))
        _kv(L, "TIME", _session_minutes(p.get("time", 0)))
        _kv(L, "IS_OPEN", 1 if p.get("is_open", True) else 0)

    q = sessions.get("qualify", {})
    if q.get("enabled"):
        L += ["", "[QUALIFY]"]
        _kv(L, "NAME", q.get("name", "Qualify"))
        _kv(L, "TIME", _session_minutes(q.get("time", 15)))
        _kv(L, "IS_OPEN", 1 if q.get("is_open", True) else 0)

    r = sessions.get("race", {})
    if r.get("enabled"):
        L += ["", "[RACE]"]
        _kv(L, "NAME", r.get("name", "Race"))
        _kv(L, "LAPS", int(r.get("laps", 10)))
        _kv(L, "TIME", int(r.get("time", 0)))
        _kv(L, "WAIT_TIME", int(r.get("wait_time", 60)))
        _kv(L, "IS_OPEN", 1 if r.get("is_open", True) else 0)

    b = sessions.get("booking", {})
    if b.get("enabled"):  # vanilla acServer only
        L += ["", "[BOOKING]"]
        _kv(L, "NAME", b.get("name", "Booking"))
        _kv(L, "TIME", int(b.get("time", 10)))

    # --- weather + dynamic track defaults ---
    w = cfg.get("weather", {})
    L += ["", "[WEATHER_0]"]
    _kv(L, "GRAPHICS", w.get("graphics", "3_clear"))
    _kv(L, "BASE_TEMPERATURE_AMBIENT", w.get("ambient", 18))
    _kv(L, "BASE_TEMPERATURE_ROAD", w.get("road_offset", 6))
    _kv(L, "VARIATION_AMBIENT", 2)
    _kv(L, "VARIATION_ROAD", 2)
    _kv(L, "WIND_BASE_SPEED_MIN", 3)
    _kv(L, "WIND_BASE_SPEED_MAX", 15)
    _kv(L, "WIND_BASE_DIRECTION", 30)
    _kv(L, "WIND_VARIATION_DIRECTION", 15)

    L += ["", "[DYNAMIC_TRACK]"]
    _kv(L, "SESSION_START", 96)
    _kv(L, "RANDOMNESS", 2)
    _kv(L, "SESSION_TRANSFER", 80)
    _kv(L, "LAP_GAIN", 30)

    return "\n".join(L) + "\n"


def _car_entry(L: List[str], idx: int, model: str, skin: str = "", guid: str = "",
               driver: str = "", ballast: int = 0, restrictor: int = 0) -> None:
    L += [f"[CAR_{idx}]"]
    _kv(L, "MODEL", model)
    _kv(L, "SKIN", skin)
    _kv(L, "SPECTATOR_MODE", 0)
    _kv(L, "DRIVERNAME", driver)
    _kv(L, "TEAM", "")
    _kv(L, "GUID", guid)          # set = slot reserved for that Steam ID
    _kv(L, "BALLAST", ballast)    # kg of added weight
    _kv(L, "RESTRICTOR", restrictor)  # 0-100 intake restrictor = less power
    L.append("")


def render_entry_list(cfg: Dict) -> str:
    """Open grid slots, then one reserved (GUID-pinned) slot per handicap. A
    handicap slot carries a restrictor/ballast, so that player silently runs
    with less power than everyone else."""
    L: List[str] = []
    cars = cfg.get("cars", [])
    default_car = cars[0]["id"] if cars else ""
    idx = 0
    for car in cars:
        cid = car["id"]
        skins = car.get("skins") or [""]
        for n in range(int(car.get("count", 1))):
            _car_entry(L, idx, cid, skin=skins[n % len(skins)])
            idx += 1
    for h in cfg.get("handicaps") or []:
        _car_entry(L, idx,
                   model=h.get("car") or default_car,
                   guid=str(h.get("guid", "")),
                   driver=h.get("name", ""),
                   ballast=int(h.get("ballast", 0)),
                   restrictor=int(h.get("restrictor", 0)))
        idx += 1
    return "\n".join(L) + "\n"


def estimate_timezone(longitude) -> str:
    """A valid IANA tz roughly matching a longitude (sun timing). Users can
    override with the real zone; this just keeps the default sensible."""
    try:
        off = round(float(longitude) / 15)
    except (TypeError, ValueError):
        return "Etc/UTC"
    if off == 0:
        return "Etc/UTC"
    # Etc/GMT signs are inverted (Etc/GMT+8 == UTC-8).
    return f"Etc/GMT{-off:+d}"


def render_track_params(track_id: str, latitude, longitude, timezone,
                        name: str = None) -> str:
    """A data_track_params.ini section so AssettoServer's WeatherManager has the
    track's location. Required for tracks not in its community database (mods)."""
    return (f"[{track_id}]\n"
            f"NAME={name or track_id}\n"
            f"LATITUDE={latitude}\n"
            f"LONGITUDE={longitude}\n"
            f"TIMEZONE={timezone}\n")


def validate(cfg: Dict) -> List[str]:
    """Return a list of human-readable problems (empty = OK)."""
    problems = []
    if not cfg.get("track", {}).get("id"):
        problems.append("No track selected.")
    if not cfg.get("cars"):
        problems.append("No cars selected.")
    sessions = cfg.get("sessions", {})
    if not any(s.get("enabled") for s in sessions.values()):
        problems.append("At least one session (practice/qualify/race) must be enabled.")
    if cfg.get("backend") == "assettoserver" and sessions.get("booking", {}).get("enabled"):
        problems.append("Booking sessions are vanilla acServer only; disable booking or switch backend.")
    return problems


def content_refs(cfg: Dict) -> Tuple[List[str], List[Tuple[str, str]]]:
    """Return (car_ids, [(track_id, layout)]) referenced by this server."""
    cars = car_ids(cfg)
    track = cfg.get("track", {})
    tracks = [(track["id"], track.get("layout", ""))] if track.get("id") else []
    return cars, tracks
