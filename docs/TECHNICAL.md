# Technical Guide

A complete, modify-it-with-confidence reference for `ac-server-aws`. If you're an
agent or developer who needs to understand or change the project, read this top
to bottom. For the friendly setup walkthrough see the [README](../README.md); for
the player join-guide see [PLAYERS.md](PLAYERS.md).

---

## 1. What this project is

It provisions and operates an **Assetto Corsa (AC) dedicated server on AWS**,
joinable from **Content Manager (CM)**, with content (cars/tracks) synced
automatically from the operator's local AC install. Design goals, in priority
order:

1. **No home-network exposure.** Everything the operator's PC does is outbound.
   The server lives in AWS; nobody port-forwards a home router.
2. **No manual content shuffling.** A local tool extracts the minimal server-side
   files from the operator's AC install and syncs only what changed.
3. **One-command infrastructure**, reconfigurable content without re-provisioning.

## 2. Mental model — two layers

```
┌───────────────────────── Operator's PC (Windows) ─────────────────────────┐
│  Terraform  ── provisions ──▶  AWS                                          │
│  ac (Python CLI) ── content + config + control ──▶ AWS (S3 + SSM + EC2)     │
│        ▲ reads local AC install for content                                │
└────────────────────────────────────────────────────────────────────────────┘
                                   │
              ┌────────────────────┴───────────────────┐
              ▼                                         ▼
   ┌──────────────────┐                      ┌────────────────────┐
   │  S3 bucket       │  ── instance pulls ─▶│  EC2 (Ubuntu)      │
   │  cfg/ + content/ │                      │  AssettoServer /   │
   │  + manifest.json │                      │  acServer (systemd)│
   └──────────────────┘                      └────────────────────┘
                                                  ▲ players join (9600/8081)
```

- **Layer 1 — Infrastructure (`terraform/`)** builds the box and is *content-
  agnostic*. Run rarely (`terraform apply`).
- **Layer 2 — Control tool (`ac/`, Python)** owns *what's on the server*: content
  sync, config rendering, start/stop, deploy. Run often. Talks to AWS via boto3
  and to the box via **SSM Run Command** (no SSH).

The two layers communicate only through **terraform outputs** (the CLI reads them
once via `ac init`) and the **S3 bucket** (the CLI writes; the box reads).

## 3. Repository layout

```
terraform/
  versions.tf       provider + version pins (aws ~>5.40, random)
  variables.tf      region, instance_type, ports, allowed_game_cidrs, …
  network.tf        default-VPC lookup + security group (game ports only)
  main.tf           AMI (SSM param), S3 bucket, IAM role/profile, EC2, EIP, user_data assembly
  outputs.tf        public_ip, instance_id, content_bucket, region, cm_connect, …
  user_data.sh      first-boot script (NO shebang — see §5.5)
  terraform.tfvars.example   copy to terraform.tfvars (gitignored)
ac/                 the control CLI (Python package, installed editable)
  cli.py            argparse entrypoint + command implementations + _sync_targets
  state.py          .ac/state.json load/save + find_project_root
  content.py        AC install discovery, car/track enumeration, minimal-file selection, hashing
  awsio.py          boto3 (S3/EC2) + `terraform output -json` reader
  render.py         server.yml -> server_cfg.ini / entry_list.ini
  remote.py         SSM Run Command wrappers (update/status/logs/restart)
  wizard.py         interactive `ac config` (questionary)
tests/              pytest suite (offline + moto-mocked AWS)
scripts/            test.ps1, check-terraform.ps1, smoke-test.ps1/.sh
docs/               PLAYERS.md (this file's sibling) + TECHNICAL.md (this file)
examples/           server.example.yml
server-config/      note on AssettoServer's auto-generated extra_cfg.yml
server.yml          the operator's live config (gitignored — may hold passwords)
.ac/state.json      local state: AC path + terraform outputs (gitignored)
```

---

## 4. Layer 1 — Infrastructure (Terraform)

### 4.1 Networking (`network.tf`)
- Uses the account's **default VPC** and its subnets (`data.aws_vpc.default`,
  `data.aws_subnets.default`). No custom VPC.
- One **security group** with ingress for **TCP+UDP 9600** (game) and **TCP 8081**
  (HTTP/lobby), open to `var.allowed_game_cidrs` (default `0.0.0.0/0`). **There is
  no port-22/SSH rule** — management is SSM-only. Egress is open (the box needs
  GitHub, S3, and SSM endpoints).

