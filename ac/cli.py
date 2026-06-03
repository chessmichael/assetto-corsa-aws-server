"""ac — command-line entry point.

  ac init                 detect AC install + read terraform outputs
  ac sync [--all] [--full]  upload changed server-side content to S3
  ac config [--file f]    interactive wizard -> server.yml
  ac deploy [--file f]    sync referenced content, render configs, restart backend
  ac share [--file f] [--out dir]   client-side content set for friends
  ac start | stop | status | logs [--lines n] | restart
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import yaml
from rich.console import Console

from . import awsio, content, remote, render, state
from .state import find_project_root

console = Console()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _root() -> Path:
    return find_project_root()


def _load_yaml(path: Path) -> Dict:
    if not path.is_file():
        raise SystemExit(f"{path.name} not found. Run `ac config` first.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_yaml(path: Path, data: Dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def _tf(st: Dict) -> Tuple[str, str, str]:
    """Return (region, bucket, instance_id) from saved terraform outputs."""
    return (state.require(st, "region"),
            state.require(st, "content_bucket"),
            state.require(st, "instance_id"))


def _print_result(title: str, status: str, out: str, err: str, max_lines: int = 40) -> None:
    color = "green" if status == "Success" else "red"
    console.print(f"[{color}]{title}: {status}[/{color}]")

    def _tail(s: str) -> str:
        lines = s.strip().splitlines()
        return "\n".join(lines[-max_lines:])

    # markup=False/highlight=False so brackets or odd chars in command output
    # are never interpreted by rich.
    if out.strip():
        console.print(_tail(out), markup=False, highlight=False)
    if err.strip():
        console.print(_tail(err), markup=False, highlight=False, style="yellow")


def _connect_url(st: Dict) -> str:
    """The Content Manager direct-connect link — bypasses the public lobby.
    Paste into Windows Run (Win+R) or a browser, or send it to friends."""
    tf = st.get("terraform", {})
    ip = tf.get("public_ip", "<ip>")
    port = tf.get("http_port", 8081)
    return f"acmanager://race/online/join?ip={ip}&httpPort={port}"


# ---------------------------------------------------------------------------
# content sync (shared by `sync` and `deploy`)
# ---------------------------------------------------------------------------

def _sync_targets(st: Dict, install: Path, car_list: List[str],
                  track_list: List[str], full: bool) -> int:
    region, bucket, _ = _tf(st)
    manifest = awsio.get_json(region, bucket, "manifest.json") or {"cars": {}, "tracks": {}}
    manifest.setdefault("cars", {})
    manifest.setdefault("tracks", {})

    uploaded = 0
    plan: List[Tuple[Path, str]] = []

    def consider(kind: str, item_id: str):
        nonlocal uploaded
        if kind == "cars":
            base = install / "content" / "cars" / item_id
            files = content.car_server_files(install, item_id, full)
            entry = content.hash_item(base, files)
        else:
            base = install / "content" / "tracks" / item_id
            files = content.track_server_files(install, item_id, full)
            entry = content.hash_item(base, files)
        if not files:
            console.print(f"  [yellow]skip {kind}/{item_id}: not found locally[/yellow]")
            return
        prev = manifest[kind].get(item_id)
        if prev and prev.get("hash") == entry["hash"]:
            return  # unchanged
        for p in files:
            rel = p.relative_to(base).as_posix()
            plan.append((p, f"server/content/{kind}/{item_id}/{rel}"))
        manifest[kind][item_id] = entry
        uploaded += 1
        console.print(f"  [cyan]queued {kind}/{item_id}[/cyan] "
                      f"({len(files)} files, {'changed' if prev else 'new'})")

    for c in car_list:
        consider("cars", c)
    for t in track_list:
        consider("tracks", t)

    if not plan:
        console.print("  [green]everything already up to date[/green]")
        return 0

    console.print(f"Uploading {len(plan)} files…")
    awsio.upload_files(region, bucket, plan)
    awsio.put_json(region, bucket, "manifest.json", manifest)
    console.print(f"[green]synced {uploaded} item(s)[/green]")
    return uploaded


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_init(args) -> None:
    root = _root()
    st = state.load_state(root)

    install = content.detect_ac_install()
    if install:
        console.print(f"Detected AC install: [cyan]{install}[/cyan]")
    if not install or not content.validate_install(install):
        import questionary
        ans = questionary.path("Path to your assettocorsa folder:").ask()
        if not ans:
            raise SystemExit("AC install path is required.")
        install = Path(ans)
        if not content.validate_install(install):
            raise SystemExit(f"{install} doesn't look like an AC install (no content/cars).")
    st["ac_install"] = str(install)

    console.print("Reading terraform outputs…")
    outs = awsio.terraform_outputs(root)
    needed = ["region", "content_bucket", "instance_id", "public_ip", "http_port"]
    st["terraform"] = {k: outs[k] for k in needed if k in outs}
    missing = [k for k in needed if k not in outs]
    if missing:
        console.print(f"[yellow]Warning: missing outputs {missing} — has apply finished?[/yellow]")

    state.save_state(st, root)
    console.print("[green]Saved .ac/state.json[/green]")
    if "public_ip" in st["terraform"]:
        ip = st["terraform"]["public_ip"]
        port = st["terraform"].get("http_port", 8081)
        console.print(f"Server address for Content Manager: [bold]{ip}:{port}[/bold]")


def cmd_sync(args) -> None:
    root = _root()
    st = state.load_state(root)
    install = state.ac_install(st)

    if args.all:
        cars = list(content.list_cars(install).keys())
        tracks = list(content.list_tracks(install).keys())
        console.print(f"Syncing entire library: {len(cars)} cars, {len(tracks)} tracks")
    else:
        cfg = _load_yaml(root / args.file)
        cars, track_refs = render.content_refs(cfg)
        tracks = [t for t, _ in track_refs]
        console.print(f"Syncing content for '{cfg.get('name','server')}'")
    _sync_targets(st, install, cars, tracks, args.full)


def cmd_config(args) -> None:
    from . import wizard
    root = _root()
    st = state.load_state(root)
    install = state.ac_install(st)
    path = root / args.file
    existing = _load_yaml(path) if path.is_file() else None
    cfg = wizard.run_wizard(install, existing)
    if cfg is None:
        console.print("[yellow]Cancelled — nothing written.[/yellow]")
        return
    problems = render.validate(cfg)
    if problems:
        for p in problems:
            console.print(f"[red]• {p}[/red]")
        console.print("[yellow]Config saved anyway; fix the above before deploying.[/yellow]")
    _save_yaml(path, cfg)
    console.print(f"[green]Wrote {path.name}[/green]  (run `ac deploy` to apply)")


def cmd_deploy(args) -> None:
    root = _root()
    st = state.load_state(root)
    install = state.ac_install(st)
    region, bucket, instance_id = _tf(st)
    cfg = _load_yaml(root / args.file)

    problems = render.validate(cfg)
    if problems:
        for p in problems:
            console.print(f"[red]• {p}[/red]")
        raise SystemExit("Fix the config problems above, then re-run `ac deploy`.")

    # 1. Make sure this server's content is on S3 (auto-sync new/changed mods).
    console.print("[bold]1/3 Ensuring content is synced…[/bold]")
    cars, track_refs = render.content_refs(cfg)
    _sync_targets(st, install, cars, [t for t, _ in track_refs], full=False)

    # 2. Render + upload configs and the backend selector.
    console.print("[bold]2/3 Rendering and uploading configs…[/bold]")
    ports = {"tcp": 9600, "udp": 9600,
             "http": int(st["terraform"].get("http_port", 8081))}
    awsio.put_text(region, bucket, "server/cfg/server_cfg.ini",
                   render.render_server_cfg(cfg, ports))
    awsio.put_text(region, bucket, "server/cfg/entry_list.ini",
                   render.render_entry_list(cfg))
    awsio.put_text(region, bucket, "server/.backend",
                   cfg.get("backend", "assettoserver"))

    # 3. Tell the box (over SSM) to pull and restart.
    console.print("[bold]3/3 Restarting the server via SSM…[/bold]")
    if not remote.is_managed(region, instance_id):
        console.print("[yellow]Instance isn't reporting to SSM yet. If you just ran "
                      "apply or `ac start`, give it ~1 minute and retry.[/yellow]")
    status, out, err = remote.update(region, instance_id)
    if status == "Success":
        console.print("[green]3/3 deploy: Success[/green]")
    else:
        _print_result("deploy", status, out, err)
        raise SystemExit("Deploy command failed on the server. Check `ac logs`.")
    ip = st["terraform"].get("public_ip", "<ip>")
    console.print(f"\n[green]Done.[/green] Join in Content Manager at "
                  f"[bold]{ip}:{ports['http']}[/bold]")
    console.print("[dim]Backup if it doesn't show in the lobby — paste into Win+R "
                  "(or send to friends):[/dim]")
    console.print(f"  {_connect_url(st)}")


def cmd_share(args) -> None:
    root = _root()
    st = state.load_state(root)
    install = state.ac_install(st)
    cfg = _load_yaml(root / args.file)
    cars, track_refs = render.content_refs(cfg)
    track_ids = [t for t, _ in track_refs]

    console.print(f"[bold]Content your friends need for '{cfg.get('name','server')}':[/bold]")
    console.print("  Track(s): " + ", ".join(track_ids))
    console.print("  Car(s):   " + ", ".join(cars))
    console.print("[dim]They need the FULL mods (models/textures), not just the "
                  "server data files — install the exact items above.[/dim]")
    console.print("\n[bold]Send them this to join[/bold] (direct-connect, bypasses the lobby):")
    console.print(f"  link:     {_connect_url(st)}   (paste into Win+R or a browser)")
    console.print(f"  password: {cfg.get('password') or '(none)'}")

    if not args.out:
        console.print("\nRe-run with [cyan]--out <folder>[/cyan] to copy the full "
                      "content there for zipping/sharing.")
        return

    out = Path(args.out)
    all_cars = content.list_cars(install)
    all_tracks = content.list_tracks(install)
    copied = 0
    for cid in cars:
        src = all_cars.get(cid, {}).get("path")
        if src:
            shutil.copytree(src, out / "content" / "cars" / cid, dirs_exist_ok=True)
            copied += 1
    for tid in track_ids:
        src = all_tracks.get(tid, {}).get("path")
        if src:
            shutil.copytree(src, out / "content" / "tracks" / tid, dirs_exist_ok=True)
            copied += 1
    console.print(f"[green]Copied {copied} full content folder(s) to {out}[/green]")


def cmd_start(args) -> None:
    st = state.load_state(_root())
    region, _, instance_id = _tf(st)
    console.print(f"Starting {instance_id}…")
    awsio.start_instance(region, instance_id)
    console.print("[green]Start requested.[/green] The selected backend auto-starts "
                  "and refreshes content on boot. Use `ac status` once it's up.")


def cmd_stop(args) -> None:
    st = state.load_state(_root())
    region, _, instance_id = _tf(st)
    console.print(f"Stopping {instance_id}…")
    awsio.stop_instance(region, instance_id)
    console.print("[green]Stop requested.[/green] Compute billing stops.")
    console.print("[yellow]Note:[/yellow] this is not $0 — the Elastic IP (~$3.60/mo) "
                  "and the EBS disk (~$2.40/mo) keep billing while stopped (~$6/mo total), "
                  "so your IP + content persist and `ac start` resumes fast.")
    console.print("[dim]For a true-zero teardown run `terraform destroy` "
                  "(loses the IP + synced content; rebuild with apply + ac sync).[/dim]")


def cmd_status(args) -> None:
    st = state.load_state(_root())
    region, _, instance_id = _tf(st)
    s = awsio.instance_state(region, instance_id)
    console.print(f"EC2 instance state: [bold]{s}[/bold]")
    if s != "running":
        console.print("Start it with `ac start`.")
        return
    if not remote.is_managed(region, instance_id):
        console.print("[yellow]Not reporting to SSM yet (give it a minute).[/yellow]")
        return
    status, out, err = remote.status(region, instance_id)
    _print_result("status", status, out, err)


def cmd_logs(args) -> None:
    root = _root()
    st = state.load_state(root)
    region, _, instance_id = _tf(st)
    backend = "assettoserver"
    cfg_path = root / args.file
    if cfg_path.is_file():
        backend = (_load_yaml(cfg_path).get("backend") or "assettoserver")
    status, out, err = remote.logs(region, instance_id, backend, args.lines)
    _print_result(f"logs ({backend})", status, out, err)


def cmd_restart(args) -> None:
    st = state.load_state(_root())
    region, _, instance_id = _tf(st)
    status, out, err = remote.restart(region, instance_id)
    _print_result("restart", status, out, err)


def cmd_destroy(args) -> None:
    """Tear down EVERYTHING — true $0. Wraps `terraform destroy`."""
    root = _root()
    console.print("[red bold]This permanently destroys EVERYTHING for this project:[/red bold] "
                  "the EC2 instance, the Elastic IP, the disk, and the S3 content bucket "
                  "(synced content included). Billing drops to $0.")
    console.print("[dim]You'll lose the stable IP and synced content. Rebuild later with "
                  "`terraform apply` -> `ac init` -> `ac sync`/`ac deploy`.[/dim]")
    if not args.yes:
        console.print("[yellow]terraform will ask you to confirm with 'yes'.[/yellow]")
    rc = awsio.terraform_destroy(root, auto_approve=args.yes)
    if rc != 0:
        raise SystemExit(f"terraform destroy did not complete (exit {rc}).")
    # The saved outputs (IP, instance id, bucket) are now stale — drop them.
    st = state.load_state(root)
    if st.pop("terraform", None) is not None:
        state.save_state(st, root)
    console.print("[green]Destroyed. This project now costs $0 on AWS.[/green]")


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ac", description="Control your AWS Assetto Corsa server.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="detect AC install + read terraform outputs").set_defaults(func=cmd_init)

    sp = sub.add_parser("sync", help="upload changed server-side content to S3")
    sp.add_argument("--all", action="store_true", help="sync your whole library, not just the active server's content")
    sp.add_argument("--full", action="store_true", help="include full folders (heavy) instead of the minimal data files")
    sp.add_argument("--file", default="server.yml")
    sp.set_defaults(func=cmd_sync)

    sp = sub.add_parser("config", help="interactive wizard -> server.yml")
    sp.add_argument("--file", default="server.yml")
    sp.set_defaults(func=cmd_config)

    sp = sub.add_parser("deploy", help="sync content, render configs, restart backend")
    sp.add_argument("--file", default="server.yml")
    sp.set_defaults(func=cmd_deploy)

    sp = sub.add_parser("share", help="show/copy the client content friends need")
    sp.add_argument("--file", default="server.yml")
    sp.add_argument("--out", help="copy full content folders into this directory")
    sp.set_defaults(func=cmd_share)

    sub.add_parser("start", help="start the EC2 instance").set_defaults(func=cmd_start)
    sub.add_parser("stop", help="stop the EC2 instance (save cost)").set_defaults(func=cmd_stop)
    sub.add_parser("status", help="instance + service status via SSM").set_defaults(func=cmd_status)
    sub.add_parser("restart", help="restart the active backend via SSM").set_defaults(func=cmd_restart)

    sp = sub.add_parser("destroy", help="tear down ALL AWS resources (true $0)")
    sp.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    sp.set_defaults(func=cmd_destroy)

    sp = sub.add_parser("logs", help="tail server logs via SSM")
    sp.add_argument("--lines", type=int, default=200)
    sp.add_argument("--file", default="server.yml")
    sp.set_defaults(func=cmd_logs)

    return p


def main(argv=None) -> None:
    # Windows consoles default to cp1252, which can't encode characters that
    # show up in server log output (e.g. arrows). Force UTF-8 so printing never
    # crashes the tool.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        sys.exit(130)


if __name__ == "__main__":
    main()