### 4.2 Compute & address (`main.tf`)
- **AMI**: latest Ubuntu 24.04 via the public SSM parameter
  `/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id`
  — region-agnostic, no hardcoded AMI IDs. **amd64 only** (see §13 ARM note).
- **EC2 instance**: `var.instance_type`, default `t3.small` in tfvars, on the
  first default subnet, with the SG and the instance profile. IMDSv2 required.
  `user_data_replace_on_change = true` → editing `user_data.sh` replaces the box.
- **Elastic IP** (`aws_eip`) attached to the instance → stable address so CM
  bookmarks survive reboots/stop-start.

### 4.3 Storage & identity (`main.tf`)
- **S3 bucket** `${project}-content-${random_id}`, `force_destroy = true` (so
  `terraform destroy` removes it even when non-empty), public access fully
  blocked.
- **IAM instance role**: `AmazonSSMManagedInstanceCore` (enables SSM management) +
  an inline policy granting **read-only** S3 (`s3:GetObject`, `s3:ListBucket`) on
  the content bucket. The box never writes to S3; the operator's CLI does, using
  the operator's own credentials.

### 4.4 Outputs (`outputs.tf`)
`public_ip`, `instance_id`, `content_bucket`, `region`, `http_port`,
`cm_connect`, `info_url`. The CLI reads these via `terraform output -json`.

### 4.5 First-boot script (`user_data.sh`)
**Critical detail:** this file has **no `#!/bin/bash` shebang**. `main.tf` builds
the real user_data by joining `"#!/bin/bash"` + three `export` lines
(`AC_BUCKET`, `AC_REGION`, `AC_AS_VERSION`) + `file("user_data.sh")`. This uses
Terraform `file()` (not `templatefile()`), so bash `${VAR}` expressions are passed
through verbatim and expanded by bash at runtime — avoiding the
`templatefile`/bash `${}` escaping minefield. **Keep `user_data.sh` free of
Terraform interpolation.**

Boot sequence:
1. Write `/etc/ac.env` with `AC_BUCKET`/`AC_REGION` (sourced by helper scripts).
2. `apt-get` deps: `i386` libs (for the 32-bit vanilla acServer), `libicu74`
   (.NET runtime for AssettoServer), curl/unzip/jq.
3. Install **AWS CLI v2** (for `aws s3 sync` on the box).
4. Install **AssettoServer**: resolve the latest `assetto-server-linux-x64.tar.gz`
   from GitHub releases (or a pinned `AC_AS_VERSION`), extract into
   `/opt/ac/server`, flattening any single top-level dir so the binary lands at
   `/opt/ac/server/AssettoServer`.
5. Optionally install **acServer** from `s3://BUCKET/bin/acServer` if present
   (the vanilla Linux binary can't be fetched anonymously — see §8).
6. Write helper scripts and two systemd units (next section). Neither service is
   enabled at boot — the first `ac deploy` selects and enables one.

### 4.6 On-box runtime layout
```
/opt/ac/server/            data root (AssettoServer extracted here)
  AssettoServer            the binary
  acServer                 optional vanilla binary (if supplied via S3)
  cfg/server_cfg.ini       ← synced from S3
  cfg/entry_list.ini       ← synced from S3
  cfg/extra_cfg.yml        ← AUTO-GENERATED by AssettoServer; never synced (see §13)
  content/cars/<id>/…      ← synced from S3 (minimal data files)
  content/tracks/<id>/…    ← synced from S3
  .backend                 ← "assettoserver" or "acserver"
/usr/local/bin/ac-presync  pull cfg+content from S3 (idempotent; --delete; excludes extra_cfg.yml)
/usr/local/bin/ac-update   ac-presync, then enable+restart the .backend service
/etc/systemd/system/assettoserver.service   ExecStartPre=ac-presync; ExecStart=/opt/ac/server/AssettoServer
/etc/systemd/system/acserver.service        ExecStartPre=ac-presync; ExecStart=/opt/ac/server/acServer
```
`ExecStartPre=ac-presync` means **every** start/reboot/stop-start refreshes
content from S3 automatically.

### 4.7 Key infra design decisions
- **SSM, not SSH** → zero inbound management ports, no key management.
- **EIP** → stable address despite stop/start.
- **Single Terraform state** → simple, but changing `region` *replaces* the box
  (new IP + re-sync). Multi-region-at-once would need workspaces (see §12).
- **Binaries baked by user_data, data synced from S3** → the box can be rebuilt
  from scratch and re-pull all content; content survives instance replacement
  because it lives in S3.

---

## 5. Layer 2 — Control tool (`ac/`)

### 5.1 Module map
| Module | Responsibility |
|---|---|
| `cli.py` | argparse parser, command funcs, `_sync_targets` (the shared sync engine), `_print_result` |
| `state.py` | `.ac/state.json` load/save; `find_project_root` (cwd search → package-location fallback) |
| `content.py` | locate AC install; enumerate cars/tracks; pick minimal server files; SHA-256 manifest |
| `awsio.py` | boto3 S3/EC2 helpers; `terraform_outputs()` via subprocess |
| `render.py` | `server.yml` → `server_cfg.ini` + `entry_list.ini`; `validate`; `content_refs` |
| `remote.py` | SSM `send_command` + poll; `update/status/logs/restart`; `is_managed` |
| `wizard.py` | interactive `ac config` using `questionary` |

Installed **editable** (`pip install -e .`), exposing the `ac` console script
(`ac.cli:main`) and `python -m ac`.

### 5.2 `server.yml` schema (the data model)
```yaml
name: str                     # server browser name
backend: assettoserver|acserver
password: str                 # join password ("" = public)
admin_password: str           # /admin <pw> in chat
register_to_lobby: bool       # default true; false = hidden (join by IP)
track: { id: str, layout: str }   # layout "" if none
cars:                         # the grid; one player slot per count
  - { id: str, count: int, skins: [str] }   # skins optional; cycled across slots
sessions:
  practice: { enabled, name, time(min, 0=unlimited), is_open }
  qualify:  { enabled, name, time, is_open }
  race:     { enabled, name, laps, time(0=use laps), wait_time(sec), is_open }
  booking:  { enabled, name, time }    # acServer only
# optional tuning: fuel_rate, tyre_wear, damage, weather{graphics,ambient,road_offset}
```
Sessions run in order and loop. **If practice `time: 0` (unlimited) it never
advances to race** — give it a finite time for a practice→race cycle.

### 5.3 Command flows
- **`ac init`** → `content.detect_ac_install()` (Steam registry + libraryfolders
  parsing, with a manual prompt fallback) + `awsio.terraform_outputs()` →
  writes `.ac/state.json`.
- **`ac sync [--all] [--full]`** → choose targets (server.yml's referenced
  content, or whole library with `--all`) → `_sync_targets` (§6).
- **`ac config`** → `wizard.run_wizard()` → writes `server.yml`.
- **`ac deploy`** → `render.validate` → `_sync_targets` for referenced content
  (auto-syncs new mods) → `render` + upload `cfg/server_cfg.ini`,
  `cfg/entry_list.ini`, `.backend` to S3 → `remote.update` (SSM) → done.
- **`ac share [--out DIR]`** → prints (or copies full folders of) the track + cars
  a client needs for the active server.
- **`ac start|stop`** → `ec2.start/stop_instances`. **`status|logs|restart`** →
  SSM Run Command.
- **`ac destroy [--yes]`** → `awsio.terraform_destroy` (wraps `terraform
  destroy`) → removes ALL infra including the S3 bucket (`force_destroy`), then
  clears the now-stale outputs from `.ac/state.json`. The true-$0 teardown.
- `cmd_deploy`/`cmd_share` print `_connect_url(st)` — the
  `acmanager://race/online/join?ip=…&httpPort=…` link that joins via CM while
  bypassing the public lobby (and is what you send players).

### 5.4 `_print_result` and Windows consoles
SSM output is printed with `markup=False, highlight=False` and tailed to N lines;
`main()` forces `sys.stdout/stderr` to UTF-8 with `errors="replace"`. This is
because legacy Windows consoles default to cp1252 and crash on characters like
`→` that appear in server output. **Don't remove the UTF-8 reconfigure.**

---

## 6. The content-sync algorithm (`_sync_targets` + `content.py`)

The crux of "no manual content shuffling." Goal: upload only the **small
server-side files**, and only what **changed**.

1. **Minimal file selection** (`content.car_server_files` / `track_server_files`):
   - Car: `data.acd` (or the unpacked `data/` folder) + `ui/ui_car.json`.
   - Track: the whole track folder **except** `*.kn5` (meshes) and any `ai/`
     splines. `--full` includes everything (the checksum-mismatch escape hatch).
2. **Hashing** (`content.hash_item`): for each item, SHA-256 over the sorted list
   of `(relpath, sha256(file))`. Any add/remove/modify changes the item hash.
3. **Manifest diff**: `manifest.json` (top of the bucket) maps `cars`/`tracks` →
   `{hash, files}`. `_sync_targets` downloads it, compares each target's freshly
   computed hash, and uploads only new/changed items' files to
   `s3://BUCKET/server/content/{cars,tracks}/<id>/<relpath>`, then re-writes the
   manifest. Unchanged items are skipped → incremental.
4. **The box pulls**: `ac-presync` runs `aws s3 sync s3://…/server/content
   /opt/ac/server/content --delete`. Because uploads never delete from S3 (no
   prune), content accumulates across servers; the box mirrors the union. Harmless
   extra content; only what `server_cfg.ini` references is loaded.

**Freshness story:** install a mod locally → `ac sync` (or just `ac deploy` a
server that uses it) → manifest detects the new/changed item → uploads only that
→ box `s3 sync` pulls only the delta → restart. Incremental at every hop.

## 7. Config rendering (`render.py`)

`render_server_cfg(cfg, ports)` emits a standard `[SERVER]` block (NAME, PASSWORD,
ADMIN_PASSWORD, CARS=`;`-joined unique ids, TRACK, CONFIG_TRACK=layout,
MAX_CLIENTS=Σcounts, the three ports, REGISTER_TO_LOBBY, pickup/loop, assists,
etc.) plus only the **enabled** session sections, plus default `[WEATHER_0]` and
`[DYNAMIC_TRACK]`. `render_entry_list(cfg)` emits one `[CAR_n]` per grid slot,
cycling skins. Both AssettoServer and acServer read this same format — the
renderer is backend-agnostic (only `[BOOKING]` is acServer-specific).

## 8. The two backends

- **AssettoServer** (default): public GitHub release, installs automatically.
  Freeroam/practice/drift/AI strengths; Race & Qualify are upstream-experimental.
- **acServer** (vanilla): rock-solid Race/Qualify/Booking, but its **Linux binary
  can't be downloaded anonymously**. To enable it: obtain `acServer` (Steam app
  302550, "Assetto Corsa Dedicated Server"), `aws s3 cp` it to
  `s3://BUCKET/bin/acServer`, and either reboot the box or SSM-run the install
  snippet (README "Two server backends"). Then set `backend: acserver`.

Switching is per-server via `server.yml`'s `backend:` field; `ac-update` enables
the chosen systemd unit and disables the other.

## 9. Cost model (real numbers, us-east-2, mid-2026)

| Resource | Running | **Stopped (`ac stop`)** | Destroyed |
|---|---|---|---|
| EC2 t3.small compute | ~$0.021/hr (~$15/mo 24/7) | **$0** | $0 |
| EBS 30 GiB gp3 | ~$2.40/mo | **~$2.40/mo** | $0 |
| Elastic IP (1 IPv4) | ~$3.60/mo | **~$3.60/mo** | $0 |
| S3 (~28 MiB) | ~$0 | **~$0** | $0 |

So **`ac stop` removes the dominant compute cost but ~$6/mo of EIP+EBS keeps
accruing.** `terraform destroy` is the only true-zero state (but you lose the IP
and must re-`apply` + re-sync next time). New accounts draw these from the ~$200
free credits. See README "Cost" for the operator-facing summary.

## 10. Security model

- No inbound management surface (SSM agent dials out; no port 22).
- Operator→AWS is all outbound (S3/SSM/EC2 APIs). Players→server is outbound from
  their side. No home port-forwarding anywhere.
- Instance role is read-only on one bucket. Join password gates players;
  `allowed_game_cidrs` can additionally restrict the game ports to known IPs.

## 11. Testing

`scripts/test.ps1` installs `.[test]` and runs `pytest`. Tiers:
- **Offline** (`test_render.py`, `test_content.py`): renderer + content/hash logic
  against a synthetic AC tree fixture (`tests/conftest.py::ac_install`).
- **Mocked AWS** (`test_sync_aws.py` via `moto`, `test_remote.py` via a fake SSM
  client): `_sync_targets` incrementality, EC2 start/stop, SSM parsing.
- **Terraform static** (`scripts/check-terraform.ps1`): `fmt -check` + `validate`.
- **Real smoke test** (`scripts/smoke-test.ps1/.sh`): `apply` → poll SSM until the
  box reports AssettoServer installed → **always `destroy`**. Costs a few cents.

## 12. How to modify / extend (recipes)

- **Add a `server.yml` option**: add the key to the wizard (`wizard.py`) and the
  renderer (`render.py`); document it in §5.2 and `examples/server.example.yml`.
- **Bigger instance / leave free tier**: upgrade the AWS account to a paid plan,
  set `instance_type` in `terraform.tfvars`, `terraform apply` (replaces the box;
  content re-syncs on boot).
- **Manage AssettoServer `extra_cfg.yml`** (AI traffic, weather): currently
  excluded from sync so the server owns it. To manage it, generate it in
  `render.py`, upload to `s3://…/server/cfg/extra_cfg.yml`, and remove the
  `--exclude extra_cfg.yml` from `ac-presync` in `user_data.sh` (requires box
  re-provision or an SSM patch).
- **Painless multi-region** (keep east + west servers alive): convert to Terraform
  **workspaces** (one state + bucket + EIP per region); have `ac init` record the
  active workspace's outputs. Avoids the destroy/rebuild of a single-state region
  switch.
- **Change the minimal file set**: edit `content.car_server_files` /
  `track_server_files`. If players hit checksum errors, the existing `--full`
  flag copies whole folders.
- **Prune old content from S3**: `awsio.delete_prefix` exists; wire an
  `ac sync --prune` that removes items not in the current manifest.

## 13. Gotchas & lessons (learned the hard way)

- **Windows console encoding**: cp1252 can't encode chars in server output → the
  UTF-8 reconfigure in `main()` and `markup=False` printing are required.
- **Run-from-anywhere**: `find_project_root` searches up from cwd, then falls back
  to the installed package's repo location, so `ac` works from any directory.
- **New AWS accounts are free-tier-restricted**: only free-tier-eligible instance
  types launch (`t3.small`/`t3.micro` are; `t3.medium` is **not**). Query with
  `aws ec2 describe-instance-types --filters Name=free-tier-eligible,Values=true`.
- **ARM is not supported as-is**: the AMI param and AssettoServer download are
  amd64. Using `t4g.*` would require an arm64 AMI + arm64 server binary.
- **Lobby rate-limiting**: refreshing CM's Online list too fast gets you
  temporarily blocked ("can't connect to the internet for servers"). Direct-
  connect (`acmanager://race/online/join?ip=…&httpPort=8081`) bypasses the lobby.
- **Line endings**: `.gitattributes` forces `*.sh` to LF so `user_data.sh` never
  ships CRLF (which would break the Linux boot script).
- **EIP/IPv4 billing**: AWS bills all public IPv4 (incl. attached EIPs) hourly, so
  a *stopped* instance still costs the EIP. See §9.
- **`extra_cfg.yml`**: AssettoServer auto-creates it on first start; the sync
  excludes it so it's never deleted.

## 14. Quick reference

- **Ports**: game TCP+UDP **9600**, HTTP/CM **8081**.
- **Region**: `us-east-2` (set in `terraform.tfvars`).
- **On-box paths**: data `/opt/ac/server`, logs `journalctl -u assettoserver`,
  setup log `/var/log/ac-setup.log`.
- **S3 layout**: `server/cfg/*.ini`, `server/content/{cars,tracks}/<id>/…`,
  `server/.backend`, `manifest.json`, `bin/acServer` (optional).
- **Health check**: `curl http://<ip>:8081/INFO` → server JSON.
- **Commands**: `ac init | sync [--all|--full] | config | deploy | share [--out] |
  start | stop | status | logs [--lines N] | restart | destroy [--yes]`.
- **Direct-connect link**: `acmanager://race/online/join?ip=<ip>&httpPort=8081`
  (Win+R or browser; bypasses the lobby). Printed by `ac deploy`/`ac share`.
